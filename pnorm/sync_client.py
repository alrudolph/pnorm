from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Generator, Optional, cast, overload

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from .async_client import AsyncPostgresClient
from .async_cursor import SingleCommitCursor, TransactionCursor
from .credentials import CredentialsDict, CredentialsProtocol, PostgresCredentials
from .hooks.base import BaseHook
from .pnorm_types import (
    BaseModelMappingT,
    BaseModelT,
    MappingT,
    ParamType,
    Query,
    QueryContext,
)


class PostgresClient:

    def __init__(
        self,
        credentials: CredentialsProtocol | CredentialsDict | PostgresCredentials,
        auto_create_connection: bool = True,
        hooks: Optional[list[BaseHook]] = None,
    ) -> None:
        """Sync Postgres Client

        Parameters
        ----------
        credentials : CredentialsProtocol | CredentialsDict | PostgresCredentials
            Credentials to connect to the Postgres database
        auto_create_connection : bool = True
            Whether to automatically create a connection when executing a query
        hooks: Optional[list[BaseHook]] = None
            List of hooks to run before and after the query. See pnorm.hooks.opentelemetry for examples
        """
        self._async_client = AsyncPostgresClient(
            credentials,
            auto_create_connection,
            hooks,
        )
        self.connection: AsyncConnection[DictRow] | None = None
        self.cursor: SingleCommitCursor | TransactionCursor = SingleCommitCursor(
            self._async_client,
        )
        self.user_set_schema: str | None = None

    def set_schema(self, *, schema: str) -> None:
        """Set the schema for the current session"""
        return asyncio.run(self._async_client.set_schema(schema=schema))

    @overload
    def get(
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
    def get(
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

    def get(
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
        return asyncio.run(
            self._async_client.get(
                return_model,
                query,
                params,
                default,
                combine_into_return_model,
                timeout=timeout,
                query_context=query_context,
                hooks=hooks,
            )
        )

    @overload
    def find(
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
    def find(
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
    def find(
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
    def find(
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

    def find(
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
        res = asyncio.run(
            self._async_client.find(
                return_model,
                query,
                params,
                default=default,
                combine_into_return_model=combine_into_return_model,
                timeout=timeout,
                query_context=query_context,
                hooks=hooks,
            )
        )

        return cast(BaseModelT | MappingT | None, res)

    @overload
    def select(
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
    def select(
        self,
        return_model: type[MappingT],
        query: Query,
        params: Optional[ParamType] = None,
        *,
        timeout: Optional[float] = None,
        query_context: Optional[QueryContext] = None,
        hooks: Optional[list[BaseHook]] = None,
    ) -> tuple[MappingT, ...]: ...

    def select(
        self,
        return_model: type[BaseModelT] | type[MappingT],
        query: Query,
        params: Optional[ParamType] = None,
        *,
        timeout: Optional[float] = None,
        query_context: Optional[QueryContext] = None,
        hooks: Optional[list[BaseHook]] = None,
    ) -> tuple[BaseModelT, ...] | tuple[MappingT, ...]:
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
        res = asyncio.run(
            self._async_client.select(
                return_model,
                query,
                params,
                timeout=timeout,
                query_context=query_context,
                hooks=hooks,
            )
        )

        return cast(tuple[BaseModelT, ...] | tuple[MappingT, ...], res)

    def execute(
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
        return asyncio.run(
            self._async_client.execute(
                query,
                params,
                timeout=timeout,
                query_context=query_context,
                hooks=hooks,
            )
        )

    @contextmanager
    def start_session(
        self,
        *,
        schema: Optional[str] = None,
    ) -> Generator[PostgresClient, None, None]:
        """Start database session

        Parameters
        ----------
        schema : Optional[str] = None
            Schema to set for the session

        Examples
        --------
        with db.start_session() as session:
            session.get(...)
        """
        close_connection_after_use = False

        if self.connection is None:
            asyncio.run(self._async_client._create_connection())
            close_connection_after_use = True

        if schema is not None:
            self.set_schema(schema=schema)

        try:
            yield self
        except:
            asyncio.run(self._async_client._rollback())
            raise
        finally:
            if self.connection is not None and close_connection_after_use:
                asyncio.run(self._async_client._end_connection())

    @contextmanager
    def start_transaction(self) -> Generator[PostgresClient, None, None]:
        """Start a transaction

        Examples
        --------
        with session.start_transaction() as tx:
            tx.get(...)
        """
        self._async_client._create_transaction()

        try:
            yield self
        except:
            asyncio.run(self._async_client._rollback())
            raise
        finally:
            asyncio.run(self._async_client._end_transaction())
