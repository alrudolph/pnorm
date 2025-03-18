import pytest_asyncio

from pnorm import PostgresClient
from tests.fixutres.client_counter import (
    PostgresClientCounter,
    client,  # noqa: F401
    get_creds,
)


class TestSyncMethods:
    @pytest_asyncio.fixture(autouse=True)
    async def setup_tests(self, client: PostgresClientCounter) -> None: # noqa: F811
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

    def test_sync_get(self) -> None:
        client = PostgresClient(get_creds()) # noqa: F811
        res = client.get(
            dict,
            "select * from pnorm__sync__tests where user_id = %(user_id)s",
            {"user_id": 1},
        )

        assert res == {"user_id": 1, "name": "test"}

    def test_sync_find(self) -> None:
        client = PostgresClient(get_creds()) # noqa: F811
        res = client.find(
            dict,
            "select * from pnorm__sync__tests where user_id = %(user_id)s",
            {"user_id": 1},
        )

        assert res == {"user_id": 1, "name": "test"}

    def test_sync_select(self) -> None:
        client = PostgresClient(get_creds()) # noqa: F811
        res = client.select(
            dict,
            "select * from pnorm__sync__tests where user_id = %(user_id)s",
            {"user_id": 1},
        )

        assert res == ({"user_id": 1, "name": "test"},)

    def test_sync_execute(self) -> None:
        client = PostgresClient(get_creds()) # noqa: F811
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

    def test_session(self) -> None:
        client = PostgresClient(get_creds()) # noqa: F811

        with client.start_session() as session:
            session.execute(
                "update pnorm__sync__tests set name = 'test-123' where user_id = %(user_id)s",
                {"user_id": 3},
            )
            res = session.get(
                dict,
                "select * from pnorm__sync__tests where user_id = %(user_id)s",
                {"user_id": 3},
            )

            assert res == {"user_id": 3, "name": "test-123"}

    def test_transaction(self) -> None:
        client = PostgresClient(get_creds()) # noqa: F811

        with client.start_session() as session:
            with session.start_transaction() as tx:
                tx.execute(
                    "update pnorm__sync__tests set name = 'test-123' where user_id = %(user_id)s",
                    {"user_id": 3},
                )
                res = tx.get(
                    dict,
                    "select * from pnorm__sync__tests where user_id = %(user_id)s",
                    {"user_id": 3},
                )

                assert res == {"user_id": 3, "name": "test-123"}
