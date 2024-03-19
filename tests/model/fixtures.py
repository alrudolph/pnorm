from __future__ import annotations

from pytest import fixture

from pnorm import Model, PnormConfig


class UserModel(Model):
    pnorm_config: PnormConfig = PnormConfig(
        table_name="test_models_user",
        id_column="id",
    )

    id: str
    name: str

    favorite_pet: FavoritePetModel
    pets: list[PetModel]


class PetModel(Model):
    pnorm_config: PnormConfig = PnormConfig(
        table_name="test_models_user_pets",
        id_column="id",
        parent_key_id_column="user_id",
    )

    id: str
    user_id: str

    name: str
    animmal_type: str


class FavoritePetModel(PetModel):
    pnorm_config: PnormConfig = PnormConfig(
        table_name="test_models_user_favorite_pets",
        id_column="id",
        parent_key_id_column="user_id",
    )


@fixture
def user_model():
    return UserModel(
        id="1",
        name="alex",
        favorite_pet=FavoritePetModel(
            id="1", user_id="1", name="fluffy 2", animmal_type="dog"
        ),
        pets=[
            PetModel(id="1", user_id="1", name="fluffy 1", animmal_type="dog"),
            PetModel(id="2", user_id="1", name="fluffy 2", animmal_type="dog"),
            PetModel(id="3", user_id="1", name="fluffy 3", animmal_type="dog"),
        ],
    )
