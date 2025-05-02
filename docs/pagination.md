# Pagination

## `fastapi.Page[T]`

::: fastsqla.Page
    options:
        heading_level: false
        show_source: false


## `fastsqla.Paginate`

::: fastsqla.Paginate
    options:
        heading_level: false
        show_source: false

## `SQLAlchemy` example

``` py title="example.py" hl_lines="25 26 27"
from fastapi import FastAPI
from fastsqla import Base, Paginate, Page, lifespan
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Mapped, mapped_column

app = FastAPI(lifespan=lifespan)

class Hero(Base):
    __tablename__ = "hero"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    secret_identity: Mapped[str]
    age: Mapped[int]


class HeroModel(HeroBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    secret_identity: str
    age: int


@app.get("/heros", response_model=Page[HeroModel]) # (1)!
async def list_heros(paginate: Paginate): # (2)!
    return await paginate(select(Hero)) # (3)!
```

1.  The endpoint returns a `Page` model of `HeroModel`.
2.  Just define an argument with type `Paginate` to get an async `paginate` function
    injected in your endpoint function.
3.  Await the `paginate` function with the `SQLAlchemy` select statement to get the
    paginated result.

To add filtering, just add whatever query parameters you need to the endpoint:

```python
@app.get("/heros", response_model=Page[HeroModel])
async def list_heros(paginate: Paginate, age:int | None = None):
    stmt = select(Hero)
    if age:
        stmt = stmt.where(Hero.age == age)
    return await paginate(stmt)
```

## `SQLModel` example

```python
from fastapi import FastAPI
from fastsqla import Page, Paginate, Session
from sqlmodel import Field, SQLModel
from sqlalchemy import select


class Hero(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    secret_identity: str
    age: int


@app.get("/heroes", response_model=Page[Hero])
async def get_heroes(paginate: Paginate):
    return await paginate(select(Hero))
```
