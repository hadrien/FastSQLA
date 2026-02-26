---
name: fastsqla-testing
description: >
  Patterns for testing FastSQLA applications with pytest. Covers the async fixture
  chain (tmp SQLite → patched env → engine → table setup → FastAPI app → ASGI client),
  critical teardown to prevent mapper leaks between tests, direct DB verification with
  a separate session, and SQLModel integration test marks.
---

# Testing FastSQLA Applications

FastSQLA tests run as async integration tests against a per-test temporary SQLite database. The fixture chain is **order-sensitive** — each fixture depends on the previous one.

## Test Dependencies

Install the testing dependencies:

```
pip install pytest pytest-asyncio httpx asgi-lifespan aiosqlite faker
```

- **pytest-asyncio**: async test and fixture support
- **httpx** + **asgi-lifespan**: ASGI client without a running server
- **aiosqlite**: async SQLite driver for isolated per-test databases
- **faker**: generates realistic test data (provides a `faker` pytest fixture)

## pytest Configuration

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

- `asyncio_mode = "auto"` — all `async def` tests and fixtures run without `@pytest.mark.asyncio`
- `asyncio_default_fixture_loop_scope = "function"` — each test gets its own event loop

## Fixture Chain

The fixtures form a strict dependency chain. **Ordering matters** — creating tables must happen before `Base.prepare()` runs during the app lifespan, and mapper cleanup must run after every test.

```
sqlalchemy_url → environ → engine → setup_tear_down → app → client
                                  ↘ session (direct DB verification)
```

### 1. `sqlalchemy_url` — Per-test temporary database

Each test gets its own SQLite file in pytest's `tmp_path`:

```python
from pytest import fixture


@fixture
def sqlalchemy_url(tmp_path):
    return f"sqlite+aiosqlite:///{tmp_path}/test.db"
```

### 2. `environ` — Patched environment with `clear=True`

Patches `os.environ` so FastSQLA's lifespan reads the test database URL. **`clear=True` is critical** — it prevents any stray `SQLALCHEMY_*` variables from the host environment from interfering:

```python
from unittest.mock import patch
from pytest import fixture


@fixture
def environ(sqlalchemy_url):
    values = {"PYTHONASYNCIODEBUG": "1", "SQLALCHEMY_URL": sqlalchemy_url}
    with patch.dict("os.environ", values=values, clear=True):
        yield values
```

### 3. `engine` — Async engine with teardown

Creates a standalone engine for direct DB operations (table setup, data seeding, verification). Disposed after the test:

```python
from pytest import fixture
from sqlalchemy.ext.asyncio import create_async_engine


@fixture
async def engine(environ):
    engine = create_async_engine(environ["SQLALCHEMY_URL"])
    yield engine
    await engine.dispose()
```

### 4. `setup_tear_down` — Create tables via raw SQL

Tables **must** be created with raw SQL before `Base.prepare()` runs (which happens during the ASGI lifespan). This is because `Base` inherits from `DeferredReflection` — it reflects existing tables rather than creating them:

```python
from pytest import fixture
from sqlalchemy import text


@fixture(autouse=True)
async def setup_tear_down(engine):
    async with engine.connect() as conn:
        await conn.execute(
            text("""
            CREATE TABLE hero (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                secret_identity TEXT NOT NULL,
                age INTEGER NOT NULL
            )
            """)
        )
```

For tests that need seed data (e.g., pagination), insert rows in the same fixture using Core operations:

```python
from sqlalchemy import MetaData, Table


@fixture(autouse=True)
async def setup_tear_down(engine, faker):
    async with engine.connect() as conn:
        await conn.execute(text("CREATE TABLE user (...)"))
        metadata = MetaData()
        user = await conn.run_sync(
            lambda sync_conn: Table("user", metadata, autoload_with=sync_conn)
        )
        await conn.execute(
            user.insert(),
            [{"email": faker.email(), "name": faker.name()} for _ in range(42)],
        )
        await conn.commit()
```

### 5. `app` — FastAPI application with models and routes

The base `app` fixture creates a FastAPI app with the FastSQLA lifespan. Each test module **overrides** this fixture to register its own ORM models and routes:

**Base fixture** (in `tests/integration/conftest.py`):

```python
from pytest import fixture
from fastapi import FastAPI


@fixture
def app(environ):
    from fastsqla import lifespan
    app = FastAPI(lifespan=lifespan)
    return app
```

**Per-module override** (depends on `setup_tear_down` to ensure tables exist first):

```python
from pytest import fixture
from sqlalchemy.orm import Mapped, mapped_column


@fixture
def app(setup_tear_down, app):
    from fastsqla import Base, Item, Session

    class User(Base):
        __tablename__ = "user"
        id: Mapped[int] = mapped_column(primary_key=True)
        email: Mapped[str] = mapped_column(unique=True)
        name: Mapped[str]

    @app.post("/users", response_model=Item[UserModel])
    async def create_user(user_in: UserIn, session: Session):
        user = User(**user_in.model_dump())
        session.add(user)
        await session.flush()
        return {"data": user}

    return app
```

