import psycopg
import pytest
import pytest_asyncio

from tests.fixutres.client_counter import client  # type: ignore
from tests.fixutres.client_counter import PostgresClientCounter, get_client

pytest_plugins = ("pytest_asyncio",)


class TestTransactions:
    @pytest_asyncio.fixture(autouse=True)
    async def setup_tests(self, client: PostgresClientCounter) -> None:
        async with client.start_session() as session:
            await session.execute(
                "create table if not exists pnorm__transactions__tests (user_id int unique, name text)"
            )
            await session.execute(
                "insert into pnorm__transactions__tests (user_id, name) values (1, 'test') on conflict do nothing"
            )
            await session.execute(
                "insert into pnorm__transactions__tests (user_id, name) values (3, 'test') on conflict do nothing"
            )
            await session.execute(
                "delete from pnorm__transactions__tests where user_id > 3"
            )

    @pytest.mark.asyncio
    async def test_transaction(self) -> None:
        client = get_client()

        async with client.start_session() as session:
            async with session.start_transaction() as tx:
                await tx.execute(
                    "insert into pnorm__transactions__tests (user_id, name) values (4, 'test')",
                )
                await tx.execute(
                    "insert into pnorm__transactions__tests (user_id, name) values (5, '123')",
                )

            res = await session.select(
                dict,
                "select * from pnorm__transactions__tests where user_id in (4, 5) order by user_id asc",
            )

            assert res == (
                {"user_id": 4, "name": "test"},
                {"user_id": 5, "name": "123"},
            )

        assert client.check_connections() == 1

    @pytest.mark.asyncio
    async def test_transaction_failure_is_rolled_back(self) -> None:
        client = get_client()

        async with client.start_session() as session:
            try:
                async with session.start_transaction() as tx:
                    await tx.execute(
                        "insert into pnorm__transactions__tests (user_id, name) values (6, 'test')",
                    )
                    await tx.execute(
                        "insert into pnorm__transactions__tests (user_id, name) values ('fake-value', 123)",
                    )

                raise Exception("This should not be reached")
            except psycopg.errors.InvalidTextRepresentation:
                ...

            res = await session.find(
                dict,
                "select * from pnorm__transactions__tests where user_id = %(user_id)s",
                {"user_id": 6},
            )

            assert res is None

        assert client.check_connections() == 1
