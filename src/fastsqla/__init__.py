import base64
import functools
import json
import math
import os
import re
import warnings
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
from contextlib import _AsyncGeneratorContextManager, asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, TypedDict, TypeVar
from uuid import UUID

import sqlalchemy as sa
from fastapi import Depends as BaseDepends
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy import Result, Select, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_engine_from_config,
    async_sessionmaker,
)
from sqlalchemy.ext.declarative import DeferredReflection
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import Label, UnaryExpression
from sqlalchemy.sql.selectable import Join
from structlog import get_logger

logger = get_logger(__name__)

try:
    from sqlmodel.ext.asyncio.session import AsyncSession

except ImportError:
    pass


__all__ = [
    "Base",
    "Collection",
    "CursorMeta",
    "CursorPage",
    "CursorPaginate",
    "CursorPaginateType",
    "Item",
    "MissingConfigurationError",
    "Page",
    "Paginate",
    "PaginateType",
    "Session",
    "lifespan",
    "new_cursor_pagination",
    "new_pagination",
    "open_session",
]

SessionFactory = async_sessionmaker(expire_on_commit=False, class_=AsyncSession)

logger = get_logger(__name__)


def Depends(*args, **kwargs):
    "Allow backward compatibility with fastapi<0.121"
    try:
        return BaseDepends(*args, **kwargs)
    except TypeError:
        kwargs.pop("scope")
        return BaseDepends(*args, **kwargs)


class Base(DeclarativeBase, DeferredReflection):
    """Inherit from `Base` to declare an `SQLAlchemy` model.

    Example:
    ```py
    from fastsqla import Base
    from sqlalchemy.orm import Mapped, mapped_column


    class Hero(Base):
        __tablename__ = "hero"
        id: Mapped[int] = mapped_column(primary_key=True)
        name: Mapped[str] = mapped_column(unique=True)
        secret_identity: Mapped[str]
        age: Mapped[int]
    ```

    To learn more on `SQLAlchemy` ORM & Declarative mapping:

    * [ORM Quick Start](https://docs.sqlalchemy.org/en/20/orm/quickstart.html)
    * [Declarative Mapping](https://docs.sqlalchemy.org/en/20/orm/mapping_styles.html#declarative-mapping)

    !!! note

        You don't need this if you use [`SQLModel`](http://sqlmodel.tiangolo.com/).
    """

    __abstract__ = True


class State(TypedDict):
    fastsqla_engine: AsyncEngine


class MissingConfigurationError(RuntimeError):
    """Raised when a required SQLAlchemy setting is missing."""


def new_lifespan(
    url: str | None = None, **kw
) -> Callable[[FastAPI | None], _AsyncGeneratorContextManager[State, None]]:
    """Create a new lifespan async context manager.

    It expects the exact same parameters as
    [`sqlalchemy.ext.asyncio.create_async_engine`][sqlalchemy.ext.asyncio.create_async_engine]

    Example:

    ```python
    from fastapi import FastAPI
    from fastsqla import new_lifespan

    lifespan = new_lifespan(
        "sqlite+aiosqlite:///app/db.sqlite", connect_args={"autocommit": False}
    )

    app = FastAPI(lifespan=lifespan)
    ```

    Args:
        url (str): Database url.
        kw (dict): Configuration parameters as expected by [`sqlalchemy.ext.asyncio.create_async_engine`][sqlalchemy.ext.asyncio.create_async_engine]

    Raises:
        MissingConfigurationError: If a required SQLAlchemy setting is missing.
    """

    has_config = url is not None

    @asynccontextmanager
    async def lifespan(app: FastAPI | None) -> AsyncGenerator[State, None]:
        if has_config:
            prefix = ""
            sqla_config = {**kw, "url": url}

        else:
            prefix = "sqlalchemy_"
            sqla_config = {k.lower(): v for k, v in os.environ.items()}

        try:
            engine = async_engine_from_config(sqla_config, prefix=prefix)

        except KeyError as exc:
            raise MissingConfigurationError(
                f"Missing {prefix}{exc.args[0]} in environ."
            ) from exc

        async with engine.begin() as conn:
            await conn.run_sync(Base.prepare)

        SessionFactory.configure(bind=engine)

        await logger.ainfo("Configured SQLAlchemy.")

        yield {"fastsqla_engine": engine}

        SessionFactory.configure(bind=None)
        await engine.dispose()

        await logger.ainfo("Cleared SQLAlchemy config.")

    return lifespan


