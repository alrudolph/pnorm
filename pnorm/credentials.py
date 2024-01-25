from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class PostgresCredentials(BaseModel):
    dbname: str = Field(
        default="postgres",
        validation_alias=AliasChoices("dbname", "database"),
    )
    user: str
    password: str
    host: str
    port: int = 5432

    model_config = ConfigDict(extra="forbid")
