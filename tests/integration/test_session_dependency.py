from http import HTTPStatus

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from pytest import fixture
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column


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
    from fastapi_async_sqla import Base, Item, Session

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

    @app.get("/session-dependency")
    async def get_session(session: Session):
        res = await session.execute(select(text("'OK'")))
        return {"data": res.scalar()}

    @app.post("/users", response_model=Item[UserModel], status_code=HTTPStatus.CREATED)
    async def create_user(user_in: UserIn, session: Session):
        user = User(**user_in.model_dump())
        user_in.model_dump
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:
            raise HTTPException(status_code=400)
        return {"data": user}

    return app


async def test_it(client):
    res = await client.get("/session-dependency")
    assert res.status_code == HTTPStatus.OK, (res.status_code, res.content)
    assert res.json() == {"data": "OK"}


async def test_session_is_commited(client, session):
    payload = {"email": "bob@bob.com", "name": "Bobby"}
    res = await client.post("/users", json=payload)

    assert res.status_code == HTTPStatus.CREATED, (res.status_code, res.content)

    all_users = (await session.execute(text("SELECT * FROM user"))).mappings().all()
    assert all_users == [{"id": 1, **payload}]


@fixture
async def bob_exists(session):
    await session.execute(
        text("INSERT INTO user (email, name) VALUES ('bob@bob.com', 'Bobby')")
    )
    await session.commit()
    yield


async def test_with_an_integrity_error(client, bob_exists):
    res = await client.post("/users", json={"email": "bob@bob.com", "name": "Bobby"})
    assert res.status_code == HTTPStatus.BAD_REQUEST, (res.status_code, res.content)
