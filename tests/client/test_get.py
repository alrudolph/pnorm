from typing import Any

import psycopg
import pytest
import pytest_asyncio
from pydantic import BaseModel

from pnorm import (
    MultipleRecordsReturnedException,
    NoRecordsReturnedException,
    QueryContext,
)
from tests.fixutres.client_counter import PostgresClientCounter, client  # type: ignore
from tests.utils.telemetry import assert_span

pytest_plugins = ("pytest_asyncio",)


class TestAsyncGet:
    @pytest_asyncio.fixture(autouse=True)
    async def setup_tests(self, client: PostgresClientCounter):
        async with client.start_session() as session:
            await session.execute(
                "create table if not exists pnorm__async_get__tests (user_id int unique, name text)"
            )
            await session.execute(
                "insert into pnorm__async_get__tests (user_id, name) values (1, 'test') on conflict do nothing"
            )
            await session.execute(
                "insert into pnorm__async_get__tests (user_id, name) values (3, 'test') on conflict do nothing"
            )

    @pytest.mark.asyncio
    async def test_no_records(self, client: PostgresClientCounter):
        with assert_span(
            {
                "attributes": {
                    "db.system.name": "postgresql",
                    "db.collection.name": "pnorm__async_get__tests",
                    "db.operation.name": "SELECT",
                    "db.query.summary": "get from pnorm__async_get__tests",
                    "db.query.text": "select * from pnorm__async_get__tests where user_id = %(user_id)s",
                    "db.operation.parameter.user_id": 2,
                    "server.address": "localhost",
                    "server.port": 5434,
                    "network.peer.address": "localhost",
                    "network.peer.port": 5434,
                    "db.operation.batch.size": 1,
                    "db.response.returned_rows": 0,
                }
            }
        ):
            try:
                await client.get(
                    dict,
                    "select * from pnorm__async_get__tests where user_id = %(user_id)s",
                    {"user_id": 2},
                    query_context=QueryContext(
                        primary_table_name="pnorm__async_get__tests",
                        operation_name="SELECT",
                        query_summary="get from pnorm__async_get__tests",
                    ),
                )
                raise AssertionError("NoRecordsReturnedException not raised")
            except NoRecordsReturnedException:
                ...
            except Exception as e:
                raise AssertionError(f"Unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_one_record(self, client: PostgresClientCounter):
        with assert_span(
            {
                "attributes": {
                    "db.system.name": "postgresql",
                    "db.collection.name": "pnorm__async_get__tests",
                    "db.operation.name": "SELECT",
                    "db.query.summary": "get from pnorm__async_get__tests",
                    "db.query.text": "select * from pnorm__async_get__tests where user_id = %(user_id)s",
                    "db.operation.parameter.user_id": 1,
                    "server.address": "localhost",
                    "server.port": 5434,
                    "network.peer.address": "localhost",
                    "network.peer.port": 5434,
                    "db.operation.batch.size": 1,
                    "db.response.returned_rows": 1,
                }
            }
        ):
            await client.get(
                dict,
                "select * from pnorm__async_get__tests where user_id = %(user_id)s",
                {"user_id": 1},
                query_context=QueryContext(
                    primary_table_name="pnorm__async_get__tests",
                    operation_name="SELECT",
                    query_summary="get from pnorm__async_get__tests",
                ),
            )

    @pytest.mark.asyncio
    async def test_multiple_records(self, client: PostgresClientCounter):
        with assert_span(
            {
                "attributes": {
                    "db.system.name": "postgresql",
                    "db.collection.name": "pnorm__async_get__tests",
                    "db.operation.name": "SELECT",
                    "db.query.summary": "get from pnorm__async_get__tests",
                    "db.query.text": "select * from pnorm__async_get__tests where user_id < %(user_id)s",
                    "db.operation.parameter.user_id": 5,
                    "server.address": "localhost",
                    "server.port": 5434,
                    "network.peer.address": "localhost",
                    "network.peer.port": 5434,
                    "db.operation.batch.size": 1,
                    "db.response.returned_rows": 2,
                }
            }
        ):
            try:
                await client.get(
                    dict,
                    "select * from pnorm__async_get__tests where user_id < %(user_id)s",
                    {"user_id": 5},
                    query_context=QueryContext(
                        primary_table_name="pnorm__async_get__tests",
                        operation_name="SELECT",
                        query_summary="get from pnorm__async_get__tests",
                    ),
                )
                raise AssertionError("MultipleRecordsReturnedException not raised")
            except MultipleRecordsReturnedException:
                ...
            except Exception as e:
                raise AssertionError(f"Unexpected exception: {e}")

    @pytest.mark.asyncio
    async def test_dict(self, client: PostgresClientCounter):
        response = await client.get(
            dict,
            "select * from pnorm__async_get__tests where user_id = %(user_id)s",
            {"user_id": 1},
            query_context=QueryContext(
                primary_table_name="pnorm__async_get__tests",
                operation_name="SELECT",
                query_summary="get from pnorm__async_get__tests",
            ),
        )

        assert response == {"user_id": 1, "name": "test"}

    @pytest.mark.asyncio
    async def test_pydantic(self, client: PostgresClientCounter):
        class ResponseModel(BaseModel):
            user_id: int
            name: str

        response = await client.get(
            ResponseModel,
            "select * from pnorm__async_get__tests where user_id = %(user_id)s",
            {"user_id": 1},
            query_context=QueryContext(
                primary_table_name="pnorm__async_get__tests",
                operation_name="SELECT",
                query_summary="get from pnorm__async_get__tests",
            ),
        )

        assert response == ResponseModel(user_id=1, name="test")

    @pytest.mark.asyncio
    async def test_combine_into_return_model(self, client: PostgresClientCounter):
        class ResponseModel(BaseModel):
            user_id: int
            name: str

        response = await client.get(
            ResponseModel,
            "select name from pnorm__async_get__tests where user_id = %(user_id)s",
            {"user_id": 1},
            combine_into_return_model=True,
            query_context=QueryContext(
                primary_table_name="pnorm__async_get__tests",
                operation_name="SELECT",
                query_summary="get from pnorm__async_get__tests",
            ),
        )

        assert response == ResponseModel(user_id=1, name="test")

    @pytest.mark.asyncio
    async def test_no_records_default(self, client: PostgresClientCounter):
        response = await client.get(
            dict,
            "select * from pnorm__async_get__tests where user_id = %(user_id)s",
            {"user_id": 2},
            default={"user_id": 2, "name": "default"},
            query_context=QueryContext(
                primary_table_name="pnorm__async_get__tests",
                operation_name="SELECT",
                query_summary="get from pnorm__async_get__tests",
            ),
        )

        assert response == {"user_id": 2, "name": "default"}

    @pytest.mark.asyncio
    async def test_db_timeout(self, client: PostgresClientCounter): ...

    @pytest.mark.asyncio
    async def test_sql_error(self, client: PostgresClientCounter):
        try:
            await client.get(
                dict,
                "select * from pnorm__async_get__tests where user_id == %(user_id)s",
                {"user_id": 2},
                query_context=QueryContext(
                    primary_table_name="pnorm__async_get__tests",
                    operation_name="SELECT",
                    query_summary="get from pnorm__async_get__tests",
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
            await client.get(
                dict,
                "select * from pnorm__async_get__tests where user_id = %(user_id)s",
                {"user_id": "hello"},
                query_context=QueryContext(
                    primary_table_name="pnorm__async_get__tests",
                    operation_name="SELECT",
                    query_summary="get from pnorm__async_get__tests",
                ),
            )
            raise AssertionError("psycopg.errors.UndefinedFunction not raised")
        except psycopg.errors.UndefinedFunction:
            ...
        except Exception as e:
            ...

    @pytest.mark.asyncio
    async def test_params_dict(self, client: PostgresClientCounter):
        response = await client.get(
            dict,
            "select * from pnorm__async_get__tests where user_id = %(user_id)s",
            {"user_id": 1},
            query_context=QueryContext(
                primary_table_name="pnorm__async_get__tests",
                operation_name="SELECT",
                query_summary="get from pnorm__async_get__tests",
            ),
        )

        assert response == {"user_id": 1, "name": "test"}

    @pytest.mark.asyncio
    async def test_params_pydantic(self, client: PostgresClientCounter):
        class Params(BaseModel):
            user_id: int

        response = await client.get(
            dict,
            "select * from pnorm__async_get__tests where user_id = %(user_id)s",
            Params(user_id=1),
            query_context=QueryContext(
                primary_table_name="pnorm__async_get__tests",
                operation_name="SELECT",
                query_summary="get from pnorm__async_get__tests",
            ),
        )

        assert response == {"user_id": 1, "name": "test"}