lifespan = new_lifespan()
"""Use `fastsqla.lifespan` to set up SQLAlchemy directly from environment variables.

In an ASGI application, [lifespan events](https://asgi.readthedocs.io/en/latest/specs/lifespan.html)
are used to communicate startup & shutdown events.

The [`lifespan`](https://fastapi.tiangolo.com/advanced/events/#lifespan) parameter of
the `FastAPI` app can be assigned to a context manager, which is opened when the app
starts and closed when the app stops.

In order for `FastSQLA` to setup `SQLAlchemy` before the app is started, set
`lifespan` parameter to `fastsqla.lifespan`:

```python
from fastapi import FastAPI
from fastsqla import lifespan


app = FastAPI(lifespan=lifespan)
```

If multiple lifespan contexts are required, create an async context manager function
to handle them and set it as the app's lifespan:

```python
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastsqla import lifespan as fastsqla_lifespan
from this_other_library import another_lifespan


@asynccontextmanager
async def lifespan(app:FastAPI) -> AsyncGenerator[dict, None]:
    async with AsyncExitStack() as stack:
        yield {
            **stack.enter_async_context(lifespan(app)),
            **stack.enter_async_context(another_lifespan(app)),
        }


app = FastAPI(lifespan=lifespan)
```

To learn more about lifespan protocol:

* [Lifespan Protocol](https://asgi.readthedocs.io/en/latest/specs/lifespan.html)
* [Use Lifespan State instead of `app.state`](https://github.com/Kludex/fastapi-tips?tab=readme-ov-file#6-use-lifespan-state-instead-of-appstate)
* [FastAPI lifespan documentation](https://fastapi.tiangolo.com/advanced/events/)
"""


