from typing import Protocol, TypedDict

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr


class CredentialsDict(TypedDict):
    dbname: str
    user: str
    password: str
    host: str
    port: int


class CredentialsProtocol(Protocol):
    dbname: str
    user: str
    password: str
    host: str
    port: int

    def as_dict(self) -> CredentialsDict: ...


class PostgresCredentials(BaseModel):
    dbname: str = Field(
        default="postgres",
        validation_alias=AliasChoices("dbname", "database"),
    )
    user: str
    password: SecretStr
    host: str
    port: int = 5432

    model_config = ConfigDict(extra="forbid")

    def as_dict(self) -> CredentialsDict:
        return {
            "dbname": self.dbname,
            "user": self.user,
            "password": self.password.get_secret_value(),
            "host": self.host,
            "port": self.port,
        }
