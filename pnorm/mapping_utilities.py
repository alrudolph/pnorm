from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, MutableMapping, Optional, cast, overload

from pydantic import BaseModel
from rcheck import r

from .exceptions import MarshallRecordException
from .pnorm_types import BaseModelMappingT, BaseModelT, MappingT, ParamType


@overload
def get_params(
    name: str,
    params: ParamType,
    by_alias: bool = False,
) -> dict[str, Any]: ...


@overload
def get_params(
    name: str,
    params: None,
    by_alias: bool = False,
) -> None: ...


def get_params(
    name: str,
    params: Optional[ParamType] = None,
    by_alias: bool = False,
) -> dict[str, Any] | None:
    if params is None:
        return None

    if isinstance(params, BaseModel):
        params = params.model_dump(by_alias=by_alias, mode="json")

    return cast(
        dict[str, Any],
        r.check_mapping(name, params, keys_of=str, values_of=Any),
    )


@overload
def get_param_maybe_list(
    name: str,
    params: ParamType,
    by_alias: bool = False,
) -> dict[str, Any]: ...


@overload
def get_param_maybe_list(
    name: str,
    params: Sequence[ParamType],
    by_alias: bool = False,
) -> list[dict[str, Any]]: ...


@overload
def get_param_maybe_list(
    name: str,
    params: None,
    by_alias: bool = False,
) -> None: ...


def get_param_maybe_list(
    name: str,
    params: Optional[ParamType | Sequence[ParamType]] = None,
    by_alias: bool = False,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    if params is None:
        return None

    if isinstance(params, BaseModel | Mapping):
        return get_params(name, params, by_alias)

    return [get_params(name, param, by_alias) for param in params]


@overload
def combine_into_return(
    return_model: type[BaseModelT],
    result: MutableMapping[str, Any] | BaseModel,
    params: Optional[ParamType] = None,
) -> BaseModelT: ...


@overload
def combine_into_return(
    return_model: type[MappingT],
    result: MutableMapping[str, Any] | BaseModel,
    params: Optional[ParamType] = None,
) -> MappingT: ...


def combine_into_return(
    return_model: type[BaseModelMappingT],
    result: MutableMapping[str, Any] | BaseModel,
    params: Optional[ParamType] = None,
) -> BaseModelMappingT:
    result_dict = get_params("Query Result", result)

    if params is not None:
        result_dict.update(get_params("Query Params", params))

    try:
        return return_model(**result_dict)
    except Exception as e:
        model_name = getattr(return_model, "__name__")
        msg = f"Could not marshall record {result_dict} into model {model_name}"
        raise MarshallRecordException(msg) from e


@overload
def combine_many_into_return(
    return_model: type[BaseModelT],
    results: Sequence[MutableMapping[str, Any] | BaseModel],
    params: Optional[ParamType] = None,
) -> tuple[BaseModelT, ...]: ...


@overload
def combine_many_into_return(
    return_model: type[MappingT],
    results: Sequence[MutableMapping[str, Any] | BaseModel],
    params: Optional[ParamType] = None,
) -> tuple[MappingT, ...]: ...


def combine_many_into_return(
    return_model: type[BaseModelMappingT],
    results: Sequence[MutableMapping[str, Any] | BaseModel],
    params: Optional[ParamType] = None,
) -> tuple[BaseModelMappingT, ...]:
    gen = (combine_into_return(return_model, result, params) for result in results)
    return tuple(gen)
