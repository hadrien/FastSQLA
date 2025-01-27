from pytest import raises


async def test_it_returns_state(environ):
    from fastsqla import lifespan

    async with lifespan(None) as state:
        assert "fastsqla_engine" in state


async def test_it_binds_an_sqla_engine_to_sessionmaker(environ):
    from fastsqla import SessionFactory, lifespan

    assert SessionFactory.kw["bind"] is None

    async with lifespan(None):
        engine = SessionFactory.kw["bind"]
        assert engine is not None
        assert str(engine.url) == environ["SQLALCHEMY_URL"]

    assert SessionFactory.kw["bind"] is None


async def test_it_fails_on_a_missing_sqlalchemy_url(monkeypatch):
    from fastsqla import lifespan

    monkeypatch.delenv("SQLALCHEMY_URL", raising=False)
    with raises(Exception) as raise_info:
        async with lifespan(None):
            pass

    assert raise_info.value.args[0] == "Missing sqlalchemy_url in environ."


async def test_it_fails_on_not_async_engine(monkeypatch):
    from fastsqla import lifespan

    monkeypatch.setenv("SQLALCHEMY_URL", "sqlite:///:memory:")
    with raises(Exception) as raise_info:
        async with lifespan(None):
            pass

    assert "'pysqlite' is not async." in raise_info.value.args[0]
