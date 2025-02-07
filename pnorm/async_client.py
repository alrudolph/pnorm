from __future__ import annotations

import asyncio
from collections.abc import Mapping, MutableMapping, Sequence
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional, cast, overload

import psycopg
from opentelemetry import trace
from opentelemetry.trace import Span
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from pydantic import BaseModel
from rcheck import r

from .async_cursor import SingleCommitCursor, TransactionCursor
from .credentials import CredentialsDict, CredentialsProtocol, PostgresCredentials
from .exceptions import (
    ConnectionAlreadyEstablishedException,
    MultipleRecordsReturnedException,
    NoRecordsReturnedException,
    connection_not_created,
)
from .mapping_utilities import (
    combine_into_return,
    combine_many_into_return,
    get_param_maybe_list,
    get_params,
)
from .pnorm_types import (
    BaseModelMappingT,
    BaseModelT,
    MappingT,
    ParamType,
    Query,
    QueryContext,
)


class AsyncPostgresClient:
    def __init__(
        self,
        credentials: CredentialsProtocol | CredentialsDict | PostgresCredentials,
        auto_create_connection: bool = True,
    ) -> None:
        # Want to keep as the PostgresCredentials class for SecretStr
        if isinstance(credentials, PostgresCredentials):
            self.credentials = credentials
        elif isinstance(credentials, dict):
            self.credentials = PostgresCredentials.model_validate(credentials)
        else:
            self.credentials = PostgresCredentials.model_validate(credentials.as_dict())

        self.connection: AsyncConnection[DictRow] | None = None
        self.auto_create_connection = r.check_bool(
            "auto_create_connection",
            auto_create_connection,
        )
        self.tracer = trace.get_tracer("pnorm.async_client")
        self.cursor: SingleCommitCursor | TransactionCursor = SingleCommitCursor(
            self, self.tracer
        )
        self.user_set_schema: str | None = None

    async def set_schema(self, *, schema: str) -> None:
        schema = r.check_str("schema", schema)
        self.user_set_schema = schema
        await self.execute(f"select set_config('search_path', '{schema}', false)")

    @overload
    async def get(
        self,
        return_model: type[MappingT],
        query: Query,
        params: Optional[ParamType] = None,
        default: Optional[MappingT] = None,
        combine_into_return_model: bool = False,
        *,
        timeout: Optional[float] = None,
        query_context: Optional[QueryContext] = None,
    ) -> MappingT: ...

    @overload
    async def get(
        self,
        return_model: type[BaseModelT],
        query: Query,
        params: Optional[ParamType] = None,
        default: Optional[BaseModelT] = None,
        combine_into_return_model: bool = False,
        *,
        timeout: Optional[float] = None,
        query_context: Optional[QueryContext] = None,
    ) -> BaseModelT: ...

    async def get(
        self,
        return_model: type[BaseModelMappingT],
        query: Query,
        params: Optional[ParamType] = None,
        default: Optional[BaseModelMappingT] = None,
        combine_into_return_model: bool = False,
        *,
        timeout: Optional[float] = None,
        query_context: Optional[QueryContext] = None,
    ) -> BaseModelMappingT:
        """Always returns exactly one record or raises an exception

        This method should be used by default when expecting exactly one row to
        be returned from the SQL query, such as when selecting an object by its
        unique id.

        Parameters
        ----------
        return_model : type[T of BaseModel]
            Pydantic model to marshall the SQL query results into
        query : str
            SQL query to execute
        params : Optional[Mapping[str, Any] | BaseModel] = None
            Named parameters for the SQL query
        default: T of BaseModel | None = None
            The default value to return if no rows are returned
        combine_into_return_model : bool = False
            Whether to combine the params mapping or pydantic model with the
            result of the query into the return_model
        timeout : Optional[float] = None
            Amount of time in seconds to wait for the query to complete. Default to no timeout
        query_context : Optional[QueryContext] = None
            Query metadata for telemetry purposes

        Raises
        ------
        NoRecordsReturnedException
            When the query did not result in returning a record and no default
            was given
        MultipleRecordsReturnedException
            When the query returns at least two records

        Returns
        -------
        get : T of BaseModel
            Results of the SQL query marshalled into the return_model Pydantic model
        """
        query_as_string = await self._query_as_string(query)
        query_params = get_params("Query Params", params)

        async with self._handle_auto_connection():
            async with self.cursor(self.connection) as cursor:
                with self.tracer.start_as_current_span(query_as_string) as span:
                    self._set_span_attributes(
                        span,
                        query_as_string,
                        query_params,
                        query_context,
                    )

                    try:
                        async with asyncio.timeout(timeout):
                            await cursor.execute(query, query_params)
                            query_result = await cursor.fetchmany(2)
                            span.set_attribute(
                                "db.response.returned_rows",
                                len(query_result),
                            )
                    except asyncio.TimeoutError as e:
                        span.set_attribute("error.type", "timeout")
                        span.record_exception(e)

                        if self.connection is not None:
                            self.connection.cancel()

                        raise
                    # except psycopg.OperationalError as e:
                    #     # https://www.psycopg.org/docs/errors.html
                    #     span.record_exception(e)
                    #     span.set_attribute("db.response.status_code", str(e.pgcode))

        if len(query_result) >= 2:
            msg = f"Received two or more records for query: {query_as_string}"
            raise MultipleRecordsReturnedException(msg)

        single: MutableMapping[str, Any]
        if len(query_result) == 0:
            if default is None:
                msg = f"Did not receive any records for query: {query_as_string}"
                raise NoRecordsReturnedException(msg)

            if isinstance(default, BaseModel):
                single = default.model_dump()
            else:
                single = default
        else:
            single = query_result[0]

        return combine_into_return(
            return_model,
            single,
            params if combine_into_return_model else None,
        )

    @overload
    async def find(
        self,
        return_model: type[MappingT],
        query: Query,
        params: Optional[ParamType] = None,
        *,
        default: MappingT,
        combine_into_return_model: bool = False,
        timeout: Optional[float] = None,
        query_context: Optional[QueryContext] = None,
    ) -> MappingT: ...

    @overload
    async def find(
        self,
        return_model: type[BaseModelT],
        query: Query,
        params: Optional[ParamType] = None,
        *,
        default: BaseModelT,
        combine_into_return_model: bool = False,
        timeout: Optional[float] = None,
        query_context: Optional[QueryContext] = None,
    ) -> BaseModelT: ...

    @overload
    async def find(
        self,
        return_model: type[MappingT],
        query: Query,
        params: Optional[ParamType] = None,
        *,
        default: Optional[MappingT] = None,
        combine_into_return_model: bool = False,
        timeout: Optional[float] = None,
        query_context: Optional[QueryContext] = None,
    ) -> MappingT | None: ...

    @overload
    async def find(
        self,
        return_model: type[BaseModelT],
        query: Query,
        params: Optional[ParamType] = None,
        *,
        default: Optional[BaseModelT] = None,
        combine_into_return_model: bool = False,
        timeout: Optional[float] = None,
        query_context: Optional[QueryContext] = None,
    ) -> BaseModelT | None: ...

    async def find(
        self,
        return_model: type[BaseModelT] | type[MappingT],
        query: Query,
        params: Optional[ParamType] = None,
        *,
        default: Optional[BaseModelT | MappingT] = None,
        combine_into_return_model: bool = False,
        timeout: Optional[float] = None,
        query_context: Optional[QueryContext] = None,
    ) -> BaseModelT | MappingT | None:
        """Return the first result if it exists

        Useful if you're not sure if the record exists, otherwise use `get`

        Parameters
        ----------
        return_model : type[T of BaseModel]
            Pydantic model to marshall the SQL query results into
        query : str
            SQL query to execute
        params : Optional[Mapping[str, Any] | BaseModel] = None
            Named parameters for the SQL query
        default: T of BaseModel | None = None
            The default value to return if no rows are returned
        combine_into_return_model : bool = False
            Whether to combine the params mapping or pydantic model with the
            result of the query into the return_model
        timeout : Optional[float] = None
            Amount of time in seconds to wait for the query to complete. Default to no timeout
        query_context : Optional[QueryContext] = None
            Query metadata for telemetry purposes

        Returns
        -------
        find : T of BaseModel | None
            Results of the SQL query marshalled into the return_model Pydantic model
            or None if no rows returned
        """
        query_as_string = await self._query_as_string(query)

        query_params = get_params("Query Params", params)
        query_result: DictRow | BaseModel | MappingT | None

        async with self._handle_auto_connection():
            async with self.cursor(self.connection) as cursor:
                with self.tracer.start_as_current_span(query_as_string) as span:
                    self._set_span_attributes(
                        span,
                        query_as_string,
                        query_params,
                        query_context,
                    )

                    try:
                        async with asyncio.timeout(timeout):
                            await cursor.execute(query, query_params)
                            query_result = await cursor.fetchone()

                            span.set_attribute(
                                "db.response.returned_rows",
                                1 if query_result is not None else 0,
                            )
                    except asyncio.TimeoutError as e:
                        span.set_attribute("error.type", "timeout")
                        span.record_exception(e)

                        if self.connection is not None:
                            self.connection.cancel()

                        raise

        if query_result is None:
            if default is None:
                return None

            query_result = default

        return combine_into_return(
            return_model,
            query_result,
            params if combine_into_return_model else None,
        )

    @overload
    async def select(
        self,
        return_model: type[BaseModelT],
        query: Query,
        params: Optional[ParamType] = None,
        *,
        timeout: Optional[float] = None,
        query_context: Optional[QueryContext] = None,
    ) -> tuple[BaseModelT, ...]: ...

    @overload
    async def select(
        self,
        return_model: type[MappingT],
        query: Query,
        params: Optional[ParamType] = None,
        *,
        timeout: Optional[float] = None,
        query_context: Optional[QueryContext] = None,
    ) -> tuple[MappingT, ...]: ...

    async def select(
        self,
        return_model: type[BaseModelT] | type[MappingT],
        query: Query,
        params: Optional[ParamType] = None,
        *,
        timeout: Optional[float] = None,
        query_context: Optional[QueryContext] = None,
    ) -> tuple[BaseModelT, ...] | tuple[MappingT, ...]:
        """Return all rows

        Parameters
        ----------
        return_model : type[T of BaseModel]
            Pydantic model to marshall the SQL query results into
        query : str
            SQL query to execute
        params : Optional[Mapping[str, Any] | BaseModel] = None
            Named parameters for the SQL query
        timeout : Optional[float] = None
            Amount of time in seconds to wait for the query to complete. Default to no timeout
        query_context : Optional[QueryContext] = None
            Query metadata for telemetry purposes

        Returns
        -------
        select : tuple[T of BaseModel, ...]
            Results of the SQL query marshalled into the return_model Pydantic model
        """
        query_as_string = await self._query_as_string(query)

        query_params = get_params("Query Params", params)

        async with self._handle_auto_connection():
            async with self.cursor(self.connection) as cursor:
                with self.tracer.start_as_current_span(query_as_string) as span:
                    self._set_span_attributes(
                        span,
                        query_as_string,
                        query_params,
                        query_context,
                    )

                    try:
                        async with asyncio.timeout(timeout):
                            await cursor.execute(query, query_params)
                            query_result = await cursor.fetchall()
                            span.set_attribute(
                                "db.response.returned_rows",
                                len(query_result),
                            )
                    except asyncio.TimeoutError as e:
                        span.set_attribute("error.type", "timeout")
                        span.record_exception(e)

                        if self.connection is not None:
                            self.connection.cancel()

                        raise

        if len(query_result) == 0:
            return tuple()

        return combine_many_into_return(return_model, query_result)

    async def execute(
        self,
        query: Query,
        params: Optional[ParamType | Sequence[ParamType]] = None,
        *,
        timeout: Optional[float] = None,
        query_context: Optional[QueryContext] = None,
    ) -> None:
        """Execute a SQL query

        Parameters
        ----------
        query : str
            SQL query to execute
        params : Optional[Mapping[str, Any] | BaseModel] = None
            Named parameters for the SQL query
        timeout : Optional[float] = None
            Amount of time in seconds to wait for the query to complete. Default to no timeout
        query_context : Optional[QueryContext] = None
            Query metadata for telemetry purposes
        """
        query_as_string = await self._query_as_string(query)

        query_params = get_param_maybe_list("Query Params", params)

        async with self._handle_auto_connection():
            async with self.cursor(self.connection) as cursor:
                with self.tracer.start_as_current_span(query_as_string) as span:
                    self._set_span_attributes(
                        span,
                        query_as_string,
                        query_params,
                        query_context,
                    )

                    try:
                        async with asyncio.timeout(timeout):
                            if isinstance(query_params, Sequence):
                                span.set_attribute(
                                    "db.operation.batch.size", len(query_params)
                                )
                                await cursor.executemany(query, query_params)
                            else:
                                await cursor.execute(query, query_params)

                            span.set_attribute("db.response.returned_rows", 0)
                    except asyncio.TimeoutError as e:
                        span.set_attribute("error.type", "timeout")
                        span.record_exception(e)

                        if self.connection is not None:
                            self.connection.cancel()

                        raise

    @asynccontextmanager
    async def start_session(
        self,
        *,
        schema: Optional[str] = None,
    ) -> AsyncGenerator[AsyncPostgresClient, None]:
        """

        Examples
        --------
        async with db.start_session() as session:
            await session.get(...)
        """
        original_auto_create_connection = self.auto_create_connection
        self.auto_create_connection = False
        close_connection_after_use = False

        if self.connection is None:
            await self._create_connection()
            close_connection_after_use = True

        if schema is not None:
            await self.set_schema(schema=schema)

        try:
            yield self
        except:
            await self._rollback()
            raise
        finally:
            if self.connection is not None and close_connection_after_use:
                await self._end_connection()

            self.auto_create_connection = original_auto_create_connection

    @asynccontextmanager
    async def start_transaction(self) -> AsyncGenerator[AsyncPostgresClient, None]:
        """

        Examples
        --------
        async with session.start_transaction() as tx:
            await tx.get(...)
        """
        self._create_transaction()

        try:
            yield self
        except:
            await self._rollback()
            raise
        finally:
            await self._end_transaction()

    async def _create_connection(self) -> None:
        if self.connection is not None:
            raise ConnectionAlreadyEstablishedException()

        self.connection = cast(
            AsyncConnection[DictRow],
            await psycopg.AsyncConnection.connect(
                **self.credentials.as_dict(),
                row_factory=dict_row,
            ),
        )

    async def _end_connection(self) -> None:
        if self.connection is None:
            connection_not_created()

        self.cursor.close()
        await self.connection.close()
        self.connection = None

    async def _rollback(self) -> None:
        if self.connection is None:
            connection_not_created()

        await self.connection.rollback()

    def _create_transaction(self) -> None:
        self.cursor = TransactionCursor(self, self.tracer)

    async def _end_transaction(self) -> None:
        await self.cursor.commit()
        self.cursor = SingleCommitCursor(self, self.tracer)

    @asynccontextmanager
    async def _handle_auto_connection(self) -> AsyncGenerator[None, None]:
        close_connection_after_use = False

        if self.auto_create_connection:
            if self.connection is None:
                await self._create_connection()
                close_connection_after_use = True
        elif self.connection is None:
            connection_not_created()

        try:
            yield
        finally:
            if close_connection_after_use:
                await self._end_connection()

    async def _query_as_string(self, query: Query) -> str:
        if isinstance(query, str):
            return query

        if isinstance(query, bytes):
            return query.decode("utf-8")

        async with self._handle_auto_connection():
            async with self.cursor(self.connection) as cursor:
                return query.as_string(cursor)

    # TODO: instead of dict[str, Any] maybe dict[str, str | int | float | bool ... ] ? datetime, uuid, dict, list ...
    def _set_span_attributes(
        self,
        span: Span,
        query_as_string: str,
        query_params: Optional[dict[str, Any] | Sequence[dict[str, Any]]] = None,
        query_context: Optional[QueryContext] = None,
    ) -> None:
        span.set_attribute("db.system.name", "postgresql")

        if self.user_set_schema is not None:
            span.set_attribute("db.namespace", self.user_set_schema)

        if query_context is not None:
            if query_context.primary_table_name is not None:
                span.set_attribute(
                    "db.collection.name",
                    query_context.primary_table_name,
                )

            if query_context.operation_name is not None:
                span.set_attribute("db.operation.name", query_context.operation_name)

            if query_context.query_summary is not None:
                span.set_attribute("db.query.summary", query_context.query_summary)

        span.set_attribute(
            "db.query.text",
            query_as_string,
        )  # TODO: remove repeated whitespace, newlines etc...
        span.set_attribute("server.address", self.credentials.host)
        span.set_attribute("server.port", self.credentials.port)
        span.set_attribute("network.peer.address", self.credentials.host)
        span.set_attribute("network.peer.port", self.credentials.port)
        span.set_attribute("db.operation.batch.size", 1)

        if query_params is None:
            return

        if isinstance(query_params, Mapping):
            for key, value in query_params.items():
                # TODO: secret values?
                # either have pydantic models with SecretStr
                # or in context have a list of values to replace with **
                if isinstance(value, str | bytes | int | float | bool):
                    span.set_attribute(f"db.operation.parameter.{key}", value)
                else:
                    span.set_attribute(f"db.operation.parameter.{key}", str(value))

            return

        # TODO: this could be bad for inserting data... maybe have a way to turn off in execute
        # or have a way to specify only certain parameters are being included
        for i, params in enumerate(query_params):
            for key, value in params.items():
                # TODO: secret values?
                # either have pydantic models with SecretStr
                # or in context have a list of values to replace with **
                if isinstance(value, str | bytes | int | float | bool):
                    span.set_attribute(f"db.operation.parameter.{i}.{key}", value)
                else:
                    span.set_attribute(f"db.operation.parameter.{i}.{key}", str(value))
