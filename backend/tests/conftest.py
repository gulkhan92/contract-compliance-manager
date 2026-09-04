"""Repo-wide test fixtures.

`db_session` requires `DATABASE_URL` to point at an already-migrated
database (run `alembic upgrade head` first — see README). Each test runs
inside an outer transaction that is rolled back afterwards, so tests never
leave data behind regardless of how many times a fixture or test body calls
`session.commit()` (`join_transaction_mode="create_savepoint"` turns those
into savepoints nested inside the outer, rolled-back transaction).
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.db.session import engine
from app.main import app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_connection() -> AsyncGenerator[AsyncConnection]:
    async with engine.connect() as connection:
        await connection.begin()
        yield connection
        await connection.rollback()


@pytest.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncGenerator[AsyncSession]:
    async with AsyncSession(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        yield session
