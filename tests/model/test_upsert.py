from pnorm import PostgresClient, create_session
from tests.fixutres.client import client
from tests.model.fixtures import UserModel, user_model


def test_upsert(client: PostgresClient, user_model: UserModel):
    with create_session(client, schema="test") as session:
        try:
            user_model.name = "alex2"
            user_model.upsert(session)

            result = UserModel.load_model(session, key=user_model.id)

            assert user_model == result
        except:
            user_model.delete(session)
            raise

        user_model.delete(session)
