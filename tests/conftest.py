from unittest.mock import patch

from pytest import fixture
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


@fixture
def environ(tmp_path):
    values = {
        "PYTHONASYNCIODEBUG": "1",
        "SQLALCHEMY_URL": f"sqlite+aiosqlite:///{tmp_path}/test.db",
    }

    with patch.dict("os.environ", values=values, clear=True):
        yield values


@fixture
async def engine(environ):
    engine = create_async_engine(environ["SQLALCHEMY_URL"])
    yield engine
    await engine.dispose()


@fixture
async def session(engine):
    async with engine.connect() as conn:
        yield AsyncSession(bind=conn)


@fixture(autouse=True)
def tear_down():
    from sqlalchemy.orm import clear_mappers

    from fastapi_async_sqla import Base

    yield

    Base.metadata.clear()
    clear_mappers()
