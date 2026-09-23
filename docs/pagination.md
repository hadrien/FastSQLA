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

Use cursor pagination to load the next batch of results, such as a "Load more" list.
Each response includes a cursor pointing after the last returned item.

Import `Page` and `Paginate` from `fastsqla.cursor`. The top-level imports use offset/limit
pagination. Using `Hero` and `HeroModel` from the example above:

```python { .annotate }
from fastsqla.cursor import Page, Paginate

@app.post("/heroes/search")
async def list_heroes(paginate: Paginate[Hero]) -> Page[HeroModel]: # (1)!
    return await paginate(select(Hero).order_by(Hero.id)) # (2)!
```

1.  `Paginate` reads optional `cursor` and `limit` fields from the POST JSON body.
    The default page size is 10, with a maximum of 100.
2.  Order by a unique, non-null column so each item has a definite position.

Send `{"limit": 10}` to `POST /heroes/search` for the first page, or `{}` to use defaults.
The response contains `data` and `meta.next_cursor`. Pass that cursor in the next JSON
body's `cursor` field. When `next_cursor` is `null`, there are no more results.

Cursor pagination accepts POST requests only. Declare a request model as shown below
to document the body in OpenAPI.

### Filters in a JSON body

Put filters and pagination fields in your endpoint's request model. Use
`new_pagination()` to configure the injectable `Paginate` type:

```python { .annotate }
from typing import Literal
from fastsqla.cursor import Page, new_pagination
from pydantic import BaseModel, ConfigDict, Field

Paginate = new_pagination(default_page_size=10, max_page_size=100)

class HeroSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cursor: str | None = Field(None, min_length=1)
    limit: int = Field(10, ge=1, le=100) # (1)!
    min_age: int | None = Field(None, ge=0)
    order_by: Literal["age", "name"] = "age"

@app.post("/heroes/search")
async def search_heroes(body: HeroSearch, paginate: Paginate[Hero]) -> Page[HeroModel]:
    column = {"age": Hero.age, "name": Hero.name}[body.order_by]
    stmt = select(Hero).order_by(column, Hero.id) # (2)!
    if body.min_age is not None:
        stmt = stmt.where(Hero.age >= body.min_age)
    return await paginate(stmt)
```

1.  Keep defaults and bounds aligned with `new_pagination()`. The dependency validates
    pagination fields independently and leaves filters to `HeroSearch`.
2.  `Hero.id` breaks ties when several heroes have the same age or name.

Send this body to `POST /heroes/search`:

```json
{"min_age": 18, "order_by": "name", "limit": 10}
```

To continue, add `cursor` using the returned `meta.next_cursor`. Keep the filters and
ordering unchanged; omit the cursor to start a different search. Invalid cursors return
HTTP 422.

### Choosing a query

Order by non-null columns with a unique tie-breaker for the whole result set. Ascending,
descending, and mixed directions are supported. Prefer immutable keys: changing a sort
value during traversal can skip or repeat an item.

!!! note "Supported queries"

    Use entity or column selections without outer joins, grouping, `DISTINCT`, unions,
    or existing limits/offsets. Ordering expressions, nullable keys, and SQLite decimal
    ordering are unsupported. SQLite can round decimal values when reading them, which
    loses the exact cursor position.

For column selections, set `row_mapper=lambda row: row._mapping` on
`new_pagination()`. The default mapper returns the first selected entity or value.
Each SQL row must produce one response item; filtering or deduplicating rows in the
mapper breaks pagination.

Cursors contain readable ordering values. Apply authorization on every request and keep
sensitive fields out of the ordering keys.

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
