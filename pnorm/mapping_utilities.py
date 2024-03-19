from __future__ import annotations

from typing import Any, MutableMapping, Optional, cast, overload

from pydantic import BaseModel
from rcheck import r

from pnorm import MarshallRecordException
from pnorm.types import MappingT, ParamType, T


def get_params(
    name: str,
    params: Optional[ParamType],
    by_alias: bool = False,
) -> dict[str, Any]:
    if params is None:
        return {}

    if isinstance(params, BaseModel):
        params = params.model_dump(by_alias=by_alias, mode="json")

    return cast(
        dict[str, Any], 
        r.check_mapping(name, params, keys_of=str, values_of=Any),
    )


@overload
def combine_into_return(
    return_model: type[T],
    result: MutableMapping[str, Any] | BaseModel,
    params: Optional[ParamType] = None,
) -> T: ...


@overload
def combine_into_return(
    return_model: type[MappingT],
    result: MutableMapping[str, Any] | BaseModel,
    params: Optional[ParamType] = None,
) -> MappingT: ...


def combine_into_return(
    return_model: type[T] | type[MappingT],
    result: MutableMapping[str, Any] | BaseModel,
    params: Optional[ParamType] = None,
) -> T | MappingT:
    result_dict = get_params("Query Result", result)

    if params is not None:
        result_dict.update(get_params("Query Params", params))

    try:
        return return_model(**result_dict)
    except Exception as e:
        model_name = getattr(return_model, "__name__")
        msg = f"Could not marshall record {result_dict} into model {model_name}"
        raise MarshallRecordException(msg) from e
