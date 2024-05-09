from pnorm import PostgresClient
from tests.fixutres.client import client
from tests.model.fixtures import UserModel, user_model


def test_upsert(client: PostgresClient, user_model: UserModel):
    with client.start_session(schema="test") as session:
        try:
            user_model.insert(session)

            user_model.name = "alex2"
            user_model.update_only(session, "name")

            result = UserModel.load_model(session, key=user_model.id)

            assert user_model == result
        except:
            user_model.delete(session)
            raise

        user_model.delete(session)
