from dataclasses import dataclass


@dataclass
class ServiceError(Exception):
    code: str
    message: str
    status_code: int = 503

    def __str__(self) -> str:
        return self.message
