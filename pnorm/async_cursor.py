from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncGenerator, Optional, cast

from psycopg import AsyncConnection, AsyncCursor
from psycopg.rows import DictRow

from pnorm.exceptions import connection_not_created

if TYPE_CHECKING:
    from pnorm import AsyncPostgresClient


class TransactionCursor:
    def __init__(self, client: AsyncPostgresClient) -> None:
        self.client = client
        self.cursor: AsyncCursor[DictRow] | None = None

    def _ensure_cursor(self) -> None:
        if self.cursor is not None:
            return

        if self.client.connection is None:
            connection_not_created()

        self.cursor = self.client.connection.cursor()

    @asynccontextmanager
    async def __call__(
        self,
        _: AsyncConnection[DictRow] | None,
    ) -> AsyncGenerator[AsyncCursor[DictRow], None]:
        self._ensure_cursor()

        yield cast(AsyncCursor[DictRow], self.cursor)

    async def commit(self) -> None:
        if self.client.connection is None:
            connection_not_created()

        await self.client.connection.commit()

    def close(self) -> None:
        self.cursor = None


class SingleCommitCursor:
    def __init__(self, client: AsyncPostgresClient) -> None:
        self.client = client

    @asynccontextmanager
    async def __call__(
        self,
        connection: AsyncConnection[DictRow] | None,
    ) -> AsyncGenerator[AsyncCursor[DictRow], None]:
        if connection is None:
            connection_not_created()

        async with connection.cursor() as cursor:
            yield cursor

        await connection.commit()

    async def commit(self) -> None:
        if self.client.connection is None:
            connection_not_created()

        await self.client.connection.commit()

    def close(self) -> None: ...
