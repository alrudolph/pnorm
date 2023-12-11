from __future__ import annotations

from contextlib import contextmanager
from types import TracebackType
from typing import (
    Any,
    Generator,
    Mapping,
    Never,
    Optional,
    Sequence,
    Type,
    TypeVar,
    cast,
)

import psycopg2
from psycopg2._psycopg import connection as Connection
from psycopg2._psycopg import cursor as Cursor
from psycopg2.extras import RealDictCursor, RealDictRow
from pydantic import BaseModel
from rcheck import r

T = TypeVar("T", bound=BaseModel)

QueryParams = list[Any] | dict[str, Any]
ParamType = QueryParams | BaseModel


class PostgresCredentials(BaseModel):
    dbname: str = "postgres"
    user: str
    password: str
    host: str
    port: int = 5432


def connection_not_created() -> Never:
    """This could be from not using a session"""

    raise Exception()


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


class PostgresClient:
    def __init__(
        self,
        credentials: PostgresCredentials,
        auto_create_connection: bool = True,
    ):
        self.credentials = credentials
        self.connection: Connection | None = None
        self.auto_create_connection = auto_create_connection
        self.cursor: SingleCommitCursor | TransactionCursor = SingleCommitCursor(self)

    def is_connected(self) -> bool:
        return self.connection is not None

    def create_connection(self) -> None:
        if self.connection is not None:
            raise Exception("Connection already established")

        self.connection = psycopg2.connect(**self.credentials.model_dump())

    def close_connection(self) -> None:
        if self.connection is None:
            connection_not_created()

        self.cursor.close()
        self.connection.close()
        self.connection = None

    def rollback(self) -> None:
        if self.connection is None:
            connection_not_created()

        self.connection.rollback()

    def start_transaction(self) -> None:
        self.cursor = TransactionCursor(self)

    def end_transaction(self) -> None:
        self.cursor.commit()
        self.cursor = SingleCommitCursor(self)

    def get(
        self,
        return_model: Type[T],
        query: str,
        params: Optional[ParamType] = None,
        combine_into_return_model: bool = False,
    ) -> T | None:
        query = r.check_str("query", query)
        query_params = self._get_params(params)
        close_connection_after = False

        if self.auto_create_connection:
            if self.connection is None:
                self.create_connection()
                close_connection_after = True
        elif self.connection is None:
            connection_not_created()

        with self.cursor(self.connection) as cursor:
            cursor.execute(query, query_params)
            result = cast(RealDictRow, cursor.fetchone())

        if close_connection_after:
            self.close_connection()

        if len(result) == 0:
            return None

        if combine_into_return_model:
            return self._combine_into_return(return_model, params, result)

        return return_model(**result)

    def _combine_into_return(
        self,
        return_model: Type[T],
        params: ParamType | None,
        result: RealDictRow,
    ) -> T:
        if params is not None:
            if isinstance(params, BaseModel):
                result.update(params.model_dump())
            elif isinstance(params, dict):
                result.update(params)
            else:
                raise Exception()

        return return_model(**result)

    def select(
        self,
        return_model: Type[T],
        query: str,
        params: Optional[ParamType] = None,
    ) -> Sequence[T]:
        query = r.check_str("query", query)
        query_params = self._get_params(params)
        close_connection_after = False

        if self.auto_create_connection:
            if self.connection is None:
                self.create_connection()
                close_connection_after = True
        elif self.connection is None:
            connection_not_created()

        with self.cursor(self.connection) as cursor:
            cursor.execute(query, query_params)
            results = cast(list[RealDictRow], cursor.fetchall())

        if close_connection_after:
            self.close_connection()

        if len(results) == 0:
            return tuple()

        return tuple(return_model(**row) for row in results)

    def execute(self, query: str, params: Optional[ParamType] = None) -> None:
        query = r.check_str("query", query)
        query_params = self._get_params(params)
        close_connection_after = False

        if self.auto_create_connection:
            if self.connection is None:
                self.create_connection()
                close_connection_after = True
        elif self.connection is None:
            connection_not_created()

        with self.cursor(self.connection) as cursor:
            cursor.execute(query, query_params)

        if close_connection_after:
            self.close_connection()

    def _get_params(self, params: ParamType | None) -> QueryParams:
        if params is None:
            return []

        if isinstance(params, BaseModel):
            return params.model_dump()

        return params

    @contextmanager
    def transaction(
        self,
    ) -> Generator[SingleCommitCursor | TransactionCursor, None, None]:
        self.start_transaction()

        yield self.cursor

        self.end_transaction()


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


# sql = PostgresClient(
#     PostgresCredentials(
#         host="localhost",
#         port=5436,
#         user="postgres",
#         password="postgres",
#     )
# )


# class Users(BaseModel):
#     username: str
#     email: str


# class Query(BaseModel):
#     color: str


# mek = sql.get(
#     Users,
#     "select username, email from test.users where favorite_color = %(color)s",
#     Query(color="green"),
# )
# print(mek)

# with Session(sql) as session:
#     with session.transaction():
#         mek = session.get(
#             Users,
#             "select username, email from test.users where favorite_color = %(color)s",
#             Query(color="green"),
#         )
#         alex = sql.get(
#             Users,
#             "select username, email from test.users where favorite_color = %s",
#             ("purple",),
#         )

#     print(mek, alex)

#     all_people = session.select(
#         Users,
#         "select username, email from test.users",
#     )

#     print(all_people)
