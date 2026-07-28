# Troubleshooting

Search for the exact error text below, then apply the correction for that failure mode.

## `Missing sqlalchemy_url in environ.`

The default [`fastsqla.lifespan`][fastsqla.lifespan] reads the database URL from
`SQLALCHEMY_URL`. The variable was absent when FastAPI started.

Set an async SQLAlchemy URL before starting the application:

```bash
export SQLALCHEMY_URL=sqlite+aiosqlite:///db.sqlite
uvicorn example:app
```

For configuration in code, create the lifespan explicitly:

```python
from fastapi import FastAPI
from fastsqla import new_lifespan

app = FastAPI(lifespan=new_lifespan("sqlite+aiosqlite:///db.sqlite"))
```

## `The asyncio extension requires an async driver to be used`

The URL selects a synchronous database driver. For example, `sqlite:///db.sqlite` loads
Python's synchronous `pysqlite` driver and produces:

```text
The asyncio extension requires an async driver to be used.
The loaded 'pysqlite' is not async.
```

Install the asynchronous driver for the database and include it in the URL:

| Database   | Install                 | URL prefix             |
|------------|-------------------------|------------------------|
| PostgreSQL | `pip install asyncpg`   | `postgresql+asyncpg://` |
| SQLite     | `pip install aiosqlite` | `sqlite+aiosqlite:///` |
| MySQL      | `pip install aiomysql`  | `mysql+aiomysql://`    |

## `Could not locate a bind configured on SQL expression or this Session.`

A [`Session`][fastsqla.Session] or [`open_session()`][fastsqla.open_session] operation ran
outside the FastSQLA lifespan. The lifespan binds the shared session factory at startup
and clears it at shutdown.

Attach the lifespan to FastAPI:

```python
from fastapi import FastAPI
from fastsqla import lifespan

app = FastAPI(lifespan=lifespan)
```

Use `Session` only in endpoint parameters. Use `open_session()` for background work that
runs after application startup and finishes before shutdown:

```python
from fastsqla import open_session
from sqlalchemy import select

async def refresh_cache() -> None:
    async with open_session() as session:
        heroes = (await session.scalars(select(Hero))).all()
```

Do not import or configure `SessionFactory`; it is an internal lifecycle detail.

## `MissingGreenlet: greenlet_spawn has not been called`

SQLAlchemy attempted implicit database I/O while ordinary Python code accessed an
unloaded ORM attribute. This often happens when response serialization touches a
lazy-loaded relationship.

Load relationships explicitly inside the awaited query. `selectinload()` is a good
default for collections:

```python
from fastsqla import Session
from sqlalchemy import select
from sqlalchemy.orm import selectinload

async def get_team(team_id: int, session: Session) -> Team:
    stmt = (
        select(Team)
        .where(Team.id == team_id)
        .options(selectinload(Team.heroes))
    )
    return (await session.scalars(stmt)).one()
```

See SQLAlchemy's guidance on
[preventing implicit I/O with `AsyncSession`](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#preventing-implicit-io-when-using-asyncsession).

## `Input should be greater than or equal to 0`

The built-in [`Paginate`][fastsqla.Paginate] dependency rejects a negative `offset`.
Start at zero:

```text
GET /heroes?offset=0&limit=10
```

## `Input should be less than or equal to 100`

The built-in `Paginate` dependency accepts `limit` values from 1 through 100. Use a
smaller value or define an intentional maximum:

```python
from typing import Annotated

from fastapi import Depends
from fastsqla import PaginateType, new_pagination

LargePage = Annotated[
    PaginateType[HeroModel],
    Depends(new_pagination(min_page_size=10, max_page_size=250)),
]
```

## `This Session's transaction has been rolled back due to a previous exception`

A database operation such as `flush()` raised an exception, but application code caught
it and then tried to keep using the invalid transaction.

Translate the original database error into an exception and let FastSQLA roll back:

```python
from fastapi import HTTPException
from fastsqla import Session
from sqlalchemy.exc import IntegrityError

async def create_hero(new_hero: HeroInput, session: Session) -> Hero:
    hero = Hero(**new_hero.model_dump())
    session.add(hero)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Hero already exists") from exc
    return hero
```

Do not catch and ignore `IntegrityError`, and do not call `commit()` inside an endpoint.
