from pydantic import BaseModel

class TestData(BaseModel):
    test_method: str
    test_name: str
    value: str
    