@asynccontextmanager
async def open_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager that opens a new `SQLAlchemy` or `SQLModel` async session.

    To the contrary of the [`Session`][fastsqla.Session] dependency which can only be
    used in endpoints, `open_session` can be used anywhere such as in background tasks.

    On exit, it automatically commits the session if no errors occur inside the context,
    or rolls back when an exception is raised.
    In all cases, it closes the session and returns the associated connection to the
    connection pool.


    Returns:
        When `SQLModel` is not installed, an async generator that yields an
            [`SQLAlchemy AsyncSession`][sqlalchemy.ext.asyncio.AsyncSession].

        When `SQLModel` is installed, an async generator that yields an
            [`SQLModel AsyncSession`](https://github.com/fastapi/sqlmodel/blob/main/sqlmodel/ext/asyncio/session.py#L32)
            which inherits from [`SQLAlchemy AsyncSession`][sqlalchemy.ext.asyncio.AsyncSession].


    ```python
    from fastsqla import open_session

    async def example():
        async with open_session() as session:
            await session.execute(...)
    ```

    """
    session = SessionFactory()
    try:
        yield session

    except Exception:
        await logger.awarning("context failed: rolling back session.")
        await session.rollback()
        raise

    else:
        await logger.adebug("context succeeded: committing session.")
        try:
            await session.commit()

        except Exception:
            await logger.aexception("commit failed: rolling back session")
            await session.rollback()
            raise

    finally:
        await logger.adebug("closing session.")
        await session.close()


async def new_session() -> AsyncGenerator[AsyncSession, None]:
    async with open_session() as session:
        yield session


Session = Annotated[AsyncSession, Depends(new_session, scope="function")]
"""Dependency used exclusively in endpoints to get an `SQLAlchemy` or `SQLModel` session.

`Session` is a [`FastAPI` dependency](https://fastapi.tiangolo.com/tutorial/dependencies/)
that provides an asynchronous `SQLAlchemy` session or `SQLModel` one if it's installed.
By defining an argument with type `Session` in an endpoint, `FastAPI` will automatically
inject an async session into the endpoint.

At the end of request handling:

* If no exceptions are raised, the session is automatically committed.
* If an exception is raised, the session is automatically rolled back.
* In all cases, the session is closed and the associated connection is returned to the
  connection pool.

Example:

``` py title="example.py" hl_lines="6"
from fastsqla import Item, Session
...

@app.get("/heros/{hero_id}", response_model=Item[HeroItem])
async def get_items(
    session: Session, # (1)!
    item_id: int,
):
    hero = await session.get(Hero, hero_id)
    return {"data": hero}
```

1.  Just define an argument with type `Session` to get an async session injected
    in your endpoint.

---

**Recommendation**: Unless there is a good reason to do so, avoid committing the session
manually, as `FastSQLA` handles it automatically.

If you need data generated by the database server, such as auto-incremented IDs, flush
the session instead:

```python
from fastsqla import Item, Session
...


@app.post("/heros", response_model=Item[HeroItem])
async def create_item(session: Session, new_hero: HeroBase):
    hero = Hero(**new_hero.model_dump())
    session.add(hero)
    await session.flush()
    return {"data": hero}
```

Or use the [session context manager][fastsqla.open_session] instead.
"""


class Meta(BaseModel):
    offset: int = Field(description="Current page offset.")
    total_items: int = Field(description="Total number of items.")
    total_pages: int = Field(description="Total number of pages.")
    page_number: int = Field(description="Current page number. Starts at 1.")


T = TypeVar("T")


class Item[T](BaseModel):
    data: T


class Collection[T](BaseModel):
    data: list[T]


class Page(Collection[T]):
    """Generic container that contains collection data and page metadata.

    The `Page` model is used to return paginated data in paginated endpoints:

    ```json
    {
        "data": list[T],
        "meta": {
            "offset": int,
            "total_items": int,
            "total_pages": int,
            "page_number": int,
        }
    }
    ```
    """

    meta: Meta


async def _query_count(session: Session, stmt: Select) -> int:
    result = await session.execute(select(func.count()).select_from(stmt.subquery()))
    return result.scalar()  # type: ignore


async def _paginate(
    session: Session,
    stmt: Select,
    total_items: int,
    offset: int,
    limit: int,
    result_processor: Callable[[Result], Iterable],
):
    total_pages = math.ceil(total_items / limit)
    page_number = math.floor(offset / limit + 1)
    result = await session.execute(stmt.offset(offset).limit(limit))
    data = result_processor(result)
    return Page(
        data=data,  # type:ignore
        meta=Meta(
            offset=offset,
            total_items=total_items,
            total_pages=total_pages,
            page_number=page_number,
        ),
    )


def _accept_deprecated_page_size_option[**P, R](
    function: Callable[P, R],
) -> Callable[P, R]:
    @functools.wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        if "min_page_size" in kwargs:
            if args or "default_page_size" in kwargs:
                raise TypeError(
                    "new_pagination() cannot receive both default_page_size and "
                    "min_page_size"
                )
            warnings.warn(
                "min_page_size is deprecated; use default_page_size instead",
                DeprecationWarning,
                stacklevel=2,
            )
        return function(*args, **kwargs)

    return wrapper


@_accept_deprecated_page_size_option
def new_pagination(
    default_page_size: int = 10,
    max_page_size: int = 100,
    query_count_dependency: Callable[..., Awaitable[int]] | None = None,
    result_processor: Callable[[Result], Iterable] = lambda result: iter(
        result.unique().scalars()
    ),
    *,
    min_page_size: int | None = None,
):
    """Create a FastAPI pagination dependency.

    Args:
        default_page_size: Default value of the `limit` query parameter.
        max_page_size: Maximum accepted value of the `limit` query parameter.
        query_count_dependency: Optional dependency that returns the total item count.
        result_processor: Function that transforms the SQLAlchemy result into page data.
        min_page_size: Deprecated alias for `default_page_size`.

    Raises:
        TypeError: Both page-size parameter names are supplied.
        ValueError: The page-size configuration is invalid.
    """
    if min_page_size is not None:
        default_page_size = min_page_size
    if max_page_size < 1:
        raise ValueError("max_page_size must be at least 1")
    if not 1 <= default_page_size <= max_page_size:
        raise ValueError("default_page_size must be between 1 and max_page_size")

    def default_dependency(
        session: Session,
        offset: int = Query(0, ge=0),
        limit: int = Query(default_page_size, ge=1, le=max_page_size),
    ) -> PaginateType[T]:
        async def paginate(stmt: Select) -> Page:
            total_items = await _query_count(session, stmt)
            return await _paginate(
                session, stmt, total_items, offset, limit, result_processor
            )

        return paginate

    def dependency(
        session: Session,
        offset: int = Query(0, ge=0),
        limit: int = Query(default_page_size, ge=1, le=max_page_size),
        total_items: int = Depends(query_count_dependency),
    ) -> PaginateType[T]:
        async def paginate(stmt: Select) -> Page:
            return await _paginate(
                session, stmt, total_items, offset, limit, result_processor
            )

        return paginate

    if query_count_dependency:
        return dependency
    else:
        return default_dependency


type PaginateType[T] = Callable[[Select], Awaitable[Page[T]]]

Paginate = Annotated[PaginateType[T], Depends(new_pagination())]
"""A dependency used in endpoints to paginate `SQLAlchemy` select queries.

It adds **`offset`** and **`limit`** query parameters to the endpoint, which are used to
paginate. The model returned by the endpoint is a [`Page`][fastsqla.Page] model.
"""


class CursorMeta(BaseModel):
    next_cursor: str | None = Field(description="Next cursor, or null at the end.")


class CursorPage[T](Collection[T]):
    """Forward page with a continuation cursor or null at the end."""

    meta: CursorMeta


type CursorPaginateType[T] = Callable[[Select], Awaitable[CursorPage[T]]]
type _CursorOrder = list[tuple[sa.Column, bool]]
type _CursorValue = int | str | UUID | datetime | date | Decimal


def _cursor_order(stmt: Select) -> _CursorOrder:
    # SQLAlchemy statement introspection is isolated here for compatibility testing.
    if not isinstance(stmt, Select) or any(
        getattr(stmt, name) is not None
        for name in ("_limit_clause", "_offset_clause", "_fetch_clause")
    ):
        raise ValueError("Cursor pagination requires an unlimited Select")
    if stmt._distinct or stmt._group_by_clauses or stmt._having_criteria:
        raise ValueError("Cursor pagination does not support DISTINCT or aggregation")
    if any(
        not isinstance(col.element if isinstance(col, Label) else col, sa.Column)
        for col in stmt.selected_columns
    ):
        raise ValueError("Cursor pagination requires entity or column selections")
    sources = stmt.get_final_froms()
    if any(
        isinstance(node, Join) and (node.isouter or node.full)
        for source in sources
        for node in visitors.iterate(source)
    ):
        raise ValueError("Cursor pagination does not support outer joins")
    order = []
    for expression in stmt._order_by_clauses:
        descending = False
        if isinstance(expression, UnaryExpression) and expression.modifier in (
            operators.asc_op, operators.desc_op
        ):
            descending = expression.modifier is operators.desc_op
            expression = expression.element
        if (
            not isinstance(expression, sa.Column)
            or not isinstance(expression.table, sa.Table)
            or expression.nullable
            or not any(source.is_derived_from(expression.table) for source in sources)
        ):
            raise ValueError("Cursor ordering requires non-null columns from the query")
        if not isinstance(
            expression.type,
            (sa.Integer, sa.String, sa.Uuid, sa.DateTime, sa.Date, sa.Numeric),
        ) or expression.type.python_type not in (int, str, UUID, datetime, date, Decimal):
            raise ValueError("Unsupported cursor column type")
        order.append((expression, descending))
    if not order:
        raise ValueError("Cursor pagination requires an explicit unique ordering")
    return order


def _cursor_schema(order: _CursorOrder) -> list[str]:
    return [
        json.dumps([col.table.fullname, col.name, desc, col.type.python_type.__name__])
        for col, desc in order
    ]


def _encode_cursor(order: _CursorOrder, values: tuple[_CursorValue, ...]) -> str:
    key_types = tuple(column.type.python_type for column, _ in order)
    adapter = TypeAdapter(tuple[key_types])
    encoded = adapter.dump_python(adapter.validate_python(values, strict=True), mode="json")
    payload = {"v": 1, "order": _cursor_schema(order), "values": encoded}
    cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    if len(cursor) > 4096:
        raise ValueError("Cursor exceeds 4096 characters; use shorter ordering keys")
    return cursor


def _decode_cursor(cursor: str, order: _CursorOrder, dialect: str) -> list[_CursorValue]:
    try:
        if len(cursor) > 4096 or not re.fullmatch(r"[A-Za-z0-9_-]+", cursor):
            raise ValueError("Invalid encoding")
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"v", "order", "values"}
            or type(payload["v"]) is not int
            or payload["v"] != 1
            or payload["order"] != _cursor_schema(order)
            or not isinstance(payload["values"], list)
            or len(payload["values"]) != len(order)
        ):
            raise ValueError("Invalid payload")
        values = []
        for (column, _), value in zip(order, payload["values"], strict=True):
            value_type = column.type.python_type
            if type(value) is not (int if value_type is int else str):
                raise ValueError("Invalid key type")
            if value_type is int:
                bits = 16 if isinstance(column.type, sa.SmallInteger) else 32
                if dialect == "sqlite" or isinstance(column.type, sa.BigInteger):
                    bits = 64
                if not -(2 ** (bits - 1)) <= value < 2 ** (bits - 1):
                    raise ValueError("Integer key out of range")
            parsed = TypeAdapter(value_type).validate_json(json.dumps(value), strict=True)
            if value_type is Decimal and (
                parsed.as_tuple().exponent < -16383
                or parsed.adjusted()
                >= (column.type.precision or 131072) - (column.type.scale or 0)
            ):
                raise ValueError("Decimal key out of range")
            if dialect == "postgresql" and (
                (value_type is str and "\0" in parsed)
                or (
                    value_type is datetime
                    and (parsed.utcoffset() is not None) != column.type.timezone
                )
            ):
                raise ValueError("Key cannot be represented by the database column")
            values.append(parsed)
        return values
    except (ValueError, TypeError, RecursionError) as error:
        raise HTTPException(status_code=422, detail="Invalid cursor") from error


def new_cursor_pagination[T](
    default_page_size: int = 10,
    max_page_size: int = 100,
    *,
    row_mapper: Callable[[sa.Row], T] = lambda row: row[0],
) -> Callable[..., CursorPaginateType[T]]:
    """Create a forward cursor dependency with a one-row-to-one-item mapper.

    Args:
        default_page_size: Default limit when the client omits it.
        max_page_size: Maximum accepted limit.
        row_mapper: Maps each original result row to exactly one response item.

    Raises:
        ValueError: Page-size bounds or the supplied Select are unsupported.
    """
    if (
        type(default_page_size) is not int
        or type(max_page_size) is not int
        or not 1 <= default_page_size <= max_page_size
    ):
        raise ValueError("Require 1 <= default_page_size <= max_page_size")

    def dependency(
        session: Session,
        cursor: str | None = Query(None, min_length=1, max_length=4096),
        limit: int = Query(default_page_size, ge=1, le=max_page_size),
    ) -> CursorPaginateType[T]:
        async def paginate(stmt: Select) -> CursorPage[T]:
            order = _cursor_order(stmt)
            columns = [column for column, _ in order]
            if cursor is not None:
                dialect = session.get_bind(clause=stmt).dialect.name
                values = tuple(_decode_cursor(cursor, order, dialect))
                same_direction = len({desc for _, desc in order}) == 1
                if same_direction and dialect in ("postgresql", "sqlite", "mysql"):
                    keys = sa.tuple_(*columns)
                    condition = keys < values if order[0][1] else keys > values
                else:
                    terms, prefix = [], []
                    for (column, desc), value in zip(order, values, strict=True):
                        comparison = column < value if desc else column > value
                        terms.append(sa.and_(*prefix, comparison))
                        prefix.append(column == value)
                    bound = columns[0] <= values[0] if order[0][1] else columns[0] >= values[0]
                    condition = sa.and_(bound, sa.or_(*terms))
                stmt = stmt.where(condition)
            stmt = stmt.add_columns(*(col.label(None) for col in columns)).limit(limit + 1)
            result = await session.execute(stmt)
            width = len(result.keys()) - len(columns)
            frozen = result.freeze()
            rows = frozen().all()
            next_cursor = (
                _encode_cursor(order, rows[limit - 1][-len(columns) :])
                if len(rows) > limit
                else None
            )
            original = frozen().columns(*range(width)).all()
            data = [row_mapper(row) for row in original[:limit]]
            return CursorPage(data=data, meta=CursorMeta(next_cursor=next_cursor))

        return paginate

    return dependency


CursorPaginate = Annotated[CursorPaginateType[T], Depends(new_cursor_pagination())]
"""Inject a forward paginator accepting cursor and limit query parameters."""
