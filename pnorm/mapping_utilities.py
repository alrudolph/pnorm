from __future__ import annotations

import json
from typing import Any, Optional, Type, cast

from pydantic import BaseModel
from rcheck import r

from pnorm import MarshallRecordException, ParamType, T


def get_params(name: str, params: Optional[ParamType]) -> dict[str, Any]:
    if params is None:
        return {}

    if isinstance(params, BaseModel):
        params = params.model_dump()

    return cast(dict[str, Any], r.check_mapping(name, params, keys_of=str))


def combine_into_return(
    return_model: Type[T],
    result: dict[str, Any] | BaseModel,
    params: Optional[ParamType] = None,
) -> T:
    result_dict = get_params("Query Result", result)

    if params is not None:
        result_dict.update(get_params("Query Params", params))

    try:
        return return_model(**result_dict)
    except Exception as e:
        model_name = getattr(return_model, "__name__")
        record = json.dumps(result_dict)
        msg = f"Could not marshall record {record} into model {model_name}"
        raise MarshallRecordException(msg) from e
