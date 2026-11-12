from typing import Any

from pydantic import BaseModel


class VisionResponse(BaseModel):
    analysis: dict[str, Any]
    persisted: bool = False
