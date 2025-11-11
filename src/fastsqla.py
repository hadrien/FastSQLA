import math
import os
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
from contextlib import _AsyncGeneratorContextManager, asynccontextmanager
from typing import Annotated, Generic, TypeVar, TypedDict

from fastapi import Depends as BaseDepends
from fastapi import FastAPI, Query
from pydantic import BaseModel, Field
from sqlalchemy import Result, Select, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_engine_from_config,
    async_sessionmaker,
)
from sqlalchemy.ext.declarative import DeferredReflection
from sqlalchemy.orm import DeclarativeBase
from structlog import get_logger

logger = get_logger(__name__)

try:
    from sqlmodel.ext.asyncio.session import AsyncSession

except ImportError:
    pass


__all__ = [
    "Base",
    "Collection",
    "Item",
    "Page",
    "Paginate",
    "PaginateType",
    "Session",
    "lifespan",
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


def new_lifespan(
    url: str | None = None, **kw
) -> Callable[[FastAPI], _AsyncGeneratorContextManager[State, None]]:
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
    """

    has_config = url is not None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[State, None]:
        if has_config:
            prefix = ""
            sqla_config = {**kw, **{"url": url}}

        else:
            prefix = "sqlalchemy_"
            sqla_config = {k.lower(): v for k, v in os.environ.items()}

        try:
            engine = async_engine_from_config(sqla_config, prefix=prefix)

        except KeyError as exc:
            raise Exception(f"Missing {prefix}{exc.args[0]} in environ.") from exc

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


class Item(BaseModel, Generic[T]):
    data: T


class Collection(BaseModel, Generic[T]):
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


def new_pagination(
    min_page_size: int = 10,
    max_page_size: int = 100,
    query_count_dependency: Callable[..., Awaitable[int]] | None = None,
    result_processor: Callable[[Result], Iterable] = lambda result: iter(
        result.unique().scalars()
    ),
):
    def default_dependency(
        session: Session,
        offset: int = Query(0, ge=0),
        limit: int = Query(min_page_size, ge=1, le=max_page_size),
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
        limit: int = Query(min_page_size, ge=1, le=max_page_size),
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
