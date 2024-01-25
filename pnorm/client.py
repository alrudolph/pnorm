from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Optional, Sequence, Type, cast, overload

import psycopg2
import psycopg2.extras as extras
from psycopg2._psycopg import connection as Connection
from psycopg2.extras import RealDictRow
from pydantic import BaseModel
from rcheck import r

from pnorm import (
    ConnectionAlreadyEstablishedException,
    MultipleRecordsReturnedException,
    NoRecordsReturnedException,
    ParamType,
    PostgresCredentials,
    T,
    connection_not_created,
)
from pnorm.cursors import SingleCommitCursor, TransactionCursor
from pnorm.mapping_utilities import combine_into_return, get_params


class PostgresClient:
    def __init__(
        self,
        credentials: PostgresCredentials,
        auto_create_connection: bool = True,  # todo: rather default to false
    ):
        self.credentials = credentials
        self.connection: Connection | None = None
        self.auto_create_connection = auto_create_connection
        self.cursor: SingleCommitCursor | TransactionCursor = SingleCommitCursor(self)

    def get(
        self,
        return_model: Type[T],
        query: str,
        params: Optional[ParamType] = None,
        default: Optional[T] = None,
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
        query_params = get_params("Query Params", params)

        with self._handle_auto_connection():
            with self.cursor(self.connection) as cursor:
                cursor.execute(query, query_params)
                query_result = cast(list[RealDictRow], cursor.fetchmany(2))

        if len(query_result) >= 2:
            msg = f"Received two or more records for query: {query}"
            raise MultipleRecordsReturnedException(msg)

        if len(query_result) == 0:
            if default is None:
                msg = f"Did not receive any records for query: {query}"
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
        params: Optional[ParamType] = None,  # todo: or BaseModel?
        default: Optional[T] = None,
        combine_into_return_model: bool = False,
    ) -> T | None:
        """Return the first result if it exists

        [desc]

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
        query = r.check_str("query", query)
        query_params = get_params("Query Params", params)

        with self._handle_auto_connection():
            with self.cursor(self.connection) as cursor:
                cursor.execute(query, query_params)
                query_result = cast(RealDictRow | None, cursor.fetchone())

        if query_result is None or len(query_result) == 0:
            if default is None:
                return None

            query_result = default

        return combine_into_return(
            return_model,
            query_result,
            params if combine_into_return_model else None,
        )

    def select(
        self,
        return_model: Type[T],
        query: str,
        params: Optional[ParamType] = None,
    ) -> tuple[T, ...]:
        """Return all rows

        [desc]

        Parameters
        ----------
        return_model : Type[T of BaseModel]
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
        query = r.check_str("query", query)
        query_params = get_params("Query Params", params)

        with self._handle_auto_connection():
            with self.cursor(self.connection) as cursor:
                cursor.execute(query, query_params)
                query_result = cast(list[RealDictRow], cursor.fetchall())

        if len(query_result) == 0:
            return tuple()

        return tuple(combine_into_return(return_model, row) for row in query_result)

    # todo: select using fetchmany for pagination

    def execute(
        self,
        query: str,
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
        query = r.check_str("query", query)
        query_params = get_params("Query Params", params)

        with self._handle_auto_connection():
            with self.cursor(self.connection) as cursor:
                cursor.execute(query, query_params)

    def execute_values(
        self,
        query: str,
        values: Optional[Sequence[BaseModel]] = None,
        template: Optional[Sequence[str]] = None,
    ) -> None:
        """Execute a sql query with values

        [desc]

        Parameters
        ----------
        query : str
            SQL query to execute
        values :

        template :


        Examples
        --------
        >>>
        >>>
        >>>
        """
        query = r.check_str("query", query)

        if values is None:
            data = get_params("Values", values)
        elif isinstance(values, list) and isinstance(values[0], tuple):
            data = values
        else:
            data = [tuple(get_params("Query params", v).values()) for v in values]

        with self._handle_auto_connection():
            with self.cursor(self.connection) as cursor:
                extras.execute_values(cursor, query, data, template)

    def create_connection(self) -> None:
        if self.connection is not None:
            raise ConnectionAlreadyEstablishedException()

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
