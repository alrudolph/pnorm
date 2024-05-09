from pnorm import PostgresClient
from tests.fixutres.client import client
from tests.model.fixtures import UserModel, user_model


def test_insert(client: PostgresClient, user_model: UserModel):
    with client.start_session(schema="test") as session:
        try:
            output = user_model.insert(session)
            result = UserModel.load_model(session, key=user_model.id)
        except:
            user_model.delete(session)
            raise

        user_model.delete(session)
        assert user_model == result
        assert output == user_model
