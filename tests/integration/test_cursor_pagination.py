import base64
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, get_args
from uuid import UUID

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from httpx import AsyncClient
from pydantic import BaseModel, ConfigDict, ValidationError
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
    from fastsqla import cursor as pagination

    dependency = get_args(pagination.new_pagination(row_mapper=mapper))[1].dependency
    parameters = {
        "cursor": {"name": "next_cursor", "value": cursor},
        "limit": {"name": "limit", "value": limit},
    }
    paginate = await dependency(session=session, parameters=parameters)
    return await paginate(stmt)


@mark.parametrize(
    ("keys", "expected"),
    [
        param("cohort id", "11 12 21 22 31", id="ascending"),
        param("-cohort -id", "31 22 21 12 11", id="descending"),
        param("cohort -id", "12 11 22 21 31", id="mixed"),
        param("-cohort id", "31 21 22 11 12", id="reverse-mixed"),
        *(param(f"{key} cohort id", "11 12 21 22 31", id=key)
          for key in ("day", "timestamp", "token")),
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
    "cursor", ["not-a-cursor", "e30", "a!b", "a", "é"],
    ids=[
        "malformed", "invalid-payload", "invalid-alphabet", "invalid-padding", "non-ascii"
    ]
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
        ("amount", "postgresql", {"values": ["NaN", 1]}),
        ("day", "sqlite", {"values": ["invalid-date", 1]}),
        ("token", "sqlite", {"values": ["invalid-uuid", 1]}),
    ]
)
async def test_rejects_invalid_payload(
    item: type[Any], session: AsyncSession, key: str, dialect: str, changes: dict
):
    from fastsqla import cursor as pagination

    stmt = select(item).order_by(getattr(item, key), item.id)
    row = (await session.scalars(stmt)).first()
    token = pagination._encode(pagination._order(stmt), (getattr(row, key), row.id))
    payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    encoded = json.dumps(payload | changes).encode()
    token = base64.urlsafe_b64encode(encoded).decode().rstrip("=")
    with raises(HTTPException) as error:
        pagination._decode(token, pagination._order(stmt), dialect)
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


@mark.parametrize(
    ("padding_size", "minimum_cursor_length"), [(0, 1), (5000, 4097)], ids=["short", "long"]
)
async def test_http_continuation(
    app: FastAPI, client: AsyncClient, item: type[Any], session: AsyncSession,
    padding_size: int, minimum_cursor_length: int,
):
    from fastsqla import cursor as pagination

    rows = (await session.scalars(select(item).order_by(item.cohort, item.id))).all()
    expected = [row.name + "x" * padding_size for row in rows]
    for row, name in zip(rows, expected, strict=True):
        row.name = name
    await session.commit()

    @app.get("/cursor")
    async def endpoint(paginate: pagination.Paginate[str]) -> pagination.Page[str]:
        return await paginate(select(item.name).order_by(item.name, item.cohort, item.id))

    first = await client.get("/cursor", params={"limit": 2})
    assert first.status_code == 200
    assert first.json()["data"] == expected[:2]
    cursor = first.json()["meta"]["next_cursor"]
    assert len(cursor) >= minimum_cursor_length
    second = await client.get("/cursor", params={"limit": 3, "next_cursor": cursor})
    assert second.status_code == 200
    assert second.json() == {"data": expected[2:], "meta": {"next_cursor": None}}
    invalid = await client.get("/cursor", params={"next_cursor": "invalid"})
    assert invalid.status_code == 422


@mark.parametrize("default,maximum", [(0, 10), (11, 10), (1, 0), (True, 10)])
def test_invalid_factory_bounds(default: int, maximum: int):
    from fastsqla import cursor as pagination

    with raises(ValueError):
        pagination.new_pagination(default, maximum)


async def test_rejects_sqlite_decimal_ordering_before_sql(
    item: type[Any], session: AsyncSession, statements: list[str]
):
    record = await session.get(item, (1, 1))
    record.amount = Decimal("0.101")
    await session.commit()
    statements.clear()
    with raises(ValueError, match="SQLite decimal ordering"):
        await page(session, select(item).order_by(item.amount, item.cohort, item.id))
    assert statements == []


