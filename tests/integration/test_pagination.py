from typing import Annotated, cast
from fastapi import Depends
from pytest import fixture
from sqlalchemy import MetaData, Table, func, select, text

TOTAL_USERS = 42
STICKY_PER_USER = 5


@fixture(autouse=True)
async def setup_tear_down(engine, faker):
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
        await conn.execute(
            text("""
            CREATE TABLE sticky (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES user (id)
            )
            """)
        )
        metadata = MetaData()
        user = await conn.run_sync(
            lambda sync_conn: Table("user", metadata, autoload_with=sync_conn)
        )
        sticky = await conn.run_sync(
            lambda sync_conn: Table("sticky", metadata, autoload_with=sync_conn)
        )
        await conn.execute(
            user.insert(),
            [
                {"email": faker.email(), "name": faker.name()}
                for _ in range(TOTAL_USERS)
            ],
        )
        await conn.execute(
            sticky.insert(),
            [
                {"user_id": user_id, "body": faker.bs()}
                for user_id in range(1, TOTAL_USERS + 1)
                for _ in range(STICKY_PER_USER)
            ],
        )
        await conn.commit()


@fixture
def app(app):
    from fastsqla import (
        Base,
        Page,
        Paginate,
        PaginateType,
        Session,
        new_pagination,
    )
    from pydantic import BaseModel

    class User(Base):
        __tablename__ = "user"

    class Sticky(Base):
        __tablename__ = "sticky"

    class UserModel(BaseModel):
        id: int
        email: str
        name: str

    class StickyModel(BaseModel):
        id: int
        body: str
        user_id: int
        user_email: str
        user_name: str

    @app.get("/pagination")
    async def list_users(paginate: Paginate[UserModel]) -> Page[UserModel]:
        return await paginate(select(User))

    async def query_count(session: Session) -> int:
        stmt = select(func.count()).select_from(Sticky)
        result = await session.execute(stmt)
        return cast(int, result.scalar())

    CustomResultProcessor = Annotated[
        PaginateType[StickyModel],
        Depends(
            new_pagination(
                query_count_dependency=query_count,
                result_processor=lambda result: iter(result.mappings()),
            )
        ),
    ]

    @app.get("/custom-pagination")
    async def list_stickies(paginate: CustomResultProcessor) -> Page[StickyModel]:
        stmt = select(
            Sticky.id,
            Sticky.body,
            User.id.label("user_id"),
            User.email.label("user_email"),
            User.name.label("user_name"),
        ).join(User)
        return await paginate(stmt)

    return app


async def test_it_with_out_of_the_box_dependency(client):
    res = await client.get("/pagination?offset=40")
    assert res.status_code == 200, (res.status_code, res.content)
    res = res.json()

    data = res["data"]
    assert len(data) == 2

    meta = res["meta"]
    assert meta["page_number"] == 5
    assert meta["total_pages"] == 5
    assert meta["offset"] == 40
    assert meta["total_items"] == TOTAL_USERS


async def test_it_with_custom_result_processor(client):
    res = await client.get("/custom-pagination")
    assert res.status_code == 200, (res.status_code, res.content)
    res = res.json()

    data = res["data"]
    assert len(data) == 10

    meta = res["meta"]
    assert meta["page_number"] == 1
    assert meta["total_pages"] == TOTAL_USERS * STICKY_PER_USER / 10
    assert meta["offset"] == 0
    assert meta["total_items"] == TOTAL_USERS * STICKY_PER_USER
