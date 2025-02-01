# FastSQLA

_Async SQLAlchemy 2 for FastAPI — boilerplate, pagination, and seamless session management._

[![PyPI - Version](https://img.shields.io/pypi/v/FastSQLA?color=brightgreen)](https://pypi.org/project/FastSQLA/)
[![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/hadrien/fastsqla/ci.yml?branch=main&logo=github&label=CI)](https://github.com/hadrien/FastSQLA/actions?query=branch%3Amain+event%3Apush)
[![Codecov](https://img.shields.io/codecov/c/github/hadrien/fastsqla?token=XK3YT60MWK&logo=codecov)](https://codecov.io/gh/hadrien/FastSQLA)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-brightgreen.svg)](https://conventionalcommits.org)
[![GitHub License](https://img.shields.io/github/license/hadrien/fastsqla)](https://github.com/hadrien/FastSQLA/blob/main/LICENSE)

**Documentation**: https://hadrien.github.io/FastSQLA/

`FastSQLA` is an [`SQLAlchemy 2`](https://docs.sqlalchemy.org/en/20/) extension for
[`FastAPI`](https://fastapi.tiangolo.com/).
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
    <center>👇👇👇</center>
    ```json
    // /heros?offset=10&limit=10
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
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from fastsqla import Base, Item, Page, Paginate, Session, lifespan

app = FastAPI(lifespan=lifespan)


class Hero(Base):
    __tablename__ = "hero"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    secret_identity: Mapped[str]


class HeroBase(BaseModel):
    name: str
    secret_identity: str


class HeroModel(HeroBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


@app.get("/heros", response_model=Page[HeroModel])
async def list_users(paginate: Paginate):
    stmt = select(Hero)
    return await paginate(stmt)


@app.get("/heros/{hero_id}", response_model=Item[HeroModel])
async def get_user(hero_id: int, session: Session):
    hero = await session.get(Hero, hero_id)
    if hero is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, "Hero not found")
    return {"data": hero}


@app.post("/heros", response_model=Item[HeroModel])
async def create_user(new_hero: HeroBase, session: Session):
    hero = Hero(**new_hero.model_dump())
    session.add(hero)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(HTTPStatus.CONFLICT, "Duplicate hero name")
    return {"data": hero}
```

### Database

💡 This example uses an `SQLite` database for simplicity.

`FastSQLA` is compatible with all asynchronous db drivers that `SQLAlchemy` is
compatible with.

Let's create an `SQLite` database using `sqlite3`:
```bash
sqlite3 db.sqlite <<EOF
CREATE TABLE hero (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE, -- Hero name (e.g., Superman)
    secret_identity TEXT NOT NULL         -- Secret identity (e.g., Clark Kent)
);

-- Insert heroes with hero name and secret identity
INSERT INTO hero (name, secret_identity) VALUES ('Superman',        'Clark Kent');
INSERT INTO hero (name, secret_identity) VALUES ('Batman',          'Bruce Wayne');
INSERT INTO hero (name, secret_identity) VALUES ('Wonder Woman',    'Diana Prince');
INSERT INTO hero (name, secret_identity) VALUES ('Iron Man',        'Tony Stark');
INSERT INTO hero (name, secret_identity) VALUES ('Spider-Man',      'Peter Parker');
INSERT INTO hero (name, secret_identity) VALUES ('Captain America', 'Steve Rogers');
INSERT INTO hero (name, secret_identity) VALUES ('Black Widow',     'Natasha Romanoff');
INSERT INTO hero (name, secret_identity) VALUES ('Thor',            'Thor Odinson');
INSERT INTO hero (name, secret_identity) VALUES ('Scarlet Witch',   'Wanda Maximoff');
INSERT INTO hero (name, secret_identity) VALUES ('Doctor Strange',  'Stephen Strange');
INSERT INTO hero (name, secret_identity) VALUES ('The Flash',       'Barry Allen');
INSERT INTO hero (name, secret_identity) VALUES ('Green Lantern',   'Hal Jordan');
EOF
```

### Run the app

Let's install required dependencies & run the app:
```bash
pip install uvicorn aiosqlite fastsqla
sqlalchemy_url=sqlite+aiosqlite:///db.sqlite?check_same_thread=false uvicorn example:app
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

## License

This project is licensed under the terms of the [MIT license](https://github.com/hadrien/FastSQLA/blob/main/LICENSE).