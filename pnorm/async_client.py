from __future__ import annotations

from contextlib import asynccontextmanager
from typing import (
    Any,
    AsyncGenerator,
    MutableMapping,
    Optional,
    Sequence,
    cast,
    overload,
)

import psycopg
from psycopg import AsyncConnection
from psycopg.rows import DictRow, TupleRow, dict_row
from psycopg.sql import Composable
from pydantic import BaseModel
from rcheck import r

from pnorm import (
    ConnectionAlreadyEstablishedException,
    MultipleRecordsReturnedException,
    NoRecordsReturnedException,
)
from pnorm.async_cursor import SingleCommitCursor, TransactionCursor
from pnorm.credentials import CredentialsDict, CredentialsProtocol, PostgresCredentials
from pnorm.exceptions import connection_not_created
from pnorm.mapping_utilities import (
    combine_into_return,
    combine_many_into_return,
    get_params,
)
from pnorm.pnorm_types import MappingT, ParamType, T


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
            self.credentials = PostgresCredentials(**credentials)
        else:
            self.credentials = PostgresCredentials(**credentials.as_dict())

        self.connection: AsyncConnection[DictRow] | None = None
        self.auto_create_connection = r.check_bool(
            "auto_create_connection",
            auto_create_connection,
        )
        self.cursor: SingleCommitCursor | TransactionCursor = SingleCommitCursor(self)

    async def set_schema(self, *, schema: str) -> None:
        schema = r.check_str("schema", schema)
        await self.execute(f"select set_config('search_path', '{schema}', false)")

    @overload
    async def get(
        self,
        return_model: type[MappingT],
        query: str | Composable,
        params: Optional[ParamType] = None,
        default: Optional[T] = None,
        combine_into_return_model: bool = False,
    ) -> MappingT: ...

    @overload
    async def get(
        self,
        return_model: type[T],
        query: str | Composable,
        params: Optional[ParamType] = None,
        default: Optional[T] = None,
        combine_into_return_model: bool = False,
    ) -> T: ...

    async def get(
        self,
        return_model: type[T] | type[MappingT],
        query: str | Composable,
        params: Optional[ParamType] = None,
        default: Optional[T] = None,
        combine_into_return_model: bool = False,
    ) -> T | MappingT:
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

        Examples
        --------
        >>>
        >>>
        >>>
        """
        query_params = get_params("Query Params", params)

        async with self._handle_auto_connection():
            async with self.cursor(self.connection) as cursor:
                await cursor.execute(query, query_params)
                query_result = await cursor.fetchmany(2)

        if len(query_result) >= 2:
            msg = f"Received two or more records for query: {await self._query_as_string(query)}"
            raise MultipleRecordsReturnedException(msg)

        single: dict[str, Any] | BaseModel
        if len(query_result) == 0:
            if default is None:
                msg = f"Did not receive any records for query: {await self._query_as_string(query)}"
                raise NoRecordsReturnedException(msg)

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
        query: str | Composable,
        params: Optional[ParamType] = None,
        *,
        default: MappingT,
        combine_into_return_model: bool = False,
    ) -> MappingT: ...

    @overload
    async def find(
        self,
        return_model: type[T],
        query: str | Composable,
        params: Optional[ParamType] = None,
        *,
        default: T,
        combine_into_return_model: bool = False,
    ) -> T: ...

    @overload
    async def find(
        self,
        return_model: type[MappingT],
        query: str | Composable,
        params: Optional[ParamType] = None,
        *,
        default: Optional[MappingT] = None,
        combine_into_return_model: bool = False,
    ) -> MappingT | None: ...

    @overload
    async def find(
        self,
        return_model: type[T],
        query: str | Composable,
        params: Optional[ParamType] = None,
        *,
        default: Optional[T] = None,
        combine_into_return_model: bool = False,
    ) -> T | None: ...

    async def find(
        self,
        return_model: type[T] | type[MappingT],
        query: str | Composable,
        params: Optional[ParamType] = None,
        *,
        default: Optional[T | MappingT] = None,
        combine_into_return_model: bool = False,
    ) -> T | MappingT | None:
        """Return the first result if it exists

        [desc]

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

        Returns
        -------
        find : T of BaseModel | None
            Results of the SQL query marshalled into the return_model Pydantic model
            or None if no rows returned

        Examples
        --------
        >>>
        >>>
        >>>
        """
        query_params = get_params("Query Params", params)
        query_result: DictRow | BaseModel | MappingT | None

        async with self._handle_auto_connection():
            async with self.cursor(self.connection) as cursor:
                await cursor.execute(query, query_params)
                query_result = await cursor.fetchone()

        if query_result is None or len(query_result) == 0:
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
        return_model: type[T],
        query: str | Composable,
        params: Optional[ParamType] = None,
    ) -> tuple[T, ...]: ...

    @overload
    async def select(
        self,
        return_model: type[MappingT],
        query: str | Composable,
        params: Optional[ParamType] = None,
    ) -> tuple[MappingT, ...]: ...

    async def select(
        self,
        return_model: type[T] | type[MappingT],
        query: str | Composable,
        params: Optional[ParamType] = None,
    ) -> tuple[T, ...] | tuple[MappingT, ...]:
        """Return all rows

        Parameters
        ----------
        return_model : type[T of BaseModel]
            Pydantic model to marshall the SQL query results into
        query : str
            SQL query to execute
        params : Optional[Mapping[str, Any] | BaseModel] = None
            Named parameters for the SQL query

        Returns
        -------
        select : tuple[T of BaseModel, ...]
            Results of the SQL query marshalled into the return_model Pydantic model

        Examples
        --------
        >>>
        >>>
        >>>
        """
        query_params = get_params("Query Params", params)

        async with self._handle_auto_connection():
            async with self.cursor(self.connection) as cursor:
                await cursor.execute(query, query_params)
                query_result = await cursor.fetchall()

        if len(query_result) == 0:
            return tuple()

        return combine_many_into_return(return_model, query_result)

    # todo: select using fetchmany for pagination

    async def execute(
        self,
        query: str | Composable,
        params: Optional[ParamType] = None,
    ) -> None:
        """Execute a SQL query

        [desc]

        Parameters
        ----------
        query : str
            SQL query to execute
        params : Optional[Mapping[str, Any] | BaseModel] = None
            Named parameters for the SQL query

        Examples
        --------
        >>>
        >>>
        >>>
        """
        query_params = get_params("Query Params", params)

        async with self._handle_auto_connection():
            async with self.cursor(self.connection) as cursor:
                await cursor.execute(query, query_params)

    # @overload
    # async def execute_values(
    #     self,
    #     query: str | Composable,
    #     values: Optional[
    #         Sequence[BaseModel] | Sequence[MutableMapping[str, Any]]
    #     ] = None,
    #     *,
    #     template: Optional[Sequence[str]] = None,
    #     return_model: type[MappingT],
    # ) -> tuple[MappingT, ...]: ...

    # @overload
    # async def execute_values(
    #     self,
    #     query: str | Composable,
    #     values: Optional[
    #         Sequence[BaseModel] | Sequence[MutableMapping[str, Any]]
    #     ] = None,
    #     *,
    #     template: Optional[Sequence[str]] = None,
    #     return_model: type[T],
    # ) -> tuple[T, ...]: ...

    # @overload
    # async def execute_values(
    #     self,
    #     query: str | Composable,
    #     values: Optional[
    #         Sequence[BaseModel] | Sequence[MutableMapping[str, Any]]
    #     ] = None,
    #     *,
    #     template: Optional[Sequence[str]] = None,
    #     return_model: None = None,
    # ) -> None: ...

    # async def execute_values(
    #     self,
    #     query: str | Composable,
    #     values: Optional[Sequence[BaseModel] | Sequence[MappingT]] = None,
    #     *,
    #     template: Optional[Sequence[str]] = None,
    #     return_model: Optional[type[T] | type[MappingT]] = None,
    # ) -> tuple[T, ...] | tuple[MappingT, ...] | None:
    #     """Execute a sql query with values

    #     Parameters
    #     ----------
    #     query : str
    #         SQL query to execute
    #     values :

    #     template :

    #     Examples
    #     --------
    #     >>>
    #     >>>
    #     >>>
    #     """
    #     data: list[Any] | dict[str, Any] = []

    #     if values is None:
    #         data = get_params("Values", values)
    #     elif isinstance(values, list) and isinstance(values[0], tuple):
    #         data = values
    #     else:
    #         data = [tuple(get_params("Query params", v).values()) for v in values]

    #     async with self._handle_auto_connection():
    #         async with self.cursor(self.connection) as cursor:
    #            await cursor.executemany(cursor, query, data, template)

    #             if return_model is None:
    #                 return

    #             query_result = await cursor.fetchall()

    #     if len(query_result) == 0:
    #         return tuple()

    #     return combine_many_into_return(return_model, query_result)

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

    async def _query_as_string(self, query: str | Composable) -> str:
        if isinstance(query, str):
            return query

        async with self._handle_auto_connection():
            async with self.cursor(self.connection) as cursor:
                return query.as_string(cursor)

    @asynccontextmanager
    async def start_transaction(self) -> AsyncGenerator[AsyncPostgresClient, None]:
        self._create_transaction()

        try:
            yield self
        except:
            await self._rollback()
            raise
        finally:
            await self._end_transaction()

    @asynccontextmanager
    async def start_session(
        self,
        *,
        schema: Optional[str] = None,
    ) -> AsyncGenerator[AsyncPostgresClient, None]:
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
