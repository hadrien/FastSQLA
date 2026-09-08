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
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Mapped, mapped_column

app = FastAPI(lifespan=lifespan)

class Hero(Base):
    __tablename__ = "hero"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    secret_identity: Mapped[str]
    age: Mapped[int]


class HeroModel(BaseModel):
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

## Forward-only cursor pagination

```python
from fastsqla import CursorPage, CursorPaginate

@app.get("/heroes/cursor")
async def list_heroes(paginate: CursorPaginate[HeroModel]) -> CursorPage[HeroModel]:
    return await paginate(select(Hero).order_by(Hero.age.desc(), Hero.id.desc()))
```

Omit `cursor` for page one; pass `meta.next_cursor` to continue. Null marks the end.
Responses have `data` and `meta.next_cursor`; queries fetch at most `limit + 1` rows.
`new_cursor_pagination(default_page_size=10, max_page_size=100)` sets limits (minimum 1).
Set `row_mapper=lambda row: row._mapping` for projections; the default selects `row[0]`.
Ordering columns need not appear in the response.

Declare direct, non-null ordering columns and include a unique tie-breaker, such as the
primary key. Ascending, descending, and mixed directions are supported. The application
owns ordering uniqueness, including across joins. Map each SQL row to one output item.
Unsupported: expressions, nullable ordering, outer joins, grouping/distinct/unions,
limits/offsets, and deduplication. Invalid cursors return HTTP 422.

Reapply authorization and fixed filters each request. Cursors encode ordering values and
provide no confidentiality. Traversal reads live data: deleting the boundary row is safe,
but changing ordering values can skip or repeat items. Prefer immutable ordering columns
and indexes matching the filters and ordering; pagination does not provide a snapshot.

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
