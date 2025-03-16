import psycopg
import pytest
import pytest_asyncio
from pydantic import BaseModel

from pnorm import AsyncPostgresClient, QueryContext
from pnorm.hooks.opentelemetry import SpanHook
from tests.fixutres.client_counter import PostgresClientCounter, client  # type: ignore
from tests.utils.telemetry import assert_span

pytest_plugins = ("pytest_asyncio",)


class TestAsyncExecute:
    @pytest_asyncio.fixture(autouse=True)
    async def setup_tests(self, client: PostgresClientCounter):
        async with client.start_session() as session:
            await session.execute(
                "create table if not exists pnorm__async_execute__tests (user_id int unique, name text)"
            )
            await session.execute("delete from pnorm__async_execute__tests")

    @pytest.mark.asyncio
    async def test_execute(self, client: PostgresClientCounter):
        with assert_span(
            {
                "attributes": {
                    "db.system.name": "postgresql",
                    "db.collection.name": "pnorm__async_execute__tests",
                    "db.operation.name": "INSERT",
                    "db.query.summary": "insert into pnorm__async_execute__tests",
                    "db.query.text": "insert into pnorm__async_execute__tests (user_id, name) values(6, 'test')",
                    # "server.address": "localhost",
                    # "server.port": 5434,
                    # "network.peer.address": "localhost",
                    # "network.peer.port": 5434,
                    "db.operation.batch.size": 1,
                    "db.response.returned_rows": 0,
                }
            }
        ):
            await client.execute(
                "insert into pnorm__async_execute__tests (user_id, name) values(6, 'test')",
                query_context=QueryContext(
                    primary_table_name="pnorm__async_execute__tests",
                    operation_name="INSERT",
                    query_summary="insert into pnorm__async_execute__tests",
                ),
                hooks=[SpanHook()],
            )

    @pytest.mark.asyncio
    async def test_execute_many(self, client: PostgresClientCounter):
        with assert_span(
            {
                "attributes": {
                    "db.system.name": "postgresql",
                    "db.collection.name": "pnorm__async_execute__tests",
                    "db.operation.name": "INSERT",
                    "db.query.summary": "insert into pnorm__async_execute__tests",
                    "db.query.text": "insert into pnorm__async_execute__tests (user_id, name) values (%(user_id)s, %(name)s)",
                    # "server.address": "localhost",
                    # "server.port": 5434,
                    # "network.peer.address": "localhost",
                    # "network.peer.port": 5434,
                    "db.operation.batch.size": 2,
                    "db.response.returned_rows": 0,
                    "db.operation.parameter.0.user_id": 20,
                    "db.operation.parameter.0.name": "test-20",
                    "db.operation.parameter.1.user_id": 21,
                    "db.operation.parameter.1.name": "test-21",
                }
            }
        ):
            data = tuple(
                [
                    {"user_id": 20, "name": "test-20"},
                    {"user_id": 21, "name": "test-21"},
                ]
            )

            await client.execute(
                "insert into pnorm__async_execute__tests (user_id, name) values (%(user_id)s, %(name)s)",
                data,
                query_context=QueryContext(
                    primary_table_name="pnorm__async_execute__tests",
                    operation_name="INSERT",
                    query_summary="insert into pnorm__async_execute__tests",
                ),
                hooks=[SpanHook()],
            )

        res = await client.select(
            dict,
            "select * from pnorm__async_execute__tests where user_id in (20, 21) order by user_id asc",
        )

        assert res == data

    @pytest.mark.asyncio
    async def test_execute_many_pydantic(self, client: PostgresClientCounter):
        class Params(BaseModel):
            user_id: int
            name: str

        data = tuple(
            [
                Params(user_id=22, name="test-22"),
                Params(user_id=23, name="test-23"),
            ]
        )

        await client.execute(
            "insert into pnorm__async_execute__tests (user_id, name) values(%(user_id)s, %(name)s)",
            data,
            query_context=QueryContext(
                primary_table_name="pnorm__async_execute__tests",
                operation_name="INSERT",
                query_summary="insert into pnorm__async_execute__tests",
            ),
        )

        res = await client.select(
            Params,
            "select * from pnorm__async_execute__tests where user_id in (22, 23) order by user_id asc",
        )

        assert res == data

    @pytest.mark.asyncio
    async def test_db_timeout(self, client: PostgresClientCounter): ...

    @pytest.mark.asyncio
    async def test_sql_error(self, client: PostgresClientCounter):
        try:
            await client.execute(
                "insert into pnorm__async_execute__tests (user_id, name) values(6, 'test)",
                query_context=QueryContext(
                    primary_table_name="pnorm__async_execute__tests",
                    operation_name="INSERT",
                    query_summary="insert into pnorm__async_execute__tests",
                ),
            )
            raise AssertionError("psycopg.errors.UndefinedFunction not raised")
        except psycopg.errors.SyntaxError:
            ...
        except Exception as e:
            raise AssertionError("Unexpected exception", e)

    @pytest.mark.asyncio
    async def test_type_error(self, client: PostgresClientCounter):
        try:
            await client.execute(
                "insert into pnorm__async_execute__tests (user_id, name) values('abc', 'test')",
                query_context=QueryContext(
                    primary_table_name="pnorm__async_execute__tests",
                    operation_name="INSERT",
                    query_summary="insert into pnorm__async_execute__tests",
                ),
            )
            raise AssertionError("psycopg.errors.InvalidTextRepresentation not raised")
        except psycopg.errors.InvalidTextRepresentation:
            ...
        except Exception as e:
            raise AssertionError("Unexpected exception", e)

    @pytest.mark.asyncio
    async def test_params_dict(self, client: PostgresClientCounter):
        await client.execute(
            "insert into pnorm__async_execute__tests (user_id, name) values(%(user_id)s, %(name)s)",
            {"user_id": 7, "name": "test-7"},
            query_context=QueryContext(
                primary_table_name="pnorm__async_execute__tests",
                operation_name="INSERT",
                query_summary="insert into pnorm__async_execute__tests",
            ),
        )

        value = await self.get_inserted_value(client, 7)
        assert value == {"user_id": 7, "name": "test-7"}

    @pytest.mark.asyncio
    async def test_params_pydantic(self, client: PostgresClientCounter):
        class Params(BaseModel):
            user_id: int
            name: str

        await client.execute(
            "insert into pnorm__async_execute__tests (user_id, name) values(%(user_id)s, %(name)s)",
            Params(user_id=8, name="test-8"),
            query_context=QueryContext(
                primary_table_name="pnorm__async_execute__tests",
                operation_name="INSERT",
                query_summary="insert into pnorm__async_execute__tests",
            ),
        )

        value = await self.get_inserted_value(client, 8)
        assert value == {"user_id": 8, "name": "test-8"}

    async def get_inserted_value(
        self, client: AsyncPostgresClient, user_id: int
    ) -> dict:
        return await client.get(
            dict,
            "select * from pnorm__async_execute__tests where user_id = %(user_id)s",
            {"user_id": user_id},
            query_context=QueryContext(
                primary_table_name="pnorm__async_execute__tests",
                operation_name="SELECT",
                query_summary="get from pnorm__async_execute__tests",
            ),
        )
