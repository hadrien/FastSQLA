# FastSQLA

_Async SQLAlchemy 2.0+ for FastAPI — boilerplate, pagination, and seamless session management._

[![PyPI - Version](https://img.shields.io/pypi/v/FastSQLA?color=brightgreen)](https://pypi.org/project/FastSQLA/)
[![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/hadrien/fastsqla/ci.yml?branch=main&logo=github&label=CI)](https://github.com/hadrien/FastSQLA/actions?query=branch%3Amain+event%3Apush)
[![Codecov](https://img.shields.io/codecov/c/github/hadrien/fastsqla?token=XK3YT60MWK&logo=codecov)](https://codecov.io/gh/hadrien/FastSQLA)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-brightgreen.svg)](https://conventionalcommits.org)
[![GitHub License](https://img.shields.io/github/license/hadrien/fastsqla)](https://github.com/hadrien/FastSQLA/blob/main/LICENSE)
[![🍁 With love from Canada](https://img.shields.io/badge/With%20love%20from%20Canada-ffffff?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI2MDAiIGhlaWdodD0iNjAwIiB2aWV3Qm94PSItMjAxNSAtMjAwMCA0MDMwIDQwMzAiPjxwYXRoIGZpbGw9IiNmMDAiIGQ9Im0tOTAgMjAzMCA0NS04NjNhOTUgOTUgMCAwIDAtMTExLTk4bC04NTkgMTUxIDExNi0zMjBhNjUgNjUgMCAwIDAtMjAtNzNsLTk0MS03NjIgMjEyLTk5YTY1IDY1IDAgMCAwIDM0LTc5bC0xODYtNTcyIDU0MiAxMTVhNjUgNjUgMCAwIDAgNzMtMzhsMTA1LTI0NyA0MjMgNDU0YTY1IDY1IDAgMCAwIDExMS01N2wtMjA0LTEwNTIgMzI3IDE4OWE2NSA2NSAwIDAgMCA5MS0yN2wzMzItNjUyIDMzMiA2NTJhNjUgNjUgMCAwIDAgOTEgMjdsMzI3LTE4OS0yMDQgMTA1MmE2NSA2NSAwIDAgMCAxMTEgNTdsNDIzLTQ1NCAxMDUgMjQ3YTY1IDY1IDAgMCAwIDczIDM4bDU0Mi0xMTUtMTg2IDU3MmE2NSA2NSAwIDAgMCAzNCA3OWwyMTIgOTktOTQxIDc2MmE2NSA2NSAwIDAgMC0yMCA3M2wxMTYgMzIwLTg1OS0xNTFhOTUgOTUgMCAwIDAtMTExIDk4bDQ1IDg2M3oiLz48L3N2Zz4K)](https://montrealpython.org)

**Documentation**: [https://hadrien.github.io/FastSQLA/](https://hadrien.github.io/FastSQLA/)

**Github Repo:** [https://github.com/hadrien/fastsqla](https://github.com/hadrien/fastsqla)

-----------------------------------------------------------------------------------------

`FastSQLA` is an async [`SQLAlchemy 2.0+`](https://docs.sqlalchemy.org/en/20/)
extension for [`FastAPI`](https://fastapi.tiangolo.com/) with built-in pagination,
[`SQLModel`](http://sqlmodel.tiangolo.com/) support and more.

It streamlines the configuration and asynchronous connection to relational databases by
providing boilerplate and intuitive helpers. Additionally, it offers built-in
customizable pagination and automatically manages the `SQLAlchemy` session lifecycle
following [`SQLAlchemy`'s best practices](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#when-do-i-construct-a-session-when-do-i-commit-it-and-when-do-i-close-it).


## Features

* Easy setup at app startup using
  [`FastAPI` Lifespan](https://fastapi.tiangolo.com/advanced/events/#lifespan):

    ```python
    from fastapi import FastAPI
    from fastsqla import lifespan

    app = FastAPI(lifespan=lifespan)
    ```

* `SQLAlchemy` async session dependency:

    ```python
    ...
    from fastsqla import Session
    from sqlalchemy import select
    ...

    @app.get("/heros")
    async def get_heros(session:Session):
        stmt = select(...)
        result = await session.execute(stmt)
        ...
    ```

* `SQLAlchemy` async session with an async context manager:

    ```python
    from fastsqla import open_session

    async def background_job():
        async with open_session() as session:
            stmt = select(...)
            result = await session.execute(stmt)
            ...
    ```

* Built-in pagination:

    ```python
    ...
    from fastsqla import Page, Paginate
    from sqlalchemy import select
    ...

    @app.get("/heros", response_model=Page[HeroModel])
    async def get_heros(paginate:Paginate):
        return await paginate(select(Hero))
    ```

    <center>

    👇 `/heros?offset=10&limit=10` 👇

    </center>

    ```json
    {
      "data": [
        {
          "name": "The Flash",
          "secret_identity": "Barry Allen",
          "id": 11
        },
        {
          "name": "Green Lantern",
          "secret_identity": "Hal Jordan",
          "id": 12
        }
      ],
      "meta": {
        "offset": 10,
        "total_items": 12,
        "total_pages": 2,
        "page_number": 2
      }
    }
    ```

* Pagination customization:
    ```python
    ...
    from fastapi import Page, new_pagination
    ...

    Paginate = new_pagination(min_page_size=5, max_page_size=500)

    @app.get("/heros", response_model=Page[HeroModel])
    async def get_heros(paginate:Paginate):
        return paginate(select(Hero))
    ```
* Session lifecycle management: session is commited on request success or rollback on
  failure.

* [`SQLModel`](http://sqlmodel.tiangolo.com/) support:
    ```python
    ...
    from fastsqla import Item, Page, Paginate, Session
    from sqlmodel import Field, SQLModel
    ...

    class Hero(SQLModel, table=True):
        id: int | None = Field(default=None, primary_key=True)
        name: str
        secret_identity: str
        age: int


    @app.get("/heroes", response_model=Page[Hero])
    async def get_heroes(paginate: Paginate):
        return await paginate(select(Hero))


    @app.get("/heroes/{hero_id}", response_model=Item[Hero])
    async def get_hero(session: Session, hero_id: int):
        hero = await session.get(Hero, hero_id)
        if hero is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        return {"data": hero}
    ```

## Installing

Using [uv](https://docs.astral.sh/uv/):
```bash
uv add fastsqla
```

Using [pip](https://pip.pypa.io/):
```
pip install fastsqla
```

## Quick Example

### `example.py`

Let's write some tiny app in `example.py`:

```python
# example.py
from http import HTTPStatus

from fastapi import FastAPI, HTTPException
from fastsqla import Base, Item, Page, Paginate, Session, lifespan
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column


app = FastAPI(lifespan=lifespan)


class Hero(Base):
    __tablename__ = "hero"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    secret_identity: Mapped[str]
    age: Mapped[int]


class HeroBase(BaseModel):
    name: str
    secret_identity: str
    age: int


class HeroModel(HeroBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


@app.get("/heros", response_model=Page[HeroModel])
async def list_heros(paginate: Paginate):
    stmt = select(Hero)
    return await paginate(stmt)


@app.get("/heros/{hero_id}", response_model=Item[HeroModel])
async def get_hero(hero_id: int, session: Session):
    hero = await session.get(Hero, hero_id)
    if hero is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, "Hero not found")
    return {"data": hero}


@app.post("/heros", response_model=Item[HeroModel])
async def create_hero(new_hero: HeroBase, session: Session):
    hero = Hero(**new_hero.model_dump())
    session.add(hero)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(HTTPStatus.CONFLICT, "Duplicate hero name")
    return {"data": hero}
```

### Database

💡 This example uses an `SQLite` database for simplicity: `FastSQLA` is compatible with
all asynchronous db drivers that `SQLAlchemy` is compatible with.

Let's create an `SQLite` database using `sqlite3` and insert 12 rows in the `hero` table:

```bash
sqlite3 db.sqlite <<EOF
-- Create Table hero
CREATE TABLE hero (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE, -- Unique hero name (e.g., Superman)
    secret_identity TEXT NOT NULL,        -- Secret identity (e.g., Clark Kent)
    age             INTEGER NOT NULL      -- Age of the hero (e.g., 30)
);

-- Insert heroes with their name, secret identity, and age
INSERT INTO hero (name, secret_identity, age) VALUES ('Superman',        'Clark Kent',       30);
INSERT INTO hero (name, secret_identity, age) VALUES ('Batman',          'Bruce Wayne',      35);
INSERT INTO hero (name, secret_identity, age) VALUES ('Wonder Woman',    'Diana Prince',     30);
INSERT INTO hero (name, secret_identity, age) VALUES ('Iron Man',        'Tony Stark',       45);
INSERT INTO hero (name, secret_identity, age) VALUES ('Spider-Man',      'Peter Parker',     25);
INSERT INTO hero (name, secret_identity, age) VALUES ('Captain America', 'Steve Rogers',     100);
INSERT INTO hero (name, secret_identity, age) VALUES ('Black Widow',     'Natasha Romanoff', 35);
INSERT INTO hero (name, secret_identity, age) VALUES ('Thor',            'Thor Odinson',     1500);
INSERT INTO hero (name, secret_identity, age) VALUES ('Scarlet Witch',   'Wanda Maximoff',   30);
INSERT INTO hero (name, secret_identity, age) VALUES ('Doctor Strange',  'Stephen Strange',  40);
INSERT INTO hero (name, secret_identity, age) VALUES ('The Flash',       'Barry Allen',      28);
INSERT INTO hero (name, secret_identity, age) VALUES ('Green Lantern',   'Hal Jordan',       35);
EOF
```

### Run the app

Let's install required dependencies:
```bash
pip install uvicorn aiosqlite fastsqla
```
Let's run the app:
```
sqlalchemy_url=sqlite+aiosqlite:///db.sqlite?check_same_thread=false \
  uvicorn example:app
```

### Check the result

Execute `GET /heros?offset=10&limit=10` using `curl`:
```bash
curl -X 'GET' -H 'accept: application/json' 'http://127.0.0.1:8000/heros?offset=10&limit=10'
```
Returns:
```json
{
  "data": [
    {
      "name": "The Flash",
      "secret_identity": "Barry Allen",
      "id": 11
    },
    {
      "name": "Green Lantern",
      "secret_identity": "Hal Jordan",
      "id": 12
    }
  ],
  "meta": {
    "offset": 10,
    "total_items": 12,
    "total_pages": 2,
    "page_number": 2
  }
}
```

You can also check the generated openapi doc by opening your browser to
[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

![OpenAPI generated documentation of the example API](https://raw.githubusercontent.com/hadrien/FastSQLA/refs/heads/main/docs/images/example-openapi-generated-doc.png)

## License

This project is licensed under the terms of the [MIT license](https://github.com/hadrien/FastSQLA/blob/main/LICENSE).
