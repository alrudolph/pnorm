from pnorm import PostgresClient
from tests.fixutres.client import client
from tests.model.fixtures import FavoritePetModel, PetModel, UserModel


def test_load_model(client: PostgresClient):
    with client.start_session(schema="test") as session:
        session.execute(
            "insert into test_models_user (id, name) values (%(id)s, %(name)s)",
            {"id": "100", "name": "test-load"},
        )

        session.execute(
            "insert into test_models_user_pets (id, user_id, name, animmal_type) values (%(id)s, %(user_id)s, %(name)s, %(animmal_type)s)",
            {"id": "100", "user_id": "100", "name": "fluffy 1", "animmal_type": "dog"},
        )

        session.execute(
            "insert into test_models_user_favorite_pets (id, user_id, name, animmal_type) values (%(id)s, %(user_id)s, %(name)s, %(animmal_type)s)",
            {"id": "100", "user_id": "100", "name": "fluffy 2", "animmal_type": "dog"},
        )

        user_model = UserModel.load_model(session, key="100")

        expected = UserModel(
            id="100",
            name="test-load",
            favorite_pet=FavoritePetModel(
                id="100", user_id="100", name="fluffy 2", animmal_type="dog"
            ),
            pets=[
                PetModel(id="100", user_id="100", name="fluffy 1", animmal_type="dog")
            ],
        )

        try:
            assert user_model == expected
        except:
            user_model.delete(session)
            raise

        user_model.delete(session)
