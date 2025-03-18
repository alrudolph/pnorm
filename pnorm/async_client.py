from __future__ import annotations

import asyncio
from collections.abc import MutableMapping, Sequence
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Literal, Optional, cast, overload

import psycopg
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
from .hooks.base import BaseHook
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
        hooks: Optional[list[BaseHook]] = None,
    ) -> None:
        """Async Postgres Client

        Parameters
        ----------
        credentials : CredentialsProtocol | CredentialsDict | PostgresCredentials
            Credentials to connect to the Postgres database
        auto_create_connection : bool = True
            Whether to automatically create a connection when executing a query
        hooks: Optional[list[BaseHook]] = None
            List of hooks to run before and after the query. See pnorm.hooks.opentelemetry for examples
        """
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
        self.cursor: SingleCommitCursor | TransactionCursor = SingleCommitCursor(
            self,
        )
        self.user_set_schema: str | None = None
        self.default_hooks = hooks

    async def set_schema(self, *, schema: str) -> None:
        """Set the schema for the current session"""
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
        hooks: Optional[list[BaseHook]] = None,
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
        hooks: Optional[list[BaseHook]] = None,
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
        hooks: Optional[list[BaseHook]] = None,
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
        hooks: Optional[list[BaseHook]] = None
            List of hooks to run before and after the query. See pnorm.hooks.opentelemetry for examples

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
        hooks = self._get_hooks(hooks)

        async with self._handle_auto_connection():
            async with self.cursor(self.connection) as cursor:
                _apply_pre_hooks(hooks, query_as_string, query_params, query_context)

                try:
                    async with asyncio.timeout(timeout):
                        await cursor.execute(query, query_params)
                        query_result = await cursor.fetchmany(2)
                except asyncio.TimeoutError as e:
                    _apply_exception_hooks(hooks, e)

                    if self.connection is not None:
                        self.connection.cancel()

                    raise

        if len(query_result) >= 2:
            msg = f"Received two or more records for query: {query_as_string}"
            _apply_post_hooks(hooks, "error", len(query_result))
            raise MultipleRecordsReturnedException(msg)

        single: MutableMapping[str, Any]
        if len(query_result) == 0:
            if default is None:
                msg = f"Did not receive any records for query: {query_as_string}"
                _apply_post_hooks(hooks, "error", 0)
                raise NoRecordsReturnedException(msg)

            _apply_post_hooks(hooks, "success", 0)
            if isinstance(default, BaseModel):
                single = default.model_dump()
            else:
                single = default
        else:
            single = query_result[0]
            _apply_post_hooks(hooks, "success", 1)

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
        hooks: Optional[list[BaseHook]] = None,
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
        hooks: Optional[list[BaseHook]] = None,
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
        hooks: Optional[list[BaseHook]] = None,
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
        hooks: Optional[list[BaseHook]] = None,
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
        hooks: Optional[list[BaseHook]] = None,
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
        hooks: Optional[list[BaseHook]] = None
            List of hooks to run before and after the query. See pnorm.hooks.opentelemetry for examples

        Returns
        -------
        find : T of BaseModel | None
            Results of the SQL query marshalled into the return_model Pydantic model
            or None if no rows returned
        """
        query_as_string = await self._query_as_string(query)

        query_params = get_params("Query Params", params)
        query_result: DictRow | BaseModel | MappingT | None
        hooks = self._get_hooks(hooks)

        async with self._handle_auto_connection():
            async with self.cursor(self.connection) as cursor:
                _apply_pre_hooks(hooks, query_as_string, query_params, query_context)

                try:
                    async with asyncio.timeout(timeout):
                        await cursor.execute(query, query_params)
                        query_result = await cursor.fetchone()
                except asyncio.TimeoutError as e:
                    _apply_exception_hooks(hooks, e)

                    if self.connection is not None:
                        self.connection.cancel()

                    raise

        if query_result is None:
            _apply_post_hooks(hooks, "success", 0)

            if default is None:
                return None

            query_result = default

        _apply_post_hooks(hooks, "success", 1)
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
        hooks: Optional[list[BaseHook]] = None,
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
        hooks: Optional[list[BaseHook]] = None,
    ) -> tuple[MappingT, ...]: ...

    async def select(
        self,
        return_model: type[BaseModelT] | type[MappingT],
        query: Query,
        params: Optional[ParamType] = None,
        *,
        timeout: Optional[float] = None,
        query_context: Optional[QueryContext] = None,
        hooks: Optional[list[BaseHook]] = None,
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
        hooks: Optional[list[BaseHook]] = None
            List of hooks to run before and after the query. See pnorm.hooks.opentelemetry for examples

        Note
        ----
        This method cannot be used for inserting multiple rows and then returning all of the
        inserted rows.

        Returns
        -------
        select : tuple[T of BaseModel, ...]
            Results of the SQL query marshalled into the return_model Pydantic model
        """
        query_as_string = await self._query_as_string(query)

        query_params = get_params("Query Params", params)
        hooks = self._get_hooks(hooks)

        async with self._handle_auto_connection():
            async with self.cursor(self.connection) as cursor:
                _apply_pre_hooks(hooks, query_as_string, query_params, query_context)

                try:
                    async with asyncio.timeout(timeout):
                        await cursor.execute(query, query_params)
                        query_result = await cursor.fetchall()
                except asyncio.TimeoutError as e:
                    _apply_exception_hooks(hooks, e)

                    if self.connection is not None:
                        self.connection.cancel()

                    raise

        _apply_post_hooks(hooks, "success", len(query_result))

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
        hooks: Optional[list[BaseHook]] = None,
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
        hooks: Optional[list[BaseHook]] = None
            List of hooks to run before and after the query. See pnorm.hooks.opentelemetry for examples
        """
        query_as_string = await self._query_as_string(query)

        query_params = get_param_maybe_list("Query Params", params)
        hooks = self._get_hooks(hooks)

        async with self._handle_auto_connection():
            async with self.cursor(self.connection) as cursor:
                _apply_pre_hooks(hooks, query_as_string, query_params, query_context)

                try:
                    async with asyncio.timeout(timeout):
                        if isinstance(query_params, Sequence):
                            await cursor.executemany(query, query_params)
                        else:
                            await cursor.execute(query, query_params)

                        _apply_post_hooks(
                            hooks,
                            "success",
                            rows_returned=0,
                            batch_size=(
                                len(query_params)
                                if isinstance(query_params, Sequence)
                                else 1
                            ),
                        )
                except asyncio.TimeoutError as e:
                    _apply_exception_hooks(hooks, e)

                    if self.connection is not None:
                        self.connection.cancel()

                    raise

    @asynccontextmanager
    async def start_session(
        self,
        *,
        schema: Optional[str] = None,
    ) -> AsyncGenerator[AsyncPostgresClient, None]:
        """Start database session

        Parameters
        ----------
        schema : Optional[str] = None
            Schema to set for the session

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
        """Start a transaction

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
        self.cursor = TransactionCursor(self)

    async def _end_transaction(self) -> None:
        await self.cursor.commit()
        self.cursor = SingleCommitCursor(self)

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

    def _get_hooks(self, hooks: Optional[list[BaseHook]]) -> list[BaseHook]:
        match self.default_hooks, hooks:
            case None, None:
                return []
            case None, _:
                # Mypy doesn't like this without the cast, but it should be correct...
                return cast(list[BaseHook], hooks)
            case _, None:
                return cast(list[BaseHook], self.default_hooks)
            case _, _:
                df = cast(list[BaseHook], self.default_hooks)
                h = cast(list[BaseHook], hooks)
                return df + h

        raise ValueError("UNREACHABLE: Invalid hooks supplied")


def _apply_pre_hooks(
    hooks: Optional[list[BaseHook]],
    query: str,
    query_params: Optional[dict[str, Any] | Sequence[dict[str, Any]]],
    query_context: Optional[QueryContext],
) -> None:
    if hooks is None:
        return

    for hook in hooks:
        hook.pre_query(query, query_params, query_context)


def _apply_post_hooks(
    hooks: Optional[list[BaseHook]],
    result_type: Literal["success", "error"],
    rows_returned: int,
    batch_size: int = 1,
) -> None:
    if hooks is None:
        return

    for hook in hooks:
        hook.post_query(result_type, rows_returned, batch_size)


def _apply_exception_hooks(
    hooks: Optional[list[BaseHook]],
    exception: Exception,
) -> None:
    if hooks is None:
        return

    for hook in hooks:
        hook.on_exception(exception)
