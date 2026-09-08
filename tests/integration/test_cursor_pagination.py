import base64
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from httpx import AsyncClient
from pytest import fixture, mark, param, raises
from sqlalchemy import Numeric, asc, desc, event, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


@fixture
async def item(engine: AsyncEngine, session: AsyncSession) -> type[Any]:
    class Base(DeclarativeBase):
        pass

    class Item(Base):
        __tablename__ = "cursor_item"
        cohort: Mapped[int] = mapped_column(primary_key=True)
        id: Mapped[int] = mapped_column(primary_key=True)
        name: Mapped[str]
        optional: Mapped[str | None]
        flag: Mapped[bool] = mapped_column(default=False)
        day: Mapped[date]
        timestamp: Mapped[datetime]
        token: Mapped[UUID]
        amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session.add_all(
        Item(
            cohort=cohort, id=id_, name=f"{cohort}{id_}", day=date(2026, 1, n),
            timestamp=datetime(2026, 1, n, tzinfo=UTC), token=UUID(int=n),
            amount=Decimal(n) / 10
        )
        for n, (cohort, id_) in enumerate([(1, 1), (1, 2), (2, 1), (2, 2), (3, 1)], 1)
    )
    await session.commit()
    return Item


@fixture
def statements(engine: AsyncEngine) -> list[str]:
    statements: list[str] = []

    def capture(_conn: Any, _cursor: Any, statement: str, *_args: Any):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    return statements


async def page(
    session: AsyncSession, stmt: Any, limit: int = 2,
    cursor: str | None = None, mapper: Any = lambda row: row[0],
) -> Any:
    from fastsqla import new_cursor_pagination

    dependency = new_cursor_pagination(row_mapper=mapper)
    paginate = dependency(session=session, cursor=cursor, limit=limit)
    return await paginate(stmt)


@mark.parametrize(
    ("keys", "expected"),
    [
        param("cohort id", "11 12 21 22 31", id="ascending"),
        param("-cohort -id", "31 22 21 12 11", id="descending"),
        param("cohort -id", "12 11 22 21 31", id="mixed"),
        param("-cohort id", "31 21 22 11 12", id="reverse-mixed"),
        *(param(f"{key} cohort id", "11 12 21 22 31", id=key)
          for key in ("day", "timestamp", "token", "amount")),
    ]
)
async def test_traverses_ties_and_typed_keys_with_changing_limit(
    item: type[Any], session: AsyncSession, keys: str, expected: str
):
    ordering = [
        (desc if key.startswith("-") else asc)(getattr(item, key.lstrip("-")))
        for key in keys.split()
    ]
    stmt = select(item).order_by(*ordering)
    first = await page(session, stmt)
    second = await page(session, stmt, limit=1, cursor=first.meta.next_cursor)
    third = await page(session, stmt, cursor=second.meta.next_cursor)
    assert [row.name for row in first.data + second.data + third.data] == expected.split()
    assert first.meta.next_cursor is not None
    assert second.meta.next_cursor is not None
    assert third.meta.model_dump() == {"next_cursor": None}


@mark.parametrize(
    ("cohort", "expected"), [(99, []), (1, ["11", "12"])], ids=["empty", "full-page"]
)
async def test_terminal_pages(
    item: type[Any], session: AsyncSession, cohort: int, expected: list[str]
):
    result = await page(
        session, select(item).where(item.cohort == cohort).order_by(item.cohort, item.id)
    )
    assert [row.name for row in result.data] == expected
    assert result.meta.next_cursor is None


async def test_retains_filters_after_boundary_deletion_and_insertion_ahead(
    item: type[Any], session: AsyncSession
):
    stmt = select(item).where(item.cohort <= 2).order_by(item.cohort, item.id)
    first = await page(session, stmt)
    await session.delete(first.data[-1])
    session.add(
        item(
            cohort=0, id=0, name="00", day=date(2026, 1, 1),
            timestamp=datetime(2026, 1, 1, tzinfo=UTC), token=UUID(int=0), amount=Decimal(0)
        )
    )
    await session.commit()
    second = await page(session, stmt, cursor=first.meta.next_cursor)
    assert [row.name for row in second.data] == ["21", "22"]
    assert second.meta.next_cursor is None


async def test_projection_hides_cursor_columns_and_runs_one_query(
    item: type[Any], session: AsyncSession, statements: list[str]
):
    stmt = select(item.name.label("label")).order_by(item.cohort, item.id)
    result = await page(session, stmt, mapper=lambda row: dict(row._mapping))
    assert result.data == [{"label": "11"}, {"label": "12"}]
    assert result.meta.next_cursor is not None
    assert len(statements) == 1
    assert "count(" not in statements[0].lower()


