import pytest_asyncio

from pnorm import PostgresClient
from tests.fixutres.client_counter import (  # type: ignore
    PostgresClientCounter,
    client,
    get_creds,
)


class TestSyncMethods:
    @pytest_asyncio.fixture(autouse=True)
    async def setup_tests(self, client: PostgresClientCounter):
        async with client.start_session() as session:
            await session.execute(
                "create table if not exists pnorm__sync__tests (user_id int unique, name text)"
            )
            await session.execute(
                "insert into pnorm__sync__tests (user_id, name) values (1, 'test') on conflict do nothing"
            )
            await session.execute(
                "insert into pnorm__sync__tests (user_id, name) values (3, 'test') on conflict do nothing"
            )

    def test_sync_get(self):
        client = PostgresClient(get_creds())
        res = client.get(
            dict,
            "select * from pnorm__sync__tests where user_id = %(user_id)s",
            {"user_id": 1},
        )

        assert res == {"user_id": 1, "name": "test"}

    def test_sync_select(self):
        client = PostgresClient(get_creds())
        res = client.select(
            dict,
            "select * from pnorm__sync__tests where user_id = %(user_id)s",
            {"user_id": 1},
        )

        assert res == ({"user_id": 1, "name": "test"},)

    def test_sync_execute(self):
        client = PostgresClient(get_creds())
        client.execute(
            "update pnorm__sync__tests set name = 'test-123' where user_id = %(user_id)s",
            {"user_id": 3},
        )
        res = client.get(
            dict,
            "select * from pnorm__sync__tests where user_id = %(user_id)s",
            {"user_id": 3},
        )

        assert res == {"user_id": 3, "name": "test-123"}
