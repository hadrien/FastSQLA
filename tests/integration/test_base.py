from fastapi import FastAPI
from pytest import fixture
from sqlalchemy import text

app = FastAPI()


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


async def test_lifespan_reflects_user_table(environ):
    from fastsqla import Base, lifespan

    class User(Base):
        __tablename__ = "user"

    assert not hasattr(User, "id")
    assert not hasattr(User, "email")
    assert not hasattr(User, "name")

    async with lifespan(app):
        assert hasattr(User, "id")
        assert hasattr(User, "email")
        assert hasattr(User, "name")
