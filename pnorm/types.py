from __future__ import annotations

from typing import Any, Mapping, MutableMapping, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

QueryParams = Mapping[str, Any]
ParamType = QueryParams | BaseModel

MappingT = TypeVar("MappingT", bound=MutableMapping[str, Any])