@mark.parametrize(
    "kind,bits",
    [
        ("TINYINT", 8),
        ("SMALLINT", 16),
        ("MEDIUMINT", 24),
        ("INTEGER", 32),
        ("BIGINT", 64),
    ],
)
@mark.parametrize("unsigned", [False, True], ids=["signed", "unsigned"])
@mark.parametrize("boundary", [0, 1], ids=["lower", "upper"])
def test_mysql_integer_cursor_round_trip(kind: str, bits: int, unsigned: bool, boundary: int):
    from sqlalchemy import Column, MetaData, Table
    from sqlalchemy.dialects import mysql

    from fastsqla import cursor as pagination

    table = Table(
        "integer_key",
        MetaData(),
        Column("id", getattr(mysql, kind)(unsigned=unsigned), primary_key=True)
    )
    bounds = (0, 2**bits - 1) if unsigned else (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1)
    value = bounds[boundary]
    order = pagination._order(select(table).order_by(table.c.id))
    token = pagination._encode(order, (value,))
    assert pagination._decode(token, order, "mysql") == [value]


@mark.parametrize("value", [-1, 2**32])
def test_rejects_values_outside_mysql_unsigned_range(value: int):
    from sqlalchemy import Column, MetaData, Table
    from sqlalchemy.dialects import mysql

    from fastsqla import cursor as pagination

    table = Table(
        "unsigned_key",
        MetaData(),
        Column("id", mysql.INTEGER(unsigned=True), primary_key=True)
    )
    order = pagination._order(select(table).order_by(table.c.id))
    token = pagination._encode(order, (value,))
    with raises(HTTPException) as error:
        pagination._decode(token, order, "mysql")
    assert error.value.status_code == 422


@mark.parametrize(
    "value", [Decimal("0.00"), Decimal("-99999999.99"), Decimal("99999999.99")]
)
def test_postgresql_decimal_cursor_round_trip(value: Decimal):
    from sqlalchemy import Column, MetaData, Table

    from fastsqla import cursor as pagination

    table = Table("decimal_key", MetaData(), Column("id", Numeric(10, 2), primary_key=True))
    order = pagination._order(select(table).order_by(table.c.id))
    token = pagination._encode(order, (value,))
    assert pagination._decode(token, order, "postgresql") == [value]


@mark.parametrize("aware", [False, True], ids=["naive", "aware"])
def test_postgresql_timestamp_cursor_round_trip(aware: bool):
    from sqlalchemy import Column, DateTime, MetaData, Table

    from fastsqla import cursor as pagination

    table = Table("timestamp_key", MetaData(),
                  Column("id", DateTime(timezone=aware), primary_key=True))
    value = datetime(2026, 1, 1, tzinfo=UTC if aware else None)
    order = pagination._order(select(table).order_by(table.c.id))
    token = pagination._encode(order, (value,))
    assert pagination._decode(token, order, "postgresql") == [value]


@mark.parametrize("encoding", ["standard", "urlsafe"])
@mark.parametrize("padding", ["", "="], ids=["unpadded", "padded"])
def test_accepts_equivalent_base64_encodings(encoding: str, padding: str):
    from sqlalchemy import Column, MetaData, String, Table

    from fastsqla import cursor as pagination

    table = Table("text_key", MetaData(), Column("id", String, primary_key=True))
    order = pagination._order(select(table).order_by(table.c.id))
    value = "\uffff" * 3
    token = pagination._encode(order, (value,))
    payload = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    encoder = {"standard": base64.b64encode, "urlsafe": base64.urlsafe_b64encode}[encoding]
    encoded = encoder(payload).decode().rstrip("=")
    cursor = encoded + padding * (-len(encoded) % 4)
    assert pagination._decode(cursor, order, "sqlite") == [value]


