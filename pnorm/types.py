from __future__ import annotations

import json
from typing import Annotated, Any, Mapping, MutableMapping, TypeVar

from pydantic import BaseModel, PlainSerializer

T = TypeVar("T", bound=BaseModel)

QueryParams = Mapping[str, Any]
ParamType = QueryParams | BaseModel

MappingT = TypeVar("MappingT", bound=MutableMapping[str, Any])

U = TypeVar("U", dict[Any, Any] | None, list[Any] | None)

PostgresJSON = Annotated[
    U,
    PlainSerializer(json.dumps, when_used="json-unless-none"),
]
