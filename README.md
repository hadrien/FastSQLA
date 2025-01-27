# FastSQLA

[![PyPI - Version](https://img.shields.io/pypi/v/FastSQLA?color=brightgreen)](https://pypi.org/project/FastSQLA/)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-brightgreen.svg)](https://conventionalcommits.org)
[![codecov](https://codecov.io/gh/hadrien/fastsqla/graph/badge.svg?token=XK3YT60MWK)](https://codecov.io/gh/hadrien/fastsqla)

FastSQLA is an [SQLAlchemy] extension for [FastAPI]. It supports asynchronous
SQLAlchemy sessions using SQLAlchemy >= 2.0 and include built-in pagination.

# Installing

Using [uv](https://docs.astral.sh/uv/):
```bash
uv add fastsqla
```

Using [pip](https://pip.pypa.io/):
```
pip install fastsqla
```

# Quick Example

Assuming it runs against a DB with a table `hero` with 3 columns `id`, `name` and
`secret_identity`:

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
    return await paginate(select(Hero))


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

<detail>
<summary>Create an`sqlite3` db</summary>

> [!NOTE]
> The example uses an sqlite db, but FastSQLA is compatible with any async db driver
> supported by [SQLAlchemy]

```bash
sqlite3 db.sqlite <<EOF
CREATE TABLE hero (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE, -- Hero name (e.g., Superman)
    secret_identity TEXT NOT NULL         -- Secret identity (e.g., Clark Kent)
);

-- Insert heroes with hero name and secret identity
INSERT INTO hero (name, secret_identity) VALUES ('Superman', 'Clark Kent');
INSERT INTO hero (name, secret_identity) VALUES ('Batman', 'Bruce Wayne');
INSERT INTO hero (name, secret_identity) VALUES ('Wonder Woman', 'Diana Prince');
INSERT INTO hero (name, secret_identity) VALUES ('Iron Man', 'Tony Stark');
INSERT INTO hero (name, secret_identity) VALUES ('Spider-Man', 'Peter Parker');
INSERT INTO hero (name, secret_identity) VALUES ('Captain America', 'Steve Rogers');
INSERT INTO hero (name, secret_identity) VALUES ('Black Widow', 'Natasha Romanoff');
INSERT INTO hero (name, secret_identity) VALUES ('Thor', 'Thor Odinson');
INSERT INTO hero (name, secret_identity) VALUES ('Scarlet Witch', 'Wanda Maximoff');
INSERT INTO hero (name, secret_identity) VALUES ('Doctor Strange', 'Stephen Strange');
INSERT INTO hero (name, secret_identity) VALUES ('The Flash', 'Barry Allen');
INSERT INTO hero (name, secret_identity) VALUES ('Green Lantern', 'Hal Jordan');
EOF
```
</detail>


1. Install the packages require by the example:
```bash
pip install aiosqlite uvicorn fastsqla
```

2. Run it
```bash
sqlalchemy_url=sqlite+aiosqlite:///db.sqlite?check_same_thread=false uvicorn example:app
```

3. `GET /heros?offset=10`

  ```bash
  curl -X 'GET' \
    'http://127.0.0.1:8000/heros?offset=10&limit=10' \
    -H 'accept: application/json'
  ```
  Returns
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

[aiosqlite]: https://github.com/omnilib/aiosqlite
[FastAPI]: https://fastapi.tiangolo.com/
[SQLAlchemy]: http://sqlalchemy.org/
