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

- `CursorPaginate[T]`: `cursor` and `limit` query parameters.
- `CursorPage[T]`: `data` and `meta.next_cursor`; `null` marks the end.
- For JSON input, use `new_cursor_pagination()` as below (`Hero` and `HeroModel` from above).

```python
from typing import Literal
from fastsqla import CursorPage, Session, new_cursor_pagination
from pydantic import BaseModel, ConfigDict, Field

cursor_dependency = new_cursor_pagination(default_page_size=10, max_page_size=100)

class HeroSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cursor: str | None = Field(None, min_length=1)
    limit: int = Field(10, ge=1, le=100)
    min_age: int | None = Field(None, ge=0)
    order_by: Literal["age", "name"] = "age"

@app.post("/heroes/search")
async def search_heroes(body: HeroSearch, session: Session) -> CursorPage[HeroModel]:
    column = {"age": Hero.age, "name": Hero.name}[body.order_by]
    stmt = select(Hero).order_by(column, Hero.id)
    if body.min_age is not None:
        stmt = stmt.where(Hero.age >= body.min_age)
    paginate = cursor_dependency(session=session, cursor=body.cursor, limit=body.limit)
    return await paginate(stmt)
```

- POST body: `{"min_age": 18, "order_by": "name", "limit": 10, "cursor": null}`.
- Omit `cursor` for page one; send `meta.next_cursor` to continue. Keep filters and ordering
  fixed; reapply authorization each request.
- Direct calls require explicit `session`, `cursor`, and `limit`. Validate body values and
  keep page-size limits aligned with the factory.
- Order by non-null columns with a unique tie-breaker, including across joins. Ascending,
  descending, and mixed directions are supported.
- Unsupported: expressions, nullable ordering, outer joins, grouping/distinct/unions,
  existing limits/offsets, and deduplication.
- Default mapping: `row[0]`. For projections, use `row_mapper=lambda row: row._mapping`.
  Map each SQL row to one item; ordering columns need not appear in the response.
- Invalid cursors return HTTP 422. FastSQLA imposes no cursor-length cap.
- Cursors expose ordering values. Changing those values during traversal can skip or
  repeat items; prefer immutable columns and matching indexes.

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
