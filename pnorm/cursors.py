from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Generator, cast

from psycopg2._psycopg import connection as Connection
from psycopg2._psycopg import cursor as Cursor
from psycopg2.extras import RealDictCursor

from pnorm import connection_not_created

if TYPE_CHECKING:
    from pnorm import PostgresClient


class TransactionCursor:
    def __init__(self, client: PostgresClient):
        self.client = client
        self.cursor: Cursor | None = None

    def _ensure_cursor(self) -> None:
        if self.cursor is not None:
            return

        if self.client.connection is None:
            connection_not_created()

        self.cursor = self.client.connection.cursor(cursor_factory=RealDictCursor)

    @contextmanager
    def __call__(self, _: Connection | None) -> Generator[Cursor, None, None]:
        self._ensure_cursor()

        yield cast(Cursor, self.cursor)

    def commit(self) -> None:
        if self.client.connection is None:
            connection_not_created()

        self.client.connection.commit()

    def close(self) -> None:
        self.cursor = None


class SingleCommitCursor:
    def __init__(self, client: PostgresClient):
        self.client = client

    @contextmanager
    def __call__(self, connection: Connection | None) -> Generator[Cursor, None, None]:
        if connection is None:
            connection_not_created()

        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor

            connection.commit()

    def commit(self) -> None:
        if self.client.connection is None:
            connection_not_created()

        self.client.connection.commit()

    def close(self) -> None:
        ...
