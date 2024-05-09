from __future__ import annotations

from contextlib import contextmanager
from typing import (
    Any,
    Generator,
    Generic,
    Literal,
    Self,
    TypeVar,
    cast,
    get_args,
    get_origin,
    overload,
)

from psycopg2.sql import SQL, Composed, Identifier
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from rcheck import r
from datetime import datetime
from pnorm.client import PostgresClient


class PnormConfig(BaseModel):
    table_name: str
    id_column: str
    parent_key_id_column: str | None = None


class ModelUtils:
    def __init__(self, model: Model | type[Model]):
        self.model = model

    @property
    def fields(self) -> dict[str, FieldInfo]:
        if not self.model.__pydantic_complete__:
            self.model.model_rebuild()

        if isinstance(self.model, Model):
            return self.model.model_fields

        return getattr(self.model, "__dict__")["model_fields"]

    @property
    def submodel_names(self) -> list[str]:
        results: list[str] = []

        for field_name, field in self.model.model_fields.items():
            if field_name != "pnorm_config" and field_sub_type(field) != "val":
                results.append(field_name)

        return results

    @property
    def submodel_names_types(self) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        cls_fields = self.fields

        for submodel_name in self.submodel_names:
            results.append((submodel_name, field_sub_type(cls_fields[submodel_name])))

        return results

    @property
    def submodels(self) -> list[Model | list[Model]]:
        results: list[Model | list[Model]] = []

        for submodel_name in self.submodel_names:
            try:
                field = getattr(self.model, "__dict__")["model_fields"][submodel_name]
                results.append(field.annotation)
            except:
                results.append(getattr(self.model, submodel_name))

        return results

    @property
    def submodels_names(self) -> dict[str, Model | list[Model]]:
        results: dict[str, Model | list[Model]] = {}

        for submodel_name in self.submodel_names:
            results[submodel_name] = getattr(self.model, submodel_name)

        return results

    @property
    def non_submodel_names(self) -> list[str]:
        results: list[str] = []

        for field_name, field in self.model.model_fields.items():
            if field_name != "pnorm_config" and field_sub_type(field) == "val":
                results.append(field_name)

        return results

    def model_config(self) -> ModelConfig:
        config = self.fields["pnorm_config"].default
        return ModelConfig(
            table_name=config.table_name,
            id_column=config.id_column,
            parent_key_id_column=config.parent_key_id_column,
        )


def field_sub_type(field: FieldInfo):
    try:
        if get_origin(field.annotation) == list and issubclass(
            get_args(field.annotation)[0], Model
        ):
            return "model-list"
        elif issubclass(field.annotation, Model):
            return "model"
    except:
        return "val"

    return "val"


def sql_format(sql: str, **kwargs: Any) -> Composed:
    return SQL(sql).format(**kwargs)


