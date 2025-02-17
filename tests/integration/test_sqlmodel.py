from http import HTTPStatus

from fastapi import HTTPException
from pytest import fixture, mark
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.automap import automap_base


pytestmark = mark.require_sqlmodel


@fixture
def heros_data():
    return [
        ("Superman", "Clark Kent", 30),
        ("Batman", "Bruce Wayne", 35),
        ("Wonder Woman", "Diana Prince", 30),
        ("Iron Man", "Tony Stark", 45),
        ("Spider-Man", "Peter Parker", 25),
        ("Captain America", "Steve Rogers", 100),
        ("Black Widow", "Natasha Romanoff", 35),
        ("Thor", "Thor Odinson", 1500),
        ("Scarlet Witch", "Wanda Maximoff", 30),
        ("Doctor Strange", "Stephen Strange", 40),
        ("The Flash", "Barry Allen", 28),
        ("Green Lantern", "Hal Jordan", 35),
    ]


@fixture(autouse=True)
async def setup_tear_down(engine, heros_data):
    Base = automap_base()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                CREATE TABLE hero (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT NOT NULL UNIQUE,
                    secret_identity TEXT NOT NULL,
                    age             INTEGER NOT NULL
                )
            """)
        )

        await conn.run_sync(Base.prepare)

        Hero = Base.classes.hero

        stmt = insert(Hero).values(
            [
                dict(name=name, secret_identity=secret_identity, age=age)
                for name, secret_identity, age in heros_data
            ]
        )
        await conn.execute(stmt)
        await conn.commit()
        yield
        await conn.execute(text("DROP TABLE hero"))


@fixture
async def app(setup_tear_down, app):
    from fastsqla import Item, Page, Paginate, Session
    from sqlmodel import Field, SQLModel

    class Hero(SQLModel, table=True):
        __table_args__ = {"extend_existing": True}
        id: int | None = Field(default=None, primary_key=True)
        name: str
        secret_identity: str
        age: int

    @app.get("/heroes", response_model=Page[Hero])
    async def get_heroes(paginate: Paginate):
        return await paginate(select(Hero))

    @app.get("/heroes/{hero_id}", response_model=Item[Hero])
    async def get_hero(session: Session, hero_id: int):
        hero = await session.get(Hero, hero_id)
        if hero is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        return {"data": hero}

    @app.post("/heroes", response_model=Item[Hero])
    async def create_hero(session: Session, hero: Hero):
        session.add(hero)
        try:
            await session.flush()
        except IntegrityError:
            raise HTTPException(status_code=HTTPStatus.CONFLICT)
        return {"data": hero}

    return app


@mark.parametrize("offset, page_number, items_count", [[0, 1, 10], [10, 2, 2]])
async def test_pagination(client, heros_data, offset, page_number, items_count):
    res = await client.get("/heroes", params={"offset": offset})
    assert res.status_code == 200, (res.status_code, res.content)

    payload = res.json()
    assert "data" in payload
    data = payload["data"]
    assert len(data) == items_count

    for i, hero in enumerate(data):
        name, secret_identity, age = heros_data[i + offset]
        assert hero["id"]
        assert hero["name"] == name
        assert hero["secret_identity"] == secret_identity
        assert hero["age"] == age

    assert "meta" in payload
    assert payload["meta"]["total_items"] == 12
    assert payload["meta"]["total_pages"] == 2
    assert payload["meta"]["offset"] == offset
    assert payload["meta"]["page_number"] == page_number


async def test_getting_an_entity_with_session_dependency(client, heros_data):
    res = await client.get("/heroes/1")
    assert res.status_code == 200, (res.status_code, res.content)

    payload = res.json()
    assert "data" in payload
    data = payload["data"]

    name, secret_identity, age = heros_data[0]
    assert data["id"] == 1
    assert data["name"] == name
    assert data["secret_identity"] == secret_identity
    assert data["age"] == age


async def test_creating_an_entity_with_session_dependency(client):
    hero = {"name": "Hulk", "secret_identity": "Bruce Banner", "age": 37}
    res = await client.post("/heroes", json=hero)
    assert res.status_code == 200, (res.status_code, res.content)

    data = res.json()["data"]
    assert data["id"] == 13
    assert data["name"] == hero["name"]
    assert data["secret_identity"] == hero["secret_identity"]
    assert data["age"] == hero["age"]


async def test_creating_an_entity_with_conflict(client):
    hero = {"name": "Superman", "secret_identity": "Clark Kent", "age": 30}
    res = await client.post("/heroes", json=hero)
    assert res.status_code == HTTPStatus.CONFLICT, (res.status_code, res.content)
