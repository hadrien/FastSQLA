---
name: fastsqla-setup
description: >
  How to install and configure FastSQLA with FastAPI. Covers pip installation,
  async driver selection, environment variable configuration via fastsqla.lifespan,
  programmatic configuration via new_lifespan(), and composing multiple lifespans
  with AsyncExitStack.
---

# FastSQLA Setup

FastSQLA is an async SQLAlchemy 2.0+ extension for FastAPI. It provides session
management, pagination, and deferred table reflection out of the box.

The entire library is a single module (`fastsqla`).

## Installation

```bash
pip install FastSQLA
```

### Optional: SQLModel support

```bash
pip install FastSQLA[sqlmodel]
```

When SQLModel is installed, FastSQLA automatically uses `sqlmodel.ext.asyncio.session.AsyncSession`
instead of SQLAlchemy's `AsyncSession`.

### Requirements

- Python >= 3.12
- FastAPI >= 0.115.6
- SQLAlchemy[asyncio] >= 2.0.37

### Async database driver

You **must** install an async driver for your database. The driver determines the URL
scheme:

| Database   | Driver     | Install                | URL scheme                |
|------------|------------|------------------------|---------------------------|
| PostgreSQL | asyncpg    | `pip install asyncpg`  | `postgresql+asyncpg://`   |
| SQLite     | aiosqlite  | `pip install aiosqlite`| `sqlite+aiosqlite:///`    |
| MySQL      | aiomysql   | `pip install aiomysql` | `mysql+aiomysql://`       |

## Configuration

There are two ways to configure FastSQLA: environment variables or programmatic.

### Option 1: Environment variable configuration

Use `fastsqla.lifespan` for 12-factor app style configuration. All configuration is
read from environment variables at startup.

```python
from fastapi import FastAPI
from fastsqla import lifespan

app = FastAPI(lifespan=lifespan)
```

Set environment variables:

```bash
export SQLALCHEMY_URL=postgresql+asyncpg://user:pass@localhost/mydb
export SQLALCHEMY_POOL_SIZE=20
export SQLALCHEMY_MAX_OVERFLOW=10
export SQLALCHEMY_ECHO=true
```

**How it works:** All environment variables prefixed with `SQLALCHEMY_` are collected
(case-insensitive) and passed to SQLAlchemy's `async_engine_from_config()` with prefix
`sqlalchemy_`. This means any `create_async_engine` parameter can be set via env var
using the `SQLALCHEMY_` prefix.

**Required:** `SQLALCHEMY_URL` must be set. If missing, startup raises:
`Missing sqlalchemy_url in environ.`

**Warning:** Stray `SQLALCHEMY_*` environment variables (e.g. from another app or a
typo) will be passed to the engine factory and can cause unexpected errors. Keep your
environment clean.

### Option 2: Programmatic configuration

Use `new_lifespan()` when you want to pass configuration directly in code. It accepts
the same arguments as SQLAlchemy's `create_async_engine()`.

```python
from fastapi import FastAPI
from fastsqla import new_lifespan

lifespan = new_lifespan(
    "sqlite+aiosqlite:///app/db.sqlite",
    connect_args={"autocommit": False},
)

app = FastAPI(lifespan=lifespan)
```

When using `new_lifespan()` with arguments, environment variables are **not** read.

`new_lifespan()` called with no arguments returns the same env-var-based lifespan as
`fastsqla.lifespan`.

## Composing multiple lifespans

If your app has multiple lifespan contexts (e.g. FastSQLA + another library), compose
them with `AsyncExitStack`:

```python
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastsqla import lifespan as fastsqla_lifespan
from other_library import lifespan as other_lifespan


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[dict, None]:
    async with AsyncExitStack() as stack:
        state1 = await stack.enter_async_context(fastsqla_lifespan(app))
        state2 = await stack.enter_async_context(other_lifespan(app))
        yield {**state1, **state2}


app = FastAPI(lifespan=lifespan)
```

Each lifespan returns a state dict. FastSQLA's lifespan returns
`{"fastsqla_engine": <AsyncEngine>}`. Merge them so FastAPI's `request.state` has all
keys.

## What the lifespan does

On **startup**:

1. Creates an `AsyncEngine` via `async_engine_from_config()` — with prefix
   `sqlalchemy_` for the env var path, or with no prefix for the programmatic path.
2. Calls `Base.prepare()` inside a connection — this triggers SQLAlchemy's
   `DeferredReflection`, reflecting table metadata from the database for any model
   inheriting from `fastsqla.Base`.
3. Binds the engine to the shared `SessionFactory` (`async_sessionmaker`).

On **shutdown**:

1. Unbinds the `SessionFactory` (sets `bind=None`).
2. Disposes the engine, closing all pooled connections.
