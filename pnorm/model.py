from pydantic import BaseModel
from rcheck import r


class PnormConfig(BaseModel):
    table_name: str
    id_column: str


class Model(BaseModel):
    pnorm_config: PnormConfig
