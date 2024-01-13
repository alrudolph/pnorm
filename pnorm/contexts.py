from __future__ import annotations

from contextlib import contextmanager
from types import TracebackType
from typing import TYPE_CHECKING, Generator, Optional, Type

if TYPE_CHECKING:
    from pnorm import PostgresClient


# todo: rm
class Session:
    def __init__(self, client: PostgresClient):
        self.client = client
        self.original_auto_create_connection = self.client.auto_create_connection
        self.client.auto_create_connection = False

    def __enter__(self) -> PostgresClient:
        if self.client.connection is None:
            self.client.create_connection()

        return self.client

    def __exit__(
        self,
        exc_type: Optional[Type[Exception]],
        exc_value: Optional[Exception],
        exc_tb: Optional[TracebackType],
    ):
        if self.client.connection is not None:
            if exc_type is not None:
                self.client.rollback()

            self.client.close_connection()

        self.client.auto_create_connection = self.original_auto_create_connection


@contextmanager
def create_session(client: PostgresClient) -> Generator[None, None, None]:
    original_auto_create_connection = client.auto_create_connection
    client.auto_create_connection = False
    close_connection_after_use = False

    if client.connection is None:
        client.create_connection()
        close_connection_after_use = True

    try:
        yield
    except:
        client.rollback()
        raise
    finally:
        if client.connection is not None and close_connection_after_use:
            client.close_connection()

        client.auto_create_connection = original_auto_create_connection


@contextmanager
def create_transaction(client: PostgresClient) -> Generator[None, None, None]:
    client.start_transaction()

    try:
        yield
    except:
        client.rollback()
        raise
    finally:
        client.end_transaction()
