import csv
import hashlib
import io
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Account, Transaction


class ImportedTransaction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    date: datetime
    description: str = Field(min_length=1, max_length=250)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    kind: str = Field(pattern=r"^(income|expense|refund|transfer)$")
    category: str = Field(default="Other", max_length=40)
    external_id: str

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, value: str | datetime) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_csv(content: bytes, max_rows: int = 5000) -> list[ImportedTransaction]:
    """Parse a strict CSV shape; descriptions are untrusted plain data."""
    try:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        required = {"date", "description", "amount", "currency", "kind"}
        if reader.fieldnames is None or not required.issubset({f.strip().lower() for f in reader.fieldnames}):
            raise ValueError("CSV must include date, description, amount, currency, and kind columns.")
        normalized = [{(key or "").strip().lower(): value for key, value in row.items()} for row in reader]
        if len(normalized) > max_rows:
            raise ValueError(f"CSV exceeds the {max_rows} row limit.")
        records: list[ImportedTransaction] = []
        for row_number, row in enumerate(normalized, start=2):
            try:
                raw_amount = Decimal((row.get("amount") or "").strip())
                raw = "|".join(row.get(k, "") or "" for k in ("date", "description", "amount", "currency", "kind"))
                row["external_id"] = "manual-" + hashlib.sha256(f"{row_number}:{raw}".encode()).hexdigest()[:24]
                records.append(ImportedTransaction.model_validate({**row, "amount": raw_amount}))
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise ValueError(f"Invalid transaction on CSV row {row_number}.") from exc
        return records
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8 encoded.") from exc


class ManualImportProvider:
    source_name = "manual"

    def get_accounts(self, db: Session, user_id: str) -> list[Account]:
        return list(db.scalars(select(Account).where(Account.user_id == user_id, Account.source == self.source_name)).all())

    def get_transactions(self, db: Session, user_id: str) -> list[Transaction]:
        return list(db.scalars(select(Transaction).where(Transaction.user_id == user_id, Transaction.source == self.source_name).order_by(Transaction.occurred_at.desc())).all())

    def get_sync_info(self, db: Session, user_id: str) -> dict[str, object]:
        rows = self.get_transactions(db, user_id)
        return {"source": self.source_name, "last_imported_at": max((t.occurred_at for t in rows), default=None), "record_count": len(rows)}

    def parse(self, content: bytes) -> list[ImportedTransaction]:
        return parse_csv(content)

    async def disconnect(self, user_id: str) -> None:
        # Imported records remain user-owned history; disconnect does not erase them.
        return None
