from __future__ import annotations

from typing import Any, Literal, Self, cast, get_args, get_origin, overload

from psycopg2.sql import SQL, Composed, Identifier
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from rcheck import r

from pnorm.client import PostgresClient


class PnormConfig(BaseModel):
    table_name: str
    id_column: str
    parent_key_id_column: str | None = None


def get_fields(cls: Model | type[Model]):
    if not cls.__pydantic_complete__:
        cls.model_rebuild()

    if isinstance(cls, Model):
        return cls.model_fields

    return getattr(cls, "__dict__")["model_fields"]


def field_sub_type(field: FieldInfo):
    try:
        if get_origin(field.annotation) == list and issubclass(
            get_args(field.annotation)[0], Model
        ):
            return "model-list"
        elif issubclass(field.annotation, Model):
            return "model"

        # print(field, field.annotation, get_origin(field.annotation))
    except:
        return "val"

    return "val"


def _get_submodel_names(cls: Model | type[Model]) -> list[str]:
    results: list[str] = []

    for field_name, field in cls.model_fields.items():
        if field_name != "pnorm_config" and field_sub_type(field) != "val":
            results.append(field_name)

    return results


def _get_submodel_names_types(cls: Model | type[Model]) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    cls_fields = get_fields(cls)

    for submodel_name in _get_submodel_names(cls):
        results.append((submodel_name, field_sub_type(cls_fields[submodel_name])))

    return results


def _get_submodels(cls: Model | type[Model]) -> list[Model | list[Model]]:
    results: list[Model] = []

    for submodel_name in _get_submodel_names(cls):
        results.append(getattr(cls, submodel_name))

    return results


def _get_submodels_names(
    cls: Model | type[Model],
) -> list[tuple[Model | list[Model], str]]:
    results: list[tuple[Model | list[Model], str]] = []

    for submodel_name in _get_submodel_names(cls):
        results.append((getattr(cls, submodel_name), submodel_name))

    return results


def _get_non_submodel_names(cls: Model | type[Model]) -> list[str]:
    results: list[str] = []

    for field_name, field in cls.model_fields.items():
        if field_name != "pnorm_config" and field_sub_type(field) == "val":
            results.append(field_name)

    return results


def sql_format(sql: str, **kwargs: Any) -> Composed:
    return SQL(sql).format(**kwargs)


class ModelConfig(BaseModel):
    table_name: str
    id_column: str
    parent_key_id_column: str | None = None


def model_config(model: Model | type[Model]) -> ModelConfig:
    config = get_fields(model)["pnorm_config"].default
    return ModelConfig(
        table_name=config.table_name,
        id_column=config.id_column,
        parent_key_id_column=config.parent_key_id_column,
    )


def set_col_value(column_names: list[str]) -> Composed:
    return SQL(",").join(
        [
            SQL("{col_name} = {value}").format(
                col_name=Identifier(field_name),
                value=SQL(f"%({field_name})s"),
            )
            for field_name in column_names
        ]
    )


def named_parameters(column_names: list[str]) -> Composed:
    return SQL(",").join([SQL(f"%({column_name})s") for column_name in column_names])


def col_names_as_identifier(column_names: list[str]) -> Composed:
    return SQL(",").join([Identifier(column_name) for column_name in column_names])


