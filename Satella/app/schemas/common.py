from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
