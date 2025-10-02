from unittest.mock import patch

from pytest import fixture, skip
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "require_sqlmodel: skip test when sqlmodel is not installed."
    )


@fixture
def sqlalchemy_url(tmp_path):
    return f"sqlite+aiosqlite:///{tmp_path}/test.db"


@fixture
def environ(sqlalchemy_url):
    values = {"PYTHONASYNCIODEBUG": "1", "SQLALCHEMY_URL": sqlalchemy_url}

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

    from fastsqla import Base

    yield

    Base.metadata.clear()
    clear_mappers()


try:
    import sqlmodel  # noqa
except ImportError:
    is_sqlmodel_installed = False
else:
    is_sqlmodel_installed = True


@fixture(autouse=True)
def check_sqlmodel(request):
    """Skip test marked with mark.require_sqlmodel if sqlmodel is not installed."""
    marker = request.node.get_closest_marker("require_sqlmodel")
    if marker and not is_sqlmodel_installed:
        skip(f"{request.node.nodeid} requires sqlmodel which is not installed.")
