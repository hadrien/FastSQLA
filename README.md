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

>! Note
>! Example uses an sqlite db, but FastSQLA is compatible with any async db supported by
>! SQLAlchemy

Assuming it runs against a DB with a table `user` with 2 columns `id` and `name`:

```python
# main.py
from fastapi import FastAPI, HTTPException
from fastsqla import Base, Item, Page, Paginate, Session, lifespan
from pydantic import BaseModel
from sqlalchemy import select


app = FastAPI(lifespan=lifespan)


class User(Base):
    __tablename__ = "user"


class UserIn(BaseModel):
    name: str


class UserModel(UserIn):
    id: int


@app.get("/users", response_model=Page[UserModel])
async def list_users(paginate: Paginate):
    return await paginate(select(User))


@app.get("/users/{user_id}", response_model=Item[UserModel])
async def get_user(user_id: int, session: Session):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404)
    return {"data": user}


@app.post("/users", response_model=Item[UserModel])
async def create_user(new_user: UserIn, session: Session):
    user = User(**new_user.model_dump())
    session.add(user)
    await session.flush()
    return {"data": user}
```


Create an `sqlite3` db:

```bash
sqlite3 db.sqlite <<EOF
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


Installing [aiosqlite] to connect to the sqlite db asynchronously:
```bash
pip install aiosqlite
```

Running the app:
```bash
sqlalchemy_url=sqlite+aiosqlite:///db.sqlite?check_same_thread=false uvicorn main:app
```

[aiosqlite]: https://github.com/omnilib/aiosqlite
[FastAPI]: https://fastapi.tiangolo.com/
[SQLAlchemy]: http://sqlalchemy.org/
