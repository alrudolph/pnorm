from pydantic import AliasChoices, BaseModel, Field


class PostgresCredentials(BaseModel):
    dbname: str = Field(
        default="postgres",
        validation_alias=AliasChoices("dbname", "database"),
    )
    user: str
    password: str
    host: str
    port: int = 5432

    class Config:
        extra = "forbid"
