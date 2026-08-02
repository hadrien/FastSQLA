from unittest.mock import AsyncMock, patch

from pytest import fixture, raises
from sqlalchemy import text


class SimulatedError(RuntimeError):
    pass


@fixture
def tablename(request):
    return request.node.name


@fixture(autouse=True)
async def setup_tear_down(engine, tablename):
    from fastsqla import SessionFactory

    async with engine.connect() as conn:
        await conn.execute(text(f"create table {tablename} (data text unique)"))

    SessionFactory.configure(bind=engine)
    yield
    SessionFactory.configure(bind=None)


async def test_it_commits_on_success(engine, tablename):
    from fastsqla import open_session

    async with open_session() as session:
        await session.execute(text(f"insert into {tablename} values ('OK')"))

    async with engine.connect() as conn:
        res = await conn.execute(text(f"select * from {tablename}"))

    assert res.scalar() == "OK"


async def test_it_re_raises_when_committing_fails():
    from fastsqla import open_session

    with patch("fastsqla.SessionFactory") as SessionFactory:
        session = AsyncMock()
        session.commit.side_effect = SimulatedError("Simulating a failure.")
        SessionFactory.return_value = session
        with raises(SimulatedError, match=r"Simulating a failure\."):
            async with open_session():
                pass


async def test_it_rollback_on_failure(engine, tablename):
    from fastsqla import open_session

    with raises(SimulatedError, match=r"Simulating a failure\."):
        async with open_session() as session:
            await session.execute(text(f"insert into {tablename} values ('OK')"))
            raise SimulatedError("Simulating a failure.")

    async with engine.connect() as conn:
        res = await conn.execute(text(f"select * from {tablename}"))

    assert res.fetchall() == []