@mark.parametrize(
    "cursor", ["", "not-a-cursor", "e30", "a" * 9000],
    ids=["empty", "malformed", "invalid-payload", "oversized"]
)
async def test_rejects_bad_cursors_before_sql(
    item: type[Any], session: AsyncSession, statements: list[str], cursor: str
):
    with raises(HTTPException) as error:
        await page(session, select(item).order_by(item.cohort, item.id), cursor=cursor)
    assert error.value.status_code == 422
    assert statements == []


@mark.parametrize(
    ("key", "dialect", "changes"),
    [
        *(("cohort", "sqlite", changes) for changes in [
            {"v": True}, {"v": 2}, {"order": []}, {"values": [True, 1]},
            {"values": ["1", 1]}, {"values": [2**100, 1]}, {"values": [1]}, {"extra": 1},
        ]),
        ("cohort", "postgresql", {"values": [2**100, 1]}),
        ("name", "postgresql", {"values": ["\0", 1]}),
        ("timestamp", "postgresql", {"values": ["2026-01-01T00:00:00Z", 1]}),
        ("amount", "postgresql", {"values": ["1e999999", 1]}),
        ("amount", "postgresql", {"values": ["1e-20000", 1]}),
    ]
)
async def test_rejects_invalid_payload(
    item: type[Any], session: AsyncSession, key: str, dialect: str, changes: dict
):
    from fastsqla import _cursor_order, _decode_cursor

    stmt = select(item).order_by(getattr(item, key), item.id)
    first = await page(session, stmt)
    token = first.meta.next_cursor
    payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    encoded = json.dumps(payload | changes).encode()
    token = base64.urlsafe_b64encode(encoded).decode().rstrip("=")
    with raises(HTTPException) as error:
        _decode_cursor(token, _cursor_order(stmt), dialect)
    assert error.value.status_code == 422


@mark.parametrize(
    "kind",
    ["unordered", "nullable", "expression", "limit", "offset", "distinct", "grouped",
     "fetch", "projection", "outer-join", "type"]
)
async def test_rejects_unsupported_queries_before_sql(
    item: type[Any], session: AsyncSession, statements: list[str], kind: str
):
    stmt = select(item).order_by(item.cohort, item.id)
    statements_by_kind = {
        "unordered": select(item),
        "nullable": select(item).order_by(item.optional),
        "expression": select(item).order_by(func.lower(item.name)),
        "limit": stmt.limit(1),
        "offset": stmt.offset(1),
        "distinct": stmt.distinct(),
        "grouped": stmt.group_by(item.cohort, item.id),
        "fetch": stmt.fetch(1),
        "projection": select(func.count()).order_by(item.cohort, item.id),
        "outer-join": stmt.outerjoin(item.__table__.alias(), item.id == 0),
        "type": select(item).order_by(item.flag),
    }
    with raises(ValueError):
        await page(session, statements_by_kind[kind])
    assert statements == []


def test_rejects_oversized_ordering_keys(item: type[Any]):
    from fastsqla import _cursor_order, _encode_cursor

    order = _cursor_order(select(item).order_by(item.name))
    with raises(ValueError, match="4096"):
        _encode_cursor(order, ("a" * 5000,))


async def test_http_continuation(app: FastAPI, client: AsyncClient, item: type[Any]):
    from fastsqla import CursorPage, CursorPaginate

    @app.get("/cursor")
    async def endpoint(paginate: CursorPaginate[str]) -> CursorPage[str]:
        return await paginate(select(item.name).order_by(item.cohort, item.id))

    first = await client.get("/cursor", params={"limit": 2})
    assert first.status_code == 200
    assert first.json()["data"] == ["11", "12"]
    second = await client.get(
        "/cursor", params={"limit": 3, "cursor": first.json()["meta"]["next_cursor"]}
    )
    assert second.json() == {"data": ["21", "22", "31"], "meta": {"next_cursor": None}}
    invalid = await client.get("/cursor", params={"cursor": "invalid"})
    assert invalid.status_code == 422


@mark.parametrize("default,maximum", [(0, 10), (11, 10), (1, 0), (True, 10)])
def test_invalid_factory_bounds(default: int, maximum: int):
    from fastsqla import new_cursor_pagination

    with raises(ValueError):
        new_cursor_pagination(default, maximum)
