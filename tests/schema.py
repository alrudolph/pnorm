from pydantic import BaseModel


class DataModel(BaseModel):
    test_method: str
    test_name: str
    value: str