async def test_offset_and_cursor_dependencies_work_in_same_app(
    app: FastAPI, client: AsyncClient, item: type[Any]
):
    import fastsqla
    from fastsqla import cursor

    @app.get("/offset")
    async def offset_endpoint(paginate: fastsqla.Paginate[str]) -> fastsqla.Page[str]:
        return await paginate(select(item.name).order_by(item.cohort, item.id))

    @app.get("/cursor")
    async def cursor_endpoint(paginate: cursor.Paginate[str]) -> cursor.Page[str]:
        return await paginate(select(item.name).order_by(item.cohort, item.id))

    offset_page = await client.get("/offset", params={"offset": 1, "limit": 2})
    assert offset_page.status_code == 200
    assert offset_page.json()["data"] == ["12", "21"]
    assert offset_page.json()["meta"]["offset"] == 1
    first = await client.get("/cursor", params={"limit": 2})
    assert first.status_code == 200
    assert first.json()["data"] == ["11", "12"]
    second = await client.get(
        "/cursor", params={"limit": 3, "next_cursor": first.json()["meta"]["next_cursor"]}
    )
    assert second.status_code == 200
    assert second.json() == {"data": ["21", "22", "31"], "meta": {"next_cursor": None}}
    paths = app.openapi()["paths"]
    assert {p["name"] for p in paths["/offset"]["get"]["parameters"]} == {"offset", "limit"}
    assert {p["name"] for p in paths["/cursor"]["get"]["parameters"]} == {"next_cursor", "limit"}


@mark.parametrize("custom", [False, True], ids=["default-query", "custom-query"])
async def test_post_filters_with_query_pagination(
    app: FastAPI, client: AsyncClient, item: type[Any], custom: bool
):
    from fastsqla import cursor

    async def get_parameters(
        cursor: str | None = Query(None, alias="next_cursor"), limit: int | None = Query(None)
    ) -> dict:
        return {
            "cursor": {"name": "next_cursor", "value": cursor},
            "limit": {"name": "limit", "value": limit},
        }

    Paginate = cursor.new_pagination(
        default_page_size=1, max_page_size=2,
        parameters_dependency=get_parameters if custom else None
    )

    class Search(BaseModel):
        model_config = ConfigDict(extra="forbid")
        min_cohort: int

    @app.post("/search")
    async def endpoint(body: Search, paginate: Paginate[str]) -> cursor.Page[str]:
        stmt = select(item.name).where(item.cohort >= body.min_cohort)
        return await paginate(stmt.order_by(item.cohort, item.id))

    first = await client.post("/search", json={"min_cohort": 2})
    assert first.status_code == 200
    assert first.json()["data"] == ["21"]
    second = await client.post(
        "/search", json={"min_cohort": 2},
        params={"limit": 2, "next_cursor": first.json()["meta"]["next_cursor"]}
    )
    assert second.status_code == 200
    assert second.json() == {"data": ["22", "31"], "meta": {"next_cursor": None}}
    schema = app.openapi()
    operation = schema["paths"]["/search"]["post"]
    assert {p["name"] for p in operation["parameters"]} == {"next_cursor", "limit"}
    body_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert body_schema == {"$ref": "#/components/schemas/Search"}
    assert set(schema["components"]["schemas"]["Search"]["properties"]) == {"min_cohort"}


@mark.parametrize(
    "parameters,location",
    [
        param({"limit": 0}, "limit", id="below-minimum"),
        param({"limit": 3}, "limit", id="above-custom-maximum"),
        param({"limit": "oops"}, "limit", id="non-numeric-limit"),
        param({"next_cursor": ""}, "next_cursor", id="empty-cursor"),
    ]
)
async def test_rejects_invalid_query_parameters_before_sql(
    app: FastAPI, client: AsyncClient, item: type[Any], statements: list[str],
    parameters: dict, location: str,
):
    from fastsqla import cursor

    Paginate = cursor.new_pagination(default_page_size=1, max_page_size=2)

    @app.get("/cursor")
    async def endpoint(paginate: Paginate[str]) -> cursor.Page[str]:
        return await paginate(select(item.name).order_by(item.cohort, item.id))

    response = await client.get("/cursor", params=parameters)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", location]
    assert statements == []


