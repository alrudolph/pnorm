from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Generator, Optional, cast, overload

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from rcheck import r

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
        self._async_client._create_transaction()

        try:
            yield self
        except:
            asyncio.run(self._async_client._rollback())
            raise
        finally:
            asyncio.run(self._async_client._end_transaction())
