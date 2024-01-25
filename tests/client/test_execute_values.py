from ..fixutres.client import PostgresClientCounter, client  # type: ignore
from ..schema import DataModel


def test_execute_valus_multiple_insert(client: PostgresClientCounter):
    test_method = "execute_values"
    test_name = "test_execute_valus_multiple_insert"

    values_to_insert = [
        DataModel(test_method=test_method, test_name=test_name, value="1"),
        DataModel(test_method=test_method, test_name=test_name, value="2"),
    ]

    client.execute(
        "delete from test_data where test_method = %(test_method)s and test_name = %(test_name)s",
        {
            "test_method": test_method,
            "test_name": test_name,
        },
    )

    client.execute_values(
        "insert into test_data (test_method, test_name, value) values %s",
        values_to_insert,
    )

    values_from_db = client.select(
        DataModel,
        "select * from test_data where test_method = %(test_method)s and test_name = %(test_name)s",
        {"test_method": test_method, "test_name": test_name},
    )

    assert len(values_from_db) == len(values_to_insert)
