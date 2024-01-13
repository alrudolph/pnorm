from __future__ import annotations

from typing import Any, Mapping, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

QueryParams = Mapping[str, Any]
ParamType = QueryParams | BaseModel
