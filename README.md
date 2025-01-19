# FastAPI-Async-SQLA

[![PyPI - Version](https://img.shields.io/pypi/v/FastAPI-Async-SQLA?color=brightgreen)](https://pypi.org/project/FastAPI-Async-SQLA/)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-brightgreen.svg)](https://conventionalcommits.org)
[![codecov](https://codecov.io/gh/hadrien/fastapi-async-sqla/graph/badge.svg?token=XK3YT60MWK)](https://codecov.io/gh/hadrien/fastapi-async-sqla)

FastAPI-Async-SQLA is an [SQLAlchemy] extension for [FastAPI]. It supports asynchronous
SQLAlchemy sessions using SQLAlchemy >= 2.0 and provides pagination support.

# Installing

Using [pip](https://pip.pypa.io/):
```
pip install fastapi-async-sqla
```

# Quick Example

Assuming it runs against a DB with a table `user` with 2 columns `id` and `name`:

```python
# main.py
from fastapi import FastAPI, HTTPException
from fastapi_async_sqla import Base, Item, Page, Paginate, Session, lifespan
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

Creating a db using `sqlite3`:
```bash
sqlite3 db.sqlite <<EOF
CREATE TABLE user (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL
);
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
