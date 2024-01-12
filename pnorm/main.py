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
    overload
)

import psycopg2
import psycopg2.extras as extras
from psycopg2._psycopg import connection as Connection
from psycopg2._psycopg import cursor as Cursor
from psycopg2.extras import RealDictCursor, RealDictRow
from pydantic import AliasChoices, BaseModel, Field
from rcheck import r

T = TypeVar("T", bound=BaseModel)

QueryParams = Mapping[str, Any]
ParamType = QueryParams | BaseModel


class NoRecordsReturnedException(Exception):
    ...


class MultipleRecordsReturnedException(Exception):
    ...


class PostgresCredentials(BaseModel):
    dbname: str = Field(
        default="postgres",
        validation_alias=AliasChoices("dbname", "database"),
    )
    user: str
    password: str
    host: str
    port: int = 5432

    class Config:
        extra = "forbid"


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
        default: T | None = None,
        combine_into_return_model: bool = False,
    ) -> T:
        """Always returns exactly one record or raises an exception
        
        This method should be used by default when expecting exactly one row to
        be returned from the SQL query, such as when selecting an object by its
        unique id.
        
        Parameters
        ----------
        return_model : Type[T of BaseModel]
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
        query = r.check_str("query", query)
        query_params = self._get_params("Query Params", params)
        
        with self._handle_auto_connection():
            with self.cursor(self.connection) as cursor:
                cursor.execute(query, query_params)
                get = cast(list[RealDictRow], cursor.fetchmany(2))

        if len(get) >= 2:
            raise MultipleRecordsReturnedException(f"Received two or more records for query: {query}")

        if len(get) == 0:
            if default is None:
                raise NoRecordsReturnedException(f"Did not receive any records for query: {query}")
            
            single = default
        else:
            single = get[0]
        
        return self._combine_into_return(
            return_model,
            single,
            params if combine_into_return_model else None,
        )
            
    @overload
    def find(
        self,
        return_model: Type[T],
        query: str,
        params: Optional[ParamType] = None,
        default: None = None,
        combine_into_return_model: bool = False,
    ) -> T | None:
        ...
            
    @overload
    def find(
        self,
        return_model: Type[T],
        query: str,
        params: Optional[ParamType] = None,
        default: T = ...,
        combine_into_return_model: bool = False,
    ) -> T:
        ...
        
    def find(
        self,
        return_model: Type[T],
        query: str,
        params: Optional[ParamType] = None, # todo: or BaseModel?
        default: T | None = None,
        combine_into_return_model: bool = False,
    ) -> T | None:
        """Return the first result or None
        """
        query = r.check_str("query", query)
        query_params = self._get_params("Query Params", params)
        
        with self._handle_auto_connection():
            with self.cursor(self.connection) as cursor:
                cursor.execute(query, query_params)
                result = cast(RealDictRow | None, cursor.fetchone())

        if result is None or len(result) == 0:
            if default is None:
                return None
            
            result = default

        return self._combine_into_return(
            return_model,
            result,
            params if combine_into_return_model else None,
        )

    def select(
        self,
        return_model: Type[T],
        query: str,
        params: Optional[ParamType] = None,
    ) -> Sequence[T]:
        """Return all rows
        """
        query = r.check_str("query", query)
        query_params = self._get_params("Query Params", params)

        with self._handle_auto_connection():
            with self.cursor(self.connection) as cursor:
                cursor.execute(query, query_params)
                results = cast(list[RealDictRow], cursor.fetchall())

        if len(results) == 0:
            return tuple()

        return tuple(self._combine_into_return(return_model, row) for row in results)
    
    # todo: select using fetchmany for pagination
    
    def execute(
        self,
        query: str,
        params: Optional[ParamType] = None,
    ) -> None:
        """Execute a SQL query
        """
        query = r.check_str("query", query)
        query_params = self._get_params("Query Params", params)

        with self._handle_auto_connection():
            with self.cursor(self.connection) as cursor:
                cursor.execute(query, query_params)

    def execute_values(
        self,
        query: str,
        values: Sequence[BaseModel] | None = None,
    ) -> None:
        """Execute a sql query with values
        """
        # todo could this just be a part of execute
        # todo does this method also need params for the query?
        query = r.check_str("query", query)

        if values is None:
            data = self._get_params(values)
        elif isinstance(values[0], tuple):
            data = values
        else:
            data = [
                tuple(self._get_params("Query params", v).values()) 
                for v in values
            ]
            
        with self._handle_auto_connection():
            with self.cursor(self.connection) as cursor:
                extras.execute_values(cursor, query, data)

    def _combine_into_return(
        self,
        return_model: Type[T],
        result: dict[str, Any] | BaseModel,
        params: ParamType | None = None,
    ) -> T:
        result_dict = self._get_params("Query Result", result)
    
        if params is not None:
            result_dict.update(self._get_params("Query Params", params))
    
        try:
            return return_model(**result_dict)
        except Exception as e:
            # todo: give helpful message 
            raise e
    
    def _get_params(self, name: str, params: ParamType | None) -> dict[str, Any]:
        if params is None:
            return {}

        if isinstance(params, BaseModel):
            params = params.model_dump()

        return cast(dict[str, Any], r.check_mapping(name, params, keys_of=str))

    @contextmanager
    def _handle_auto_connection(self) -> Generator[None, None, None]:
        close_connection_after_use = False
        
        if self.auto_create_connection:
            if self.connection is None:
                self.create_connection()
                close_connection_after_use = True
        elif self.connection is None:
            connection_not_created()
            
        yield

        if close_connection_after_use:
            self.close_connection()


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
def create_session(client: PostgresClient) -> Generator[PostgresClient, None, None]:
    original_auto_create_connection = client.auto_create_connection
    client.auto_create_connection = False
    close_connection_after_use = False
    
    if client.connection is None:
        client.create_connection()
        close_connection_after_use = True
        
    try:
        yield client
    except:
        client.rollback()
        raise
    finally:
        if client.connection is not None and close_connection_after_use:
            client.close_connection()
            
        client.auto_create_connection = original_auto_create_connection
    

@contextmanager
def create_transaction(
    client: PostgresClient,
) -> Generator[SingleCommitCursor | TransactionCursor, None, None]:
    client.start_transaction()

    try:
        yield client.cursor
    except:
        client.rollback()
        raise
    finally:
        client.end_transaction()