class Model(BaseModel):
    # can we hide in repr?
    pnorm_config: PnormConfig

    def _get_id_value(self) -> Any:
        return getattr(self, self.pnorm_config.id_column)

    @overload
    @classmethod
    def _load_model_or_many(
        cls,
        client: PostgresClient,
        key: str,
        many: Literal[False] = False,
        use_parent: bool = False,
    ) -> Self: ...

    @overload
    @classmethod
    def _load_model_or_many(
        cls,
        client: PostgresClient,
        key: str,
        many: Literal[True] = True,
        use_parent: bool = False,
    ) -> list[Self]: ...

    @classmethod
    def _load_model_or_many(
        cls,
        client: PostgresClient,
        key: str,
        many: bool = False,
        use_parent: bool = False,
    ) -> Self | list[Self]:
        config = model_config(cls)

        load_query = sql_format(
            "select * from {table_name} where {id_column} = %(id_value)s",
            table_name=Identifier(config.table_name),
            id_column=Identifier(
                config.parent_key_id_column
                if use_parent and config.parent_key_id_column is not None
                else config.id_column
            ),
        )

        if many:
            model_temp = client.select(dict[str, Any], load_query, {"id_value": key})
        else:
            model_temp = client.get(dict[str, Any], load_query, {"id_value": key})
            model_temp = [model_temp]

        cls_fields = get_fields(cls)
        output: list[Self] = []

        for i, model in enumerate(model_temp):

            for submodel_name, type_ in _get_submodel_names_types(cls):
                match type_:
                    case "model":
                        submodel = cast(
                            type[Model], cls_fields[submodel_name].annotation
                        )
                        model_temp[i][submodel_name] = submodel._load_model_or_many(
                            client,
                            model[config.id_column],
                            use_parent=True,
                        )
                    case "model-list":
                        submodel = cast(
                            type[Model],
                            get_args(cls_fields[submodel_name].annotation)[0],
                        )
                        model_temp[i][submodel_name] = submodel._load_model_or_many(
                            client,
                            model[config.id_column],
                            many=True,
                            use_parent=True,
                        )

            output.append(cls(**model_temp[i]))

        return output if many else output[0]

    @classmethod
    def load_model(
        cls,
        client: PostgresClient,
        key: str,
    ) -> Self:
        return cls._load_model_or_many(client, key)

    def insert(
        self,
        transaction: PostgresClient,
        ignore_on_conflict: bool = False,
    ) -> Self:
        """Insert the model into the db if it does not otherwise exist, otherwsise do nothing"""
        output = transaction.get(
            dict[str, Any],
            sql_format(
                "insert into {table_name} ({column_names}) values ({values}) on conflict do nothing returning *",
                table_name=Identifier(self.pnorm_config.table_name),
                column_names=col_names_as_identifier(_get_non_submodel_names(self)),
                values=named_parameters(_get_non_submodel_names(self)),
            ),
            self,
        )

        for submodel, submodel_name in _get_submodels_names(self):
            match submodel:
                case Model():
                    output[submodel_name] = submodel.insert(transaction)
                case list(_):
                    sub_outputs: list[Model] = []

                    for model in submodel:
                        sub_outputs.append(model.insert(transaction))

                    output[submodel_name] = sub_outputs

        return self.__class__(**output)

    def upsert(self, transaction: PostgresClient) -> None:
        """Insert the model into the db if it does not otherwise exist, otherwise update the values"""
        transaction.execute(
            sql_format(
                "insert into {table_name} ({column_names}) values ({values}) on conflict({id_column}) do update set {set_fields}",
                table_name=Identifier(self.pnorm_config.table_name),
                column_names=col_names_as_identifier(_get_non_submodel_names(self)),
                values=named_parameters(_get_non_submodel_names(self)),
                id_column=Identifier(self.pnorm_config.id_column),
                set_fields=set_col_value(_get_non_submodel_names(self)),
            ),
            self,
        )

        for submodel in _get_submodels(self):
            match submodel:
                case Model():
                    submodel.upsert(transaction)
                case list(_):
                    for model in submodel:
                        model.upsert(transaction)

    def update_only(self, transaction: PostgresClient, *column_names: str) -> None:
        column_names_to_update: list[str] = []

        for field_name in column_names:
            field_name = r.check_str(f"column-{field_name}", field_name)

            if not hasattr(self, field_name):
                raise Exception()

            match field_sub_type(getattr(self, field_name)):
                case "model":
                    submodel = cast(Model, getattr(self, field_name))
                    submodel.upsert(transaction)
                case "model-list":
                    for model in cast(list[Any], getattr(self, field_name)):
                        if not isinstance(model, Model):
                            raise Exception()

                        model.upsert(transaction)
                case "val":
                    column_names_to_update.append(field_name)

        transaction.execute(
            sql_format(
                "update {table_name} set {set_fields} where {id_col} = %(id_value)s",
                table_name=Identifier(self.pnorm_config.table_name),
                set_fields=set_col_value(column_names_to_update),
                id_col=Identifier(self.pnorm_config.id_column),
            ),
            {"id_value": self._get_id_value(), **self.model_dump(mode="json")},
        )

    def create_table_ddl_string(self):
        # add recursive calls
        ...

    def delete(self, transaction: PostgresClient) -> None:
        transaction.execute(
            sql_format(
                "delete from {table_name} where {id_column} = %(id_value)s",
                table_name=Identifier(self.pnorm_config.table_name),
                id_column=Identifier(self.pnorm_config.id_column),
            ),
            {"id_value": self._get_id_value()},
        )

        for submodel in _get_submodels(self):
            match submodel:
                case Model():
                    submodel.delete(transaction)
                case list(_):
                    for model in submodel:
                        model.delete(transaction)
