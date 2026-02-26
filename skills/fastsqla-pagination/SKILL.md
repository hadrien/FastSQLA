---
name: fastsqla-pagination
description: >
  Paginate SQLAlchemy select queries in FastAPI endpoints using FastSQLA.
  Covers the built-in Paginate dependency (offset/limit query params),
  Page/Item/Collection response models, and the new_pagination() factory
  for custom page sizes, count queries, and result processing.
---

# FastSQLA Pagination

FastSQLA provides a `Paginate` dependency that adds `offset` and `limit` query parameters to any FastAPI endpoint and returns paginated results wrapped in a `Page` model.

## Response Models

FastSQLA exports three generic response wrappers:

### `Page[T]` — paginated list with metadata

```json
{
  "data": [{ ... }, { ... }],
  "meta": {
    "offset": 0,
    "total_items": 42,
    "total_pages": 5,
    "page_number": 1
  }
}
```

### `Collection[T]` — plain list, no pagination metadata

```json
{
  "data": [{ ... }, { ... }]
}
```

### `Item[T]` — single item wrapper

```json
{
  "data": { ... }
}
```

## Basic Usage with `Paginate`

`Paginate` is a pre-configured FastAPI dependency. It injects a callable that accepts a SQLAlchemy `Select` and returns a `Page`.

Default query parameters added to the endpoint:
- `offset`: int, default `0`, minimum `0`
- `limit`: int, default `10`, minimum `1`, maximum `100`

```python
from fastapi import FastAPI
from fastsqla import Base, Page, Paginate
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Mapped, mapped_column

app = FastAPI()

class Hero(Base):
    __tablename__ = "hero"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    age: Mapped[int]

class HeroModel(BaseModel):
    id: int
    name: str
    age: int

@app.get("/heroes")
async def list_heroes(paginate: Paginate[HeroModel]) -> Page[HeroModel]:
    return await paginate(select(Hero))
```

A request to `GET /heroes?offset=20&limit=10` returns the third page of results.

## Adding Filters

Combine `Paginate` with additional query parameters:

```python
@app.get("/heroes")
async def list_heroes(
    paginate: Paginate[HeroModel],
    age: int | None = None,
    name: str | None = None,
):
    stmt = select(Hero)
    if age is not None:
        stmt = stmt.where(Hero.age == age)
    if name is not None:
        stmt = stmt.where(Hero.name.ilike(f"%{name}%"))
    return await paginate(stmt)
```

## The `new_pagination()` Factory

For custom pagination behavior, use `new_pagination()` to create a new dependency. It accepts four parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `min_page_size` | `int` | `10` | Default and minimum `limit` value |
| `max_page_size` | `int` | `100` | Maximum allowed `limit` value |
| `query_count_dependency` | `Callable[..., Awaitable[int]] \| None` | `None` | FastAPI dependency returning total item count. When `None`, uses `SELECT COUNT(*) FROM (subquery)`. |
| `result_processor` | `Callable[[Result], Iterable]` | `lambda r: iter(r.unique().scalars())` | Transforms the SQLAlchemy `Result` into an iterable of items |

The return value is a FastAPI dependency. Use it with `Annotated` and `Depends`:

```python
from typing import Annotated
from fastapi import Depends
from fastsqla import PaginateType, new_pagination
```

### `PaginateType[T]`

Type alias for the paginate callable:

```python
type PaginateType[T] = Callable[[Select], Awaitable[Page[T]]]
```

Use this when annotating custom pagination dependencies.

## Custom Page Sizes

```python
from typing import Annotated
from fastapi import Depends
from fastsqla import Page, PaginateType, new_pagination

SmallPagePaginate = Annotated[
    PaginateType[HeroModel],
    Depends(new_pagination(min_page_size=5, max_page_size=25)),
]

@app.get("/heroes")
async def list_heroes(paginate: SmallPagePaginate) -> Page[HeroModel]:
    return await paginate(select(Hero))
```

This endpoint has `limit` defaulting to `5` with a maximum of `25`.

## Custom Count Query

The default count query runs `SELECT COUNT(*) FROM (your_select_as_subquery)`. For joins or complex queries where this is inefficient, provide a `query_count_dependency` — a FastAPI dependency that receives the session and returns an `int`:

```python
from typing import cast
from sqlalchemy import func, select
from fastsqla import Session

async def query_count(session: Session) -> int:
    result = await session.execute(select(func.count()).select_from(Sticky))
    return cast(int, result.scalar())
```

Then pass it to `new_pagination()`:

```python
CustomPaginate = Annotated[
    PaginateType[StickyModel],
    Depends(new_pagination(query_count_dependency=query_count)),
]
```

## Custom Result Processor

The default `result_processor` is:

```python
lambda result: iter(result.unique().scalars())
```

This works for single-entity selects like `select(Hero)`. For multi-column selects (e.g., joins returning individual columns), use `.mappings()`:

```python
lambda result: iter(result.mappings())
```

## Full Custom Pagination Example

Combining a custom count query and a custom result processor for a join:

```python
from typing import Annotated, cast
from fastapi import Depends, FastAPI
from fastsqla import Base, Page, PaginateType, Session, new_pagination
from pydantic import BaseModel
from sqlalchemy import ForeignKey, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

app = FastAPI()

class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str]

class Sticky(Base):
    __tablename__ = "sticky"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(User.id))
    body: Mapped[str]

class StickyModel(BaseModel):
    id: int
    body: str
    user_id: int
    user_email: str
    user_name: str

async def query_count(session: Session) -> int:
    result = await session.execute(select(func.count()).select_from(Sticky))
    return cast(int, result.scalar())

CustomPaginate = Annotated[
    PaginateType[StickyModel],
    Depends(
        new_pagination(
            query_count_dependency=query_count,
            result_processor=lambda result: iter(result.mappings()),
        )
    ),
]

@app.get("/stickies")
async def list_stickies(paginate: CustomPaginate) -> Page[StickyModel]:
    stmt = select(
        Sticky.id,
        Sticky.body,
        User.id.label("user_id"),
        User.email.label("user_email"),
        User.name.label("user_name"),
    ).join(User)
    return await paginate(stmt)
```

## SQLModel Usage

When using SQLModel, models serve as both ORM and response models — no separate Pydantic model is needed:

```python
from fastsqla import Page, Paginate
from sqlmodel import Field, SQLModel, select

class Hero(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    age: int

@app.get("/heroes")
async def list_heroes(paginate: Paginate[Hero]) -> Page[Hero]:
    return await paginate(select(Hero))
```

## Quick Reference

| What you need | What to use |
|---|---|
| Standard pagination (offset/limit) | `Paginate[T]` |
| Custom page sizes | `Annotated[PaginateType[T], Depends(new_pagination(min_page_size=..., max_page_size=...))]` |
| Custom count for joins | `new_pagination(query_count_dependency=my_count_dep)` |
| Multi-column select results | `new_pagination(result_processor=lambda r: iter(r.mappings()))` |
| Type annotation for paginate callable | `PaginateType[T]` |
| Paginated response | `Page[T]` (data + meta) |
| Unpaginated list response | `Collection[T]` (data only) |
| Single item response | `Item[T]` (data only) |
