from datetime import datetime
from decimal import Decimal
from typing import Protocol


class AccountRecord(Protocol):
    id: int
    name: str
    currency: str
    balance: Decimal
    source: str
    synced_at: datetime


class FinancialProvider(Protocol):
    """Read-only source of account and transaction records."""

    source_name: str

    def get_accounts(self, db, user_id: str) -> list[object]: ...
    def get_transactions(self, db, user_id: str) -> list[object]: ...
    def get_sync_info(self, db, user_id: str) -> dict[str, object]: ...
    async def disconnect(self, user_id: str) -> None: ...
