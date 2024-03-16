from __future__ import annotations

from typing import Any, Self, cast, get_args, get_origin

from psycopg2.sql import SQL, Identifier, Literal
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from rcheck import r

from pnorm.client import PostgresClient


class PnormConfig(BaseModel):
    table_name: str
    id_column: str
    parent_key_id_column: str | None = None


def get_fields(cls: Model | type[Model]):
    if isinstance(cls, Model):
        return cls.model_fields

    return getattr(cls, "__dict__")["model_fields"]


def field_sub_type(field: FieldInfo):

    if get_origin(field.annotation) == list and issubclass(
        get_args(field.annotation)[0], Model
    ):
        return "model-list"
    elif issubclass(field.annotation, Model):
        return "model"

    return "val"


def _get_submodel_names(cls: Model | type[Model]) -> list[str]:
    results: list[str] = []

    for field_name, field in cls.model_fields.items():
        if field_name != "pnorm_config" and field_sub_type(field) != "val":
            results.append(field_name)

    return results


def _get_non_submodel_names(cls: Model | type[Model]) -> list[str]:
    results: list[str] = []

    for field_name, field in cls.model_fields.items():
        if field_name != "pnorm_config" and field_sub_type(field) == "val":
            results.append(field_name)

    return results


class Model(BaseModel):
    # can we hide in repr?
    pnorm_config: PnormConfig

    def _get_id_value(self):
        return getattr(self, self.pnorm_config.id_column)

    @classmethod
    def load_model(
        cls,
        client: PostgresClient,
        key: str,
        many: bool = False,
        use_parent: bool = False,
    ) -> Self:
        if many:
            model_temp = client.select(
                dict,
                SQL(
                    "select * from {table_name} where {id_column} = %(id_value)s"
                ).format(
                    table_name=Identifier(
                        get_fields(cls)["pnorm_config"].default.table_name
                    ),
                    id_column=Identifier(
                        get_fields(cls)["pnorm_config"].default.id_column
                        if not use_parent
                        else get_fields(cls)[
                            "pnorm_config"
                        ].default.parent_key_id_column
                    ),
                ),
                {"id_value": key},
            )
        else:
            # print(get_fields(cls)["pnorm_config"].default.table_name)
            # print(get_fields(cls)["pnorm_config"].default.id_column)
            model_temp = client.get(
                dict,
                SQL(
                    "select * from {table_name} where {id_column} = %(id_value)s"
                ).format(
                    table_name=Identifier(
                        get_fields(cls)["pnorm_config"].default.table_name
                    ),
                    id_column=Identifier(
                        get_fields(cls)["pnorm_config"].default.id_column
                        if not use_parent
                        else get_fields(cls)[
                            "pnorm_config"
                        ].default.parent_key_id_column
                    ),
                ),
                {"id_value": key},
            )

        if not many:
            model_temp = [model_temp]

        cls_fields = get_fields(cls)
        output = []

        for i, model in enumerate(model_temp):

            for submodel_name in _get_submodel_names(cls):
                if field_sub_type(cls_fields[submodel_name]) == "model":
                    submodel = cast(type[Model], cls_fields[submodel_name].annotation)
                    # parent_key_col = get_fields(submodel)["pnorm_config"].default.parent_key_id_column
                    parent_key_col = get_fields(cls)["pnorm_config"].default.id_column
                    model_temp[i][submodel_name] = submodel.load_model(
                        client, model[parent_key_col], use_parent=True
                    )
                elif field_sub_type(cls_fields[submodel_name]) == "model-list":
                    submodel = cast(
                        type[Model], get_args(cls_fields[submodel_name].annotation)[0]
                    )
                    # parent_key_col = get_fields(submodel)["pnorm_config"].default.parent_key_id_column
                    parent_key_col = get_fields(cls)["pnorm_config"].default.id_column
                    model_temp[i][submodel_name] = submodel.load_model(
                        client, model[parent_key_col], many=True, use_parent=True
                    )
                else:
                    raise Exception()

                # print("...", submodel, submodel_name, model_temp[i])
                # model_temp[i][submodel_name] = submodel(**model_temp[i])

            # print("|||", cls, model, i, model_temp[i])
            output.append(cls(**model_temp[i]))

        return output if many else output[0]

    def upsert(self, transaction: PostgresClient):
        """Insert the model into the db if it does not otherwise exist, otherwise update the values"""
        transaction.execute(
            SQL(
                "insert into {table_name} ({column_names}) values ({values}) on conflict({id_column}) do update set {set_fields}"
            ).format(
                table_name=Identifier(self.pnorm_config.table_name),
                id_column=Identifier(self.pnorm_config.id_column),
                column_names=SQL(",").join(
                    [
                        Identifier(column_name)
                        for column_name in _get_non_submodel_names(self)
                    ]
                ),
                values=SQL(",").join(
                    [
                        SQL(f"%({column_name})s")
                        for column_name in _get_non_submodel_names(self)
                    ]
                ),
                set_fields=SQL(",").join(
                    [
                        SQL("{col_name} = {value}").format(
                            col_name=Identifier(field_name),
                            value=Literal(getattr(self, field_name)),
                        )
                        for field_name in _get_non_submodel_names(self)
                    ]
                ),
            ),
            self,
        )

        cls_fields = get_fields(self)
        for submodel_name in _get_submodel_names(self):

            if field_sub_type(cls_fields[submodel_name]) == "model":
                submodel = cast(Model, getattr(self, submodel_name))
                submodel.upsert(transaction)
                continue

            if field_sub_type(cls_fields[submodel_name]) == "model-list":
                for model in cast(list[Any], getattr(self, submodel_name)):
                    if not isinstance(model, Model):
                        raise Exception()

                    model.upsert(transaction)

    def update_only(self, transaction: PostgresClient, *column_names: str):
        column_names_to_update: list[str] = []

        for field_name in column_names:
            field_name = r.check_str(f"column-{field_name}", field_name)

            if not hasattr(self, field_name):
                raise Exception()

            if field_sub_type(getattr(self, field_name)) == "model":
                submodel = cast(Model, getattr(self, field_name))
                submodel.upsert(transaction)
                continue

            if field_sub_type(getattr(self, field_name)) == "model-list":
                for model in cast(list[Any], getattr(self, field_name)):
                    if not isinstance(model, Model):
                        raise Exception()

                    model.upsert(transaction)

                continue

            column_names_to_update.append(field_name)

        set_fields = SQL(",").join(
            [
                SQL("{col_name} = {value}").format(
                    col_name=Identifier(field_name),
                    value=Literal(getattr(self, field_name)),
                )
                for field_name in column_names_to_update
            ]
        )

        transaction.execute(
            SQL(
                "update {table_name} set {set_fields} where {id_col} = %(id_value)s"
            ).format(
                table_name=Identifier(self.pnorm_config.table_name),
                set_fields=set_fields,
                id_col=Identifier(self.pnorm_config.id_column),
            ),
            {"id_value": self._get_id_value()},
        )
