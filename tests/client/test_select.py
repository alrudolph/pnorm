import psycopg
import pytest
import pytest_asyncio
from pydantic import BaseModel

from pnorm import QueryContext
from pnorm.hooks.opentelemetry import SpanHook
from tests.fixutres.client_counter import PostgresClientCounter, client  # type: ignore
from tests.utils.telemetry import assert_span

pytest_plugins = ("pytest_asyncio",)


class TestAsyncSelect:
    @pytest_asyncio.fixture(autouse=True)
    async def setup_tests(self, client: PostgresClientCounter):
        async with client.start_session() as session:
            await session.execute(
                "create table if not exists pnorm__async_select__tests (user_id int unique, name text)"
            )
            await session.execute("delete from pnorm__async_select__tests")
            await session.execute(
                "insert into pnorm__async_select__tests (user_id, name) values (1, 'test') on conflict do nothing"
            )
            await session.execute(
                "insert into pnorm__async_select__tests (user_id, name) values (3, 'test') on conflict do nothing"
            )

    @pytest.mark.asyncio
    async def test_no_records(self, client: PostgresClientCounter):
        with assert_span(
            {
                "attributes": {
                    "db.system.name": "postgresql",
                    "db.collection.name": "pnorm__async_select__tests",
                    "db.operation.name": "SELECT",
                    "db.query.summary": "get from pnorm__async_select__tests",
                    "db.query.text": "select * from pnorm__async_select__tests where user_id = %(user_id)s",
                    "db.operation.parameter.user_id": 2,
                    # "server.address": "localhost",
                    # "server.port": 5434,
                    # "network.peer.address": "localhost",
                    # "network.peer.port": 5434,
                    "db.operation.batch.size": 1,
                    "db.response.returned_rows": 0,
                }
            }
        ):
            res = await client.select(
                dict,
                "select * from pnorm__async_select__tests where user_id = %(user_id)s",
                {"user_id": 2},
                query_context=QueryContext(
                    primary_table_name="pnorm__async_select__tests",
                    operation_name="SELECT",
                    query_summary="get from pnorm__async_select__tests",
                ),
                hooks=[SpanHook()],
            )

            assert res == tuple()

    @pytest.mark.asyncio
    async def test_one_record(self, client: PostgresClientCounter):
        with assert_span(
            {
                "attributes": {
                    "db.system.name": "postgresql",
                    "db.collection.name": "pnorm__async_select__tests",
                    "db.operation.name": "SELECT",
                    "db.query.summary": "get from pnorm__async_select__tests",
                    "db.query.text": "select * from pnorm__async_select__tests where user_id = %(user_id)s",
                    "db.operation.parameter.user_id": 1,
                    # "server.address": "localhost",
                    # "server.port": 5434,
                    # "network.peer.address": "localhost",
                    # "network.peer.port": 5434,
                    "db.operation.batch.size": 1,
                    "db.response.returned_rows": 1,
                }
            }
        ):
            res = await client.select(
                dict,
                "select * from pnorm__async_select__tests where user_id = %(user_id)s",
                {"user_id": 1},
                query_context=QueryContext(
                    primary_table_name="pnorm__async_select__tests",
                    operation_name="SELECT",
                    query_summary="get from pnorm__async_select__tests",
                ),
                hooks=[SpanHook()],
            )

            assert res == ({"user_id": 1, "name": "test"},)

    @pytest.mark.asyncio
    async def test_multiple_records(self, client: PostgresClientCounter):
        with assert_span(
            {
                "attributes": {
                    "db.system.name": "postgresql",
                    "db.collection.name": "pnorm__async_select__tests",
                    "db.operation.name": "SELECT",
                    "db.query.summary": "get from pnorm__async_select__tests",
                    "db.query.text": "select * from pnorm__async_select__tests where user_id < %(user_id)s",
                    "db.operation.parameter.user_id": 10,
                    # "server.address": "localhost",
                    # "server.port": 5434,
                    # "network.peer.address": "localhost",
                    # "network.peer.port": 5434,
                    "db.operation.batch.size": 1,
                    "db.response.returned_rows": 2,
                }
            }
        ):
            res = await client.select(
                dict,
                "select * from pnorm__async_select__tests where user_id < %(user_id)s",
                {"user_id": 10},
                query_context=QueryContext(
                    primary_table_name="pnorm__async_select__tests",
                    operation_name="SELECT",
                    query_summary="get from pnorm__async_select__tests",
                ),
                hooks=[SpanHook()],
            )

            assert res == (
                {"user_id": 1, "name": "test"},
                {"user_id": 3, "name": "test"},
            )

    @pytest.mark.asyncio
    async def test_dict(self, client: PostgresClientCounter):
        res = await client.select(
            dict,
            "select * from pnorm__async_select__tests where user_id = %(user_id)s",
            {"user_id": 1},
            query_context=QueryContext(
                primary_table_name="pnorm__async_select__tests",
                operation_name="SELECT",
                query_summary="get from pnorm__async_select__tests",
            ),
        )

        assert res == ({"user_id": 1, "name": "test"},)

    @pytest.mark.asyncio
    async def test_pydantic(self, client: PostgresClientCounter):
        class ResponseModel(BaseModel):
            user_id: int
            name: str

        res = await client.select(
            ResponseModel,
            "select * from pnorm__async_select__tests where user_id = %(user_id)s",
            {"user_id": 1},
            query_context=QueryContext(
                primary_table_name="pnorm__async_select__tests",
                operation_name="SELECT",
                query_summary="get from pnorm__async_select__tests",
            ),
        )

        assert res == (ResponseModel(user_id=1, name="test"),)

    @pytest.mark.asyncio
    async def test_db_timeout(self, client: PostgresClientCounter): ...

    @pytest.mark.asyncio
    async def test_sql_error(self, client: PostgresClientCounter):
        try:
            await client.select(
                dict,
                "select * from pnorm__async_select__tests where user_id == %(user_id)s",
                {"user_id": 2},
                query_context=QueryContext(
                    primary_table_name="pnorm__async_select__tests",
                    operation_name="SELECT",
                    query_summary="get from pnorm__async_select__tests",
                ),
            )
            raise AssertionError("psycopg.errors.UndefinedFunction not raised")
        except psycopg.errors.UndefinedFunction:
            ...
        except:
            raise AssertionError("Unexpected exception")

    @pytest.mark.asyncio
    async def test_type_error(self, client: PostgresClientCounter):
        try:
            await client.select(
                dict,
                "select * from pnorm__async_select__tests where user_id = %(user_id)s",
                {"user_id": "hello"},
                query_context=QueryContext(
                    primary_table_name="pnorm__async_select__tests",
                    operation_name="SELECT",
                    query_summary="get from pnorm__async_select__tests",
                ),
            )
            raise AssertionError("psycopg.errors.UndefinedFunction not raised")
        except psycopg.errors.UndefinedFunction:
            ...
        except Exception as e:
            ...

    @pytest.mark.asyncio
    async def test_params_dict(self, client: PostgresClientCounter):
        response = await client.select(
            dict,
            "select * from pnorm__async_select__tests where user_id = %(user_id)s",
            {"user_id": 1},
            query_context=QueryContext(
                primary_table_name="pnorm__async_select__tests",
                operation_name="SELECT",
                query_summary="get from pnorm__async_select__tests",
            ),
        )

        assert response == ({"user_id": 1, "name": "test"},)

    @pytest.mark.asyncio
    async def test_params_pydantic(self, client: PostgresClientCounter):
        class Params(BaseModel):
            user_id: int

        response = await client.select(
            dict,
            "select * from pnorm__async_select__tests where user_id = %(user_id)s",
            Params(user_id=1),
            query_context=QueryContext(
                primary_table_name="pnorm__async_select__tests",
                operation_name="SELECT",
                query_summary="get from pnorm__async_select__tests",
            ),
        )

        assert response == ({"user_id": 1, "name": "test"},)
