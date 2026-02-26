---
name: fastsqla-session
description: >
  Manages async SQLAlchemy sessions in FastSQLA endpoints and background tasks.
  Covers the Session dependency (auto-commit/rollback lifecycle), flush vs commit
  rules, IntegrityError handling, and the open_session() context manager. Use when
  writing FastAPI endpoints or background tasks that interact with a database through
  FastSQLA.
---

# FastSQLA Session Management

FastSQLA provides two ways to get an async SQLAlchemy session:

1. **`Session`** — A FastAPI dependency for endpoints.
2. **`open_session()`** — An async context manager for non-endpoint code.

Both follow the same lifecycle: auto-commit on success, auto-rollback on exception, always close.

---

## Session Dependency

`Session` is a FastAPI dependency. Type-annotate an endpoint parameter as `Session` and FastAPI injects an async session automatically.

```python
from fastsqla import Session, Item

@app.get("/users/{user_id}", response_model=Item[UserModel])
async def get_user(session: Session, user_id: int):
    user = await session.get(User, user_id)
    return {"data": user}
```

### Lifecycle

| Phase     | What happens                                         |
|-----------|------------------------------------------------------|
| Success   | Session is **committed** automatically               |
| Exception | Session is **rolled back** automatically             |
| Always    | Session is **closed**, connection returned to pool   |

You do not need to manage any of this yourself.

---

## Critical: flush() vs commit()

**NEVER call `session.commit()` inside an endpoint.** FastSQLA commits automatically when the endpoint returns without error. Calling `commit()` manually breaks the transactional guarantee — if an error occurs after your manual commit, the already-committed changes cannot be rolled back.

Use `session.flush()` when you need server-generated data (e.g., auto-increment IDs) before the response is returned. Flushing sends pending changes to the database **within the current transaction** without finalizing it.

### CORRECT — use flush()

```python
from fastsqla import Session, Item

@app.post("/heroes", response_model=Item[HeroItem])
async def create_hero(session: Session, new_hero: HeroBase):
    hero = Hero(**new_hero.model_dump())
    session.add(hero)
    await session.flush()  # hero.id is now populated
    return {"data": hero}
# FastSQLA auto-commits here
```

### INCORRECT — do not call commit()

```python
from fastsqla import Session, Item

@app.post("/heroes", response_model=Item[HeroItem])
async def create_hero(session: Session, new_hero: HeroBase):
    hero = Hero(**new_hero.model_dump())
    session.add(hero)
    await session.commit()  # WRONG: breaks auto-commit lifecycle
    return {"data": hero}
```

If you call `commit()` and a later step raises an exception, the committed data **cannot** be rolled back. Let FastSQLA handle the commit.

---

## IntegrityError Handling

When a `flush()` triggers a constraint violation (unique, foreign key, etc.), SQLAlchemy raises `IntegrityError`. The session is **invalidated** after this — you cannot continue using it for further queries.

The correct pattern is to catch `IntegrityError` after `flush()` and re-raise it as an `HTTPException`. The raised exception triggers FastSQLA's automatic rollback.

```python
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from fastsqla import Session, Item

@app.post("/heroes", response_model=Item[HeroItem])
async def create_hero(session: Session, new_hero: HeroBase):
    hero = Hero(**new_hero.model_dump())
    session.add(hero)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Hero already exists")
    return {"data": hero}
```

### Rules for IntegrityError

- **Always re-raise as an exception.** Do not catch and silently ignore — the session is broken after an `IntegrityError` and cannot be used for further operations.
- **Use `flush()`, not `commit()`**, so the error is caught within the transaction.
- The `HTTPException` propagates up, triggering the automatic rollback, which is the correct behavior.

---

## open_session()

For code that runs **outside FastAPI endpoints** (background tasks, CLI scripts, scheduled jobs), use `open_session()`:

```python
from fastsqla import open_session

async def sync_external_data():
    async with open_session() as session:
        result = await session.execute(select(Hero))
        heroes = result.scalars().all()
        for hero in heroes:
            hero.synced = True
    # auto-commit on successful exit
```

### Lifecycle

`open_session()` follows the same pattern as the `Session` dependency:

- **Context body succeeds** — session is committed, then closed.
- **Context body raises** — session is rolled back, then closed. The exception is re-raised.
- **Commit itself fails** — session is rolled back, then closed. The commit exception is re-raised.

The third case is important: if everything in your `async with` block succeeds but the `commit()` call at exit fails (e.g., a deferred constraint violation), `open_session()` rolls back and re-raises the commit exception. You do not get a silent failure.

---

## Summary Rules

1. **Use `Session` for endpoints** — type-annotate a parameter and FastAPI injects it. Never instantiate sessions manually in endpoint code.
2. **Never call `session.commit()` in endpoints** — FastSQLA auto-commits on success. Use `session.flush()` to get server-generated values.
3. **Catch `IntegrityError` after `flush()` and re-raise as `HTTPException`** — the session is broken after an integrity error; do not attempt further operations on it.
4. **Use `open_session()` outside endpoints** — background tasks, scripts, and other non-request code should use this async context manager.
5. **Trust the lifecycle** — success commits, exceptions roll back, sessions always close. Do not add manual commit/rollback/close calls.
