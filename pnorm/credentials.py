from typing import Any, Protocol

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class CredentialsProtocol(Protocol):
    dbname: str
    user: str
    password: str
    host: str
    port: int

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...


class PostgresCredentials(CredentialsProtocol, BaseModel):
    dbname: str = Field(
        default="postgres",
        validation_alias=AliasChoices("dbname", "database"),
    )
    user: str
    password: str
    host: str
    port: int = 5432

    model_config = ConfigDict(extra="forbid")