**Key detail**: The overriding `app` fixture takes `setup_tear_down` as a parameter to enforce that tables are created before `Base.prepare()` runs.

### 6. `client` — ASGI test client

Uses `asgi-lifespan` to trigger the app's startup/shutdown events (which runs `Base.prepare()`), then wraps it with httpx for HTTP requests:

```python
from asgi_lifespan import LifespanManager
from httpx import AsyncClient, ASGITransport
from pytest import fixture


@fixture
async def client(app):
    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://app") as client:
            yield client
```

## Critical Teardown — Preventing Mapper Leaks

**This is the most common testing pitfall.** Without this autouse fixture, ORM model definitions from one test leak into subsequent tests, causing `ArgumentError: Class already has a primary mapper defined` or `InvalidRequestError`:

```python
from pytest import fixture


@fixture(autouse=True)
def tear_down():
    from sqlalchemy.orm import clear_mappers
    from fastsqla import Base

    yield

    Base.metadata.clear()
    clear_mappers()
```

**Why both calls?**
- `Base.metadata.clear()` removes all table definitions from the shared `MetaData`
- `clear_mappers()` removes all class-to-table mapper configurations

This fixture is **synchronous** and **autouse** — it runs automatically after every test without being explicitly requested.

## Direct Data Verification

Use a separate `session` fixture bound to the same engine to query the database directly, bypassing the application layer. This verifies that the app actually persisted data:

```python
from pytest import fixture
from sqlalchemy.ext.asyncio import AsyncSession


@fixture
async def session(engine):
    async with engine.connect() as conn:
        yield AsyncSession(bind=conn)
```

Usage in a test:

```python
from sqlalchemy import text


async def test_user_is_persisted(client, session):
    payload = {"email": "bob@bob.com", "name": "Bobby"}
    res = await client.post("/users", json=payload)
    assert res.status_code == 201

    rows = (await session.execute(text("SELECT * FROM user"))).mappings().all()
    assert rows == [{"id": 1, **payload}]
```

## SQLModel Integration Tests

Tests requiring SQLModel use a custom marker and an autouse fixture that skips them when SQLModel is not installed:

### Register the marker

```python
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "require_sqlmodel: skip test when sqlmodel is not installed."
    )
```

### Auto-skip fixture

```python
from pytest import fixture, skip

try:
    import sqlmodel
except ImportError:
    is_sqlmodel_installed = False
else:
    is_sqlmodel_installed = True


@fixture(autouse=True)
def check_sqlmodel(request):
    marker = request.node.get_closest_marker("require_sqlmodel")
    if marker and not is_sqlmodel_installed:
        skip(f"{request.node.nodeid} requires sqlmodel which is not installed.")
```

### Mark an entire module

```python
from pytest import mark

pytestmark = mark.require_sqlmodel
```

### SQLModel model definition

SQLModel models need `__table_args__ = {"extend_existing": True}` since the table was already created via raw SQL and reflected by `Base.prepare()`:

```python
from sqlmodel import Field, SQLModel


class Hero(SQLModel, table=True):
    __table_args__ = {"extend_existing": True}
    id: int | None = Field(default=None, primary_key=True)
    name: str
    secret_identity: str
    age: int
```

## Integration Test Example

A complete test that creates a resource via POST and verifies it was persisted:

```python
from http import HTTPStatus
from pydantic import BaseModel, ConfigDict
from pytest import fixture
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column
from fastapi import HTTPException


@fixture(autouse=True)
async def setup_tear_down(engine):
    async with engine.connect() as conn:
        await conn.execute(
            text("""
            CREATE TABLE user (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL
            )
            """)
        )


@fixture
def app(setup_tear_down, app):
    from fastsqla import Base, Item, Session

    class User(Base):
        __tablename__ = "user"
        id: Mapped[int] = mapped_column(primary_key=True)
        email: Mapped[str] = mapped_column(unique=True)
        name: Mapped[str]

    class UserIn(BaseModel):
        email: str
        name: str

    class UserModel(UserIn):
        model_config = ConfigDict(from_attributes=True)
        id: int

    @app.post("/users", response_model=Item[UserModel], status_code=HTTPStatus.CREATED)
    async def create_user(user_in: UserIn, session: Session):
        user = User(**user_in.model_dump())
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:
            raise HTTPException(status_code=400)
        return {"data": user}

    return app


async def test_create_and_verify(client, session):
    payload = {"email": "bob@bob.com", "name": "Bobby"}
    res = await client.post("/users", json=payload)
    assert res.status_code == HTTPStatus.CREATED

    all_users = (await session.execute(text("SELECT * FROM user"))).mappings().all()
    assert all_users == [{"id": 1, **payload}]
```
