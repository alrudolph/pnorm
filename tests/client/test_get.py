import pytest
from pydantic import BaseModel

from pnorm import (
    MultipleRecordsReturnedException,
    NoRecordsReturnedException,
    Session,
    create_session,
)

from ..fixutres.client import PostgresClientCounter, client  # type: ignore
from ..schema import DataModel


def test_simple_row_returned(client: PostgresClientCounter):
    assert client.connection is None

    row = client.get(
        DataModel,
        "select * from test_data where test_method = %(test_method)s and test_name = %(test_name)s",
        {
            "test_method": "get",
            "test_name": "test_simple_row_returned",
        },
    )

    assert row.test_method == "get"
    assert row.test_name == "test_simple_row_returned"
    assert row.value == "1"
    assert client.connection is None
    assert client.check_connections() == 1


def test_no_rows_returned(client: PostgresClientCounter):
    assert client.connection is None

    with pytest.raises(MultipleRecordsReturnedException):
        client.get(
            DataModel,
            "select * from test_data where test_method = %(test_method)s",
            {
                "test_method": "get",
            },
        )
        assert False

    assert client.connection is None
    assert client.check_connections() == 1


def test_multiple_rows_returned(client: PostgresClientCounter):
    assert client.connection is None

    with pytest.raises(NoRecordsReturnedException):
        client.get(
            DataModel,
            "select * from test_data where test_method = %(test_method)s and test_name = %(test_name)s",
            {
                "test_method": "get",
                "test_name": "test_simple_row_returned_does_not_exist",
            },
        )
        assert False

    assert client.connection is None
    assert client.check_connections() == 1


# test combine into return model
def test_combine_into_return_model(client: PostgresClientCounter):
    assert client.connection is None

    class Params(BaseModel):
        test_method: str
        test_name: str
        other_value: int

    class DataExtended(DataModel):
        other_value: int

    row = client.get(
        DataExtended,
        "select * from test_data where test_method = %(test_method)s and test_name = %(test_name)s",
        Params(
            test_method="get",
            test_name="test_combine_into_return_model",
            other_value=1,
        ),
        combine_into_return_model=True,
    )

    assert row.test_method == "get"
    assert row.test_name == "test_combine_into_return_model"
    assert row.other_value == 1  # keeps existing data
    assert row.value == "2"
    assert client.connection is None
    assert client.check_connections() == 1


def test_session_connection(client: PostgresClientCounter):
    assert client.connection is None

    # todo: what happens if exception is raised (exception as part of sql or non part)
    with create_session(client):
        assert client.connection is not None
        row = client.get(
            DataModel,
            "select * from test_data where test_method = %(test_method)s and test_name = %(test_name)s",
            {
                "test_method": "get",
                "test_name": "test_session_connection",
            },
        )
        assert row.test_method == "get"
        assert row.test_name == "test_session_connection"
        assert row.value == "3"

    assert client.connection is None
    assert client.check_connections() == 1


def test_session_connection_old(client: PostgresClientCounter):
    assert client.connection is None

    # todo: what happens if exception is raised (exception as part of sql or non part)
    with Session(client) as session:
        assert client.connection is not None
        row = session.get(
            DataModel,
            "select * from test_data where test_method = %(test_method)s and test_name = %(test_name)s",
            {
                "test_method": "get",
                "test_name": "test_session_connection",
            },
        )
        assert row.test_method == "get"
        assert row.test_name == "test_session_connection"
        assert row.value == "3"

    assert client.connection is None
    assert client.check_connections() == 1


# test when in transaction works - but it has to commit anyways
# what happens to things previously in the transaction?
def test_transaction_connection(client: PostgresClientCounter): ...