class ModelConfig(BaseModel):
    table_name: str
    id_column: str
    parent_key_id_column: str | None = None


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
    _transaction: PostgresClient | None = None

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
        model_utils = ModelUtils(cls)
        config = model_utils.model_config()

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

        cls_fields = model_utils.fields
        output: list[Self] = []

        for i, model in enumerate(model_temp):

            for submodel_name, type_ in model_utils.submodel_names_types:
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

    @overload
    def insert(
        self,
        transaction: PostgresClient,
        /,
        *,
        ignore_on_conflict: bool = False,
    ) -> Self: ...

    @overload
    def insert(self, /, *, ignore_on_conflict: bool = False) -> Self: ...

    def insert(
        self,
        transaction: PostgresClient | bool | None = None,
        /,
        *,
        ignore_on_conflict: bool = False,
    ) -> Self:
        if isinstance(transaction, bool):
            assert self._transaction is not None
            return self._insert(self._transaction, transaction)

        assert transaction is not None
        return self._insert(transaction, ignore_on_conflict)

    def _insert(
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
                column_names=col_names_as_identifier(
                    self._model_utils.non_submodel_names
                ),
                values=named_parameters(self._model_utils.non_submodel_names),
            ),
            self,
        )

        for submodel_name, submodel in self._model_utils.submodels_names.items():
            match submodel:
                case Model():
                    output[submodel_name] = submodel.insert(transaction)
                case list(_):
                    sub_outputs: list[Model] = []

                    for model in submodel:
                        sub_outputs.append(model.insert(transaction))

                    output[submodel_name] = sub_outputs

        return self.__class__(**output)

    def upsert(self, transaction: PostgresClient | None = None, /) -> None:
        if transaction is not None:
            return self._upsert(transaction)

        assert self._transaction is not None
        return self._upsert(self._transaction)

    def _upsert(self, transaction: PostgresClient) -> None:
        """Insert the model into the db if it does not otherwise exist, otherwise update the values"""

        transaction.execute(
            sql_format(
                "insert into {table_name} ({column_names}) values ({values}) on conflict({id_column}) do update set {set_fields}",
                table_name=Identifier(self.pnorm_config.table_name),
                column_names=col_names_as_identifier(
                    self._model_utils.non_submodel_names
                ),
                values=named_parameters(self._model_utils.non_submodel_names),
                id_column=Identifier(self.pnorm_config.id_column),
                set_fields=set_col_value(self._model_utils.non_submodel_names),
            ),
            self,
        )

        for submodel in self._model_utils.submodels:
            match submodel:
                case Model():
                    submodel.upsert(transaction)
                case list(_):
                    for model in submodel:
                        model.upsert(transaction)

    @overload
    def update_only(
        self,
        transaction: PostgresClient,
        /,
        *additional_column_names: str,
    ) -> None: ...

    @overload
    def update_only(
        self,
        first_column_name: str,
        /,
        *additional_column_names: str,
    ) -> None: ...

    def update_only(
        self,
        transaction: PostgresClient | str,
        /,
        *additional_column_names: str,
    ) -> None:
        if isinstance(transaction, str):
            assert self._transaction is not None
            return self._update_only(
                self._transaction, transaction, *additional_column_names
            )

        return self._update_only(transaction, *additional_column_names)

    def _update_only(self, transaction: PostgresClient, *column_names: str) -> None:
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

    def delete(self, transaction: PostgresClient | None = None, /) -> None:
        if transaction is not None:
            return self._delete(transaction)

        assert self._transaction is not None
        return self._delete(self._transaction)

    def _delete(self, transaction: PostgresClient) -> None:
        transaction.execute(
            sql_format(
                "delete from {table_name} where {id_column} = %(id_value)s",
                table_name=Identifier(self.pnorm_config.table_name),
                id_column=Identifier(self.pnorm_config.id_column),
            ),
            {"id_value": self._get_id_value()},
        )

        for submodel in self._model_utils.submodels:
            match submodel:
                case Model():
                    submodel.delete(transaction)
                case list(_):
                    for model in submodel:
                        model.delete(transaction)
        
    @property
    def _model_utils(self) -> ModelUtils:
        return ModelUtils(self)

    @contextmanager
    def start_transaction(
        self, client: PostgresClient, /
    ) -> Generator[Self, None, None]:
        updated_model = self.model_copy()

        try:
            # TODO: auto transaction context like in client.py
            if self._transaction is not None:
                yield updated_model
            else:
                with client.start_transaction() as transaction:
                    updated_model._set_transaction(transaction)
                    yield updated_model
        finally:
            updated_model._close_transaction()

        for field_name, value in updated_model:
            setattr(self, field_name, value)

    def _set_transaction(self, transaction: PostgresClient, /):
        self._transaction = transaction

    def _close_transaction(self):
        # TODO: or on the transaction cursor set a field to mark no longer use?
        self._transaction = None


def create_table_ddl_string(cls: Model | type[Model]) -> str:
    model_utils = ModelUtils(cls)
    
    datatypes = {
        str: "varchar",
        int: "int",
        float: "float",
        bool: "bool",
        datetime: "timestamp",
    }
    
    # previous = f'create table "{cls.pnorm_config.table_name}" (\n'
    previous = "create table [TABLE_NAME] (\n"
        
    for i, column_name in enumerate(model_utils.non_submodel_names):
        column_type = datatypes[model_utils.fields[column_name].annotation]
        
        if i == 0:
            previous += "  "
        else:
            previous += "  , "

        previous += f'"{column_name}" {column_type}\n'
    
    # TODO: add foreing key constraint
    # TODO: add "primary key" on id_columns
    # if cls.pnorm_config.parent_key_id_column is not None:
    #     column_name = cls.pnorm_config.parent_key_id_column
    #     # column_type = datatypes[getattr(self, column_name).annotation]
    #     column_type = datatypes[cls._model_utils.fields[column_name].annotation]
    #     previous += f'  , "{column_name}" {column_type}\n'
    
    previous +=");\n"
    
    for submodel in model_utils.submodels:
        match submodel:
            case Model():
                previous += "\n" + create_table_ddl_string(submodel)
            case list(_):
                for model in submodel:
                    previous += "\n" + create_table_ddl_string(model)
            case _:
                if issubclass(submodel, BaseModel):
                    previous += "\n" + create_table_ddl_string(submodel)
        

    return previous
    
