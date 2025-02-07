import pytest
import pytest_asyncio

from tests.fixutres.client_counter import client  # type: ignore
from tests.fixutres.client_counter import PostgresClientCounter, get_client

pytest_plugins = ("pytest_asyncio",)


class TestSessions:
    @pytest_asyncio.fixture(autouse=True)
    async def setup_tests(self, client: PostgresClientCounter):
        async with client.start_session() as session:
            await session.execute(
                "create table if not exists pnorm__sessions__tests (user_id int unique, name text)"
            )
            await session.execute(
                "insert into pnorm__sessions__tests (user_id, name) values (1, 'test') on conflict do nothing"
            )
            await session.execute(
                "insert into pnorm__sessions__tests (user_id, name) values (3, 'test') on conflict do nothing"
            )

    @pytest.mark.asyncio
    async def test_only_one_connection_execute(self):
        client = get_client()

        async with client.start_session() as session:
            await session.execute(
                "select * from pnorm__sessions__tests where user_id = %(user_id)s",
                {"user_id": 1},
            )

        assert client.check_connections() == 1

    @pytest.mark.asyncio
    async def test_multiple_statements(self):
        client = get_client()

        async with client.start_session() as session:
            await session.find(
                dict,
                "select * from pnorm__sessions__tests where user_id = %(user_id)s",
                {"user_id": 1},
            )
            await session.find(
                dict,
                "select * from pnorm__sessions__tests where user_id = %(user_id)s",
                {"user_id": 2},
            )
            await session.find(
                dict,
                "select * from pnorm__sessions__tests where user_id = %(user_id)s",
                {"user_id": 3},
            )

        assert client.check_connections() == 1