@mark.parametrize(
    "parameters,location",
    [
        param((None, 0), "limit", id="below-minimum"),
        param((None, 3), "limit", id="above-custom-maximum"),
        param((None, True), "limit", id="boolean-limit"),
        param((None, 1.5), "limit", id="fractional-limit"),
        param(("", None), "next_cursor", id="empty-cursor"),
        param((1, None), "next_cursor", id="numeric-cursor"),
    ]
)
async def test_validates_custom_dependency_values_before_sql(
    app: FastAPI, client: AsyncClient, item: type[Any], statements: list[str],
    parameters: tuple, location: str,
):
    from fastsqla import cursor

    async def get_parameters() -> dict:
        return {
            "cursor": {"name": "next_cursor", "value": parameters[0]},
            "limit": {"name": "limit", "value": parameters[1]},
        }

    Paginate = cursor.new_pagination(
        default_page_size=1, max_page_size=2, parameters_dependency=get_parameters
    )

    @app.get("/cursor")
    async def endpoint(paginate: Paginate[str]) -> cursor.Page[str]:
        return await paginate(select(item.name).order_by(item.cohort, item.id))

    response = await client.get("/cursor")
    assert response.status_code == 422
    slot = "cursor" if location == "next_cursor" else location
    assert response.json()["detail"][0]["loc"] == [slot, "value"]
    assert statements == []


async def test_default_query_schema_and_omitted_parameters(
    app: FastAPI, client: AsyncClient, item: type[Any]
):
    from fastsqla import cursor

    @app.get("/cursor")
    async def endpoint(paginate: cursor.Paginate[str]) -> cursor.Page[str]:
        return await paginate(select(item.name).order_by(item.cohort, item.id))

    response = await client.get("/cursor")
    assert response.status_code == 200
    assert response.json() == {
        "data": ["11", "12", "21", "22", "31"], "meta": {"next_cursor": None}
    }
    operation = app.openapi()["paths"]["/cursor"]["get"]
    assert "requestBody" not in operation
    limit = next(p for p in operation["parameters"] if p["name"] == "limit")
    assert limit["schema"]["default"] == 10
    assert limit["schema"]["minimum"] == 1
    assert limit["schema"]["maximum"] == 100


async def test_sync_extractor_with_body_subdependency(
    app: FastAPI, client: AsyncClient, item: type[Any]
):
    from fastsqla import cursor

    async def get_body(body: Annotated[dict, Body()]) -> dict:
        return body

    def get_parameters(body: Annotated[dict, Depends(get_body)]) -> dict:
        return {
            "cursor": {"name": "after", "value": body.get("after")},
            "limit": {"name": "size", "value": body.get("size")},
        }

    Paginate = cursor.new_pagination(
        default_page_size=1, max_page_size=2, parameters_dependency=get_parameters
    )

    @app.post("/search")
    async def endpoint(
        paginate: Paginate[str], body: Annotated[dict, Depends(get_body)]
    ) -> cursor.Page[str]:
        stmt = select(item.name).where(item.cohort >= body["min_cohort"])
        return await paginate(stmt.order_by(item.cohort, item.id))

    first = await client.post("/search", json={"min_cohort": 2, "size": None})
    assert first.status_code == 200
    assert first.json()["data"] == ["21"]
    assert set(first.json()["meta"]) == {"after"}
    second = await client.post("/search", json={
        "min_cohort": 2, "size": 2, "after": first.json()["meta"]["after"]
    })
    assert second.status_code == 200
    assert second.json() == {"data": ["22", "31"], "meta": {"after": None}}


