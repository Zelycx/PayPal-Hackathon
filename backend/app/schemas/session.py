
from pydantic import BaseModel, Field


class SessionStartRequest(BaseModel):
    display_name: str = Field(
        min_length=1,
        max_length=40
    )
