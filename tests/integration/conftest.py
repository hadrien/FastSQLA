from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pytest import fixture


@fixture
def app(environ):
    from fastsqla import lifespan

    app = FastAPI(lifespan=lifespan)
    return app


@fixture
async def client(app):
    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)  # type: ignore
        async with AsyncClient(transport=transport, base_url="http://app") as client:
            yield client