@mark.parametrize("cursor_name", ["after", "next-page", "cursor"])
@mark.parametrize("return_dict", [False, True], ids=["model", "dict"])
async def test_custom_name_survives_response_validation_and_round_trip(
    app: FastAPI, client: AsyncClient, item: type[Any], cursor_name: str, return_dict: bool
):
    from fastsqla import cursor

    async def get_parameters(
        cursor_value: str | None = Query(None, alias=cursor_name),
        limit: int | None = Query(None),
    ) -> dict:
        return {
            "cursor": {"name": cursor_name, "value": cursor_value},
            "limit": {"name": "limit", "value": limit},
        }

    Paginate = cursor.new_pagination(
        default_page_size=2, parameters_dependency=get_parameters
    )

    @app.get("/named")
    async def endpoint(paginate: Paginate[str]) -> cursor.Page[str]:
        result = await paginate(select(item.name).order_by(item.cohort, item.id))
        return result.model_dump() if return_dict else result

    @app.get("/default")
    async def default_endpoint(paginate: cursor.Paginate[str]) -> cursor.Page[str]:
        return await paginate(select(item.name).order_by(item.cohort, item.id))

    first = await client.get("/named")
    assert first.status_code == 200
    assert first.json()["data"] == ["11", "12"]
    assert set(first.json()["meta"]) == {cursor_name}
    parsed = cursor.Page[str].model_validate_json(first.content)
    assert parsed.model_dump() == first.json()
    assert parsed.meta.next_cursor == first.json()["meta"][cursor_name]
    second = await client.get(
        "/named", params={cursor_name: parsed.meta.next_cursor, "limit": 3}
    )
    assert second.status_code == 200
    assert second.json() == {"data": ["21", "22", "31"], "meta": {cursor_name: None}}
    default = await client.get("/default")
    assert default.status_code == 200
    assert default.json()["meta"] == {"next_cursor": None}
    schema = app.openapi()
    assert {p["name"] for p in schema["paths"]["/named"]["get"]["parameters"]} == {
        cursor_name, "limit"
    }
    assert {p["name"] for p in schema["paths"]["/default"]["get"]["parameters"]} == {
        "next_cursor", "limit"
    }
    meta_schema = schema["components"]["schemas"]["Meta"]
    assert meta_schema["type"] == "object"
    assert meta_schema["minProperties"] == meta_schema["maxProperties"] == 1
    assert meta_schema["additionalProperties"] == {
        "anyOf": [{"type": "string"}, {"type": "null"}]
    }


async def test_custom_extractor_owns_input_name_and_factory_names_metadata(
    app: FastAPI, client: AsyncClient, item: type[Any]
):
    from fastsqla import cursor

    async def get_parameters(after: str | None = Query(None)) -> dict:
        return {
            "cursor": {"name": "after", "value": after},
            "limit": {"name": "size", "value": 3},
        }

    Paginate = cursor.new_pagination(parameters_dependency=get_parameters)

    @app.post("/search")
    async def endpoint(paginate: Paginate[str]) -> cursor.Page[str]:
        return await paginate(select(item.name).order_by(item.cohort, item.id))

    first = await client.post("/search")
    assert first.status_code == 200
    assert first.json()["data"] == ["11", "12", "21"]
    assert set(first.json()["meta"]) == {"after"}
    second = await client.post("/search", params={"after": first.json()["meta"]["after"]})
    assert second.status_code == 200
    assert second.json() == {"data": ["22", "31"], "meta": {"after": None}}
    parameters = app.openapi()["paths"]["/search"]["post"]["parameters"]
    assert [p["name"] for p in parameters] == ["after"]


@mark.parametrize(
    "parameters",
    [
        (None, 2),
        {"cursor": {"name": "", "value": None}, "limit": {"name": "size", "value": 2}},
        {"cursor": {"name": "after", "value": None}, "limit": {"name": "after", "value": 2}},
        {"cursor": {"name": " after ", "value": None}, "limit": {"name": "size", "value": 2}},
    ],
    ids=["tuple", "empty-name", "duplicate-name", "surrounding-whitespace"],
)
async def test_rejects_invalid_custom_parameter_shape_before_sql(
    app: FastAPI, client: AsyncClient, item: type[Any], statements: list[str],
    parameters: Any,
):
    from fastsqla import cursor

    async def get_parameters() -> dict:
        return parameters

    Paginate = cursor.new_pagination(parameters_dependency=get_parameters)

    @app.get("/cursor")
    async def endpoint(paginate: Paginate[str]) -> cursor.Page[str]:
        return await paginate(select(item.name).order_by(item.cohort, item.id))

    response = await client.get("/cursor")
    assert response.status_code == 422
    assert statements == []


@mark.parametrize("meta", [{}, {"after": "a", "next_cursor": "b"}, {"after": 1}])
def test_metadata_requires_exactly_one_string_or_null_cursor(meta: dict):
    from fastsqla import cursor

    with raises(ValidationError):
        cursor.Page[str](data=[], meta=meta)
