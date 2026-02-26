---
name: fastsqla-models
description: >
  How to define ORM models with FastSQLA. Covers fastsqla.Base
  (DeclarativeBase + DeferredReflection), fully declared models, reflected
  models, Pydantic response models, SQLModel integration, and
  extend_existing. Includes a comparison table of Base vs SQLModel tradeoffs.
---

# FastSQLA Models

FastSQLA provides `Base`, a pre-configured SQLAlchemy declarative base that
combines `DeclarativeBase` with `DeferredReflection`. Alternatively, you can
use SQLModel for models that are both ORM and Pydantic.

## `fastsqla.Base`

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.declarative import DeferredReflection
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase, DeferredReflection):
    __abstract__ = True
```

Because `Base` inherits from `DeferredReflection`, table metadata is **not**
loaded at import time. Instead, `Base.prepare()` is called inside FastSQLA's
lifespan during app startup, which reflects all tables from the database in a
single pass.

This means model attributes (columns, relationships) are **not available**
until the app lifespan has started.

## Fully Declared Models

Standard SQLAlchemy 2.0 declarative mapping. You define every column
explicitly using `Mapped` and `mapped_column`:

```python
from fastsqla import Base
from sqlalchemy.orm import Mapped, mapped_column


class Hero(Base):
    __tablename__ = "hero"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    secret_identity: Mapped[str]
    age: Mapped[int]
```

Columns are fully typed and available for IDE autocompletion even before
`Base.prepare()` runs. The `DeferredReflection` base still applies — the
actual table binding happens at startup.

### Relationships

Declare relationships the standard SQLAlchemy way:

```python
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastsqla import Base


class Team(Base):
    __tablename__ = "team"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    heroes: Mapped[list["Hero"]] = relationship(back_populates="team")


class Hero(Base):
    __tablename__ = "hero"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id"))
    team: Mapped["Team"] = relationship(back_populates="heroes")
```

## Reflected Models (DeferredReflection)

For tables that already exist in the database, declare only the table name.
All columns are auto-reflected from the database schema when `Base.prepare()`
runs at startup:

```python
from fastsqla import Base


class User(Base):
    __tablename__ = "user"
```

After the lifespan starts, `User` has all columns from the `user` table as
attributes (e.g. `User.id`, `User.email`).

**Important:** Reflected model attributes are **not available** until
`Base.prepare()` has been called. Do not access column attributes at module
level or during import.

You can mix reflected and fully declared models freely — both inherit from the
same `Base`.

## Pydantic Response Models

`fastsqla.Base` models are **not** Pydantic models. To use them as FastAPI
response types, create a separate Pydantic `BaseModel` with
`ConfigDict(from_attributes=True)`:

```python
from fastsqla import Base
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Mapped, mapped_column


class Hero(Base):
    __tablename__ = "hero"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    secret_identity: Mapped[str]
    age: Mapped[int]


class HeroResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    secret_identity: str
    age: int
```

Then use `HeroResponse` in your endpoint:

```python
from fastapi import FastAPI
from fastsqla import Item, Session
from sqlalchemy import select

app = FastAPI()


@app.get("/heroes/{hero_id}")
async def get_hero(hero_id: int, session: Session) -> Item[HeroResponse]:
    hero = await session.get(Hero, hero_id)
    return {"data": hero}
```

FastAPI automatically converts the ORM instance to `HeroResponse` via
`from_attributes`.

## SQLModel Alternative

Install with the `sqlmodel` extra:

```bash
pip install FastSQLA[sqlmodel]
```

SQLModel models are both SQLAlchemy ORM models **and** Pydantic models. No
separate response model is needed:

```python
from sqlmodel import Field, SQLModel


class Hero(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    secret_identity: str
    age: int
```

Use directly in endpoints:

```python
from fastapi import FastAPI
from fastsqla import Item, Session
from sqlmodel import select

app = FastAPI()


@app.get("/heroes/{hero_id}")
async def get_hero(hero_id: int, session: Session) -> Item[Hero]:
    hero = (await session.execute(select(Hero).where(Hero.id == hero_id))).scalar_one()
    return {"data": hero}
```

### Session Swap

When SQLModel is installed, FastSQLA silently uses
`sqlmodel.ext.asyncio.session.AsyncSession` instead of SQLAlchemy's
`AsyncSession`. This happens automatically — no configuration needed:

```python
# src/fastsqla.py lines 23-27
try:
    from sqlmodel.ext.asyncio.session import AsyncSession
except ImportError:
    pass
```

The `Session` dependency and all internal session handling use whichever
`AsyncSession` was imported.

### `extend_existing`

When using SQLModel, if another part of your code (or a library) has already
registered a table with the same name in SQLAlchemy's metadata, add
`extend_existing`:

```python
from sqlmodel import Field, SQLModel


class Hero(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    secret_identity: str
    age: int
```

This tells SQLAlchemy to merge the model definition with the existing table
metadata instead of raising an error.

### SQLModel Does Not Use `fastsqla.Base`

SQLModel models inherit from `SQLModel`, not from `fastsqla.Base`. They do
**not** participate in `DeferredReflection` and do **not** support column
reflection. All columns must be explicitly declared.

## Base vs SQLModel Comparison

| Feature | `fastsqla.Base` | SQLModel |
|---|---|---|
| Column reflection | Yes — declare only `__tablename__`, columns auto-reflected | No — all columns must be declared |
| Separate Pydantic model needed | Yes — `BaseModel` with `from_attributes=True` | No — model is both ORM and Pydantic |
| Validation on assignment | No | Yes — Pydantic validation on fields |
| Dependencies | SQLAlchemy only | SQLAlchemy + SQLModel + Pydantic |
| Relationships | Standard SQLAlchemy `relationship()` | SQLModel `Relationship()` (wraps SQLAlchemy) |
| DeferredReflection | Yes — `Base.prepare()` at startup | No — tables registered at import time |
| Install | `pip install FastSQLA` | `pip install FastSQLA[sqlmodel]` |

## Quick Reference

| What you need | What to use |
|---|---|
| Fully declared model with explicit columns | `class MyModel(Base)` with `Mapped` + `mapped_column` |
| Reflected model from existing table | `class MyModel(Base)` with only `__tablename__` |
| Response model for Base | Separate `BaseModel` with `ConfigDict(from_attributes=True)` |
| Combined ORM + Pydantic model | `class MyModel(SQLModel, table=True)` |
| Table already in metadata (SQLModel) | Add `__table_args__ = {"extend_existing": True}` |
