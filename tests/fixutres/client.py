import os
from typing import TypedDict

from dotenv import load_dotenv
from pytest import fixture

from pnorm import PostgresClient, PostgresCredentials


class ConnectionCount(TypedDict):
    create_connections_count: int
    close_connections_count: int


class TransactionsCount(TypedDict):
    create_connections_count: int
    close_connections_count: int


class PostgresClientCounter(PostgresClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.create_connections: list[ConnectionCount] = []
        self.close_connections: list[ConnectionCount] = []

    def _create_connection(self) -> None:
        self.create_connections.append(
            {
                "create_connections_count": len(self.create_connections) + 1,
                "close_connections_count": len(self.close_connections),
            }
        )
        return super()._create_connection()

    def _end_connection(self) -> None:
        self.close_connections.append(
            {
                "create_connections_count": len(self.create_connections),
                "close_connections_count": len(self.close_connections) + 1,
            }
        )
        return super()._end_connection()

    def check_connections(self) -> int:
        number_of_connections = len(self.create_connections)

        assert len(self.create_connections) == len(self.close_connections)

        assert (
            len(self.create_connections) == 0
            or self.create_connections[0]["create_connections_count"] == 1
        )
        assert len(self.create_connections) == 0 or self.create_connections[-1][
            "create_connections_count"
        ] == len(self.create_connections)

        for conn in self.create_connections:
            assert (
                conn["create_connections_count"] - 1 == conn["close_connections_count"]
            )

        assert (
            len(self.close_connections) == 0
            or self.close_connections[0]["close_connections_count"] == 1
        )
        assert len(self.close_connections) == 0 or self.close_connections[-1][
            "close_connections_count"
        ] == len(self.close_connections)

        for conn in self.close_connections:
            assert conn["close_connections_count"] == conn["create_connections_count"]

        return number_of_connections


@fixture
def client() -> PostgresClient:
    load_dotenv()
    credentials = PostgresCredentials(
        # dbname=os.environ["TEST_DB_NAME"],
        dbname="postgres",
        user=os.environ["TEST_DB_USER"],
        password=os.environ["TEST_DB_PASSWORD"],
        host=os.environ["TEST_DB_HOST"],
        port=int(os.environ["TEST_DB_PORT"]),
    )
    return PostgresClientCounter(credentials)
