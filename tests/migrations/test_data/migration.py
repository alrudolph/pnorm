from pydantic import BaseModel

from pnorm.migrations import Migration


class TestData(BaseModel):
    test_method: str
    test_name: str
    value: str


class V1(Migration):
    def upgrade(self, from_version: int | None):
        self.client.execute(
            "create table test_data ("
            "  test_method varchar"
            "  , test_name varchar"
            "  , value varchar"
            ")"
        )
        self.client.execute_values(
            "insert into test_data (test_method, test_name, value) values %s",
            [
                TestData(
                    test_method="get",
                    test_name="test_simple_row_returned",
                    value="1",
                ),
                TestData(
                    test_method="get",
                    test_name="test_combine_into_return_model",
                    value="2",
                ),
                TestData(
                    test_method="get", test_name="test_session_connection", value="3"
                ),
            ],
        )

        self.client.execute(
            "create table test_models_user ("
            "  id varchar primary key"
            "  , name varchar"
            ");"
            "create table test_models_user_pets ("
            "  id varchar primary key"
            "  , user_id varchar"
            "  , name varchar"
            "  , animmal_type varchar"
            ");"
            "create table test_models_user_favorite_pets ("
            "  id varchar primary key"
            "  , user_id varchar"
            "  , name varchar"
            "  , animmal_type varchar"
            ");"
        )

        super().upgrade(from_version)

    def downgrade(self, to_version: int):
        self.client.execute("drop table test_data")
        super().downgrade(to_version)
