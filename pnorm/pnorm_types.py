from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any, Mapping, MutableMapping, Optional, TypeVar

from psycopg.abc import Query as PsycopgQuery
from pydantic import BaseModel, PlainSerializer

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)

QueryParams = Mapping[str, Any]
ParamType = QueryParams | BaseModel

MappingT = TypeVar("MappingT", bound=MutableMapping[str, Any])
BaseModelMappingT = TypeVar("BaseModelMappingT", BaseModel, MutableMapping[str, Any])


U = TypeVar("U", dict[Any, Any] | None, list[Any] | None)

PostgresJSON = Annotated[
    U,
    PlainSerializer(json.dumps, when_used="json-unless-none"),
]


@dataclass
class QueryContext:
    primary_table_name: Optional[str] = None
    operation_name: Optional[str] = None  # SELECT | INSERT | UPDATE etc... (make enums)
    query_summary: Optional[str] = (
        None  # get user by id | SELECT orders | INSERT shipping_details
    )


Query = PsycopgQuery
