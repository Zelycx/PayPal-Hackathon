from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Account, Budget, SavingsGoal, Transaction
from app.providers.base import FinancialProvider
from sqlalchemy import select


class DemoFinancialProvider:
    """Seeds clearly labeled fictional records for local analysis and development."""

    source_name = "simulated"

    def ensure_seeded(self, db: Session, user_id: str) -> None:
        # Never mix fictional fixtures into an account that already has user-provided data.
        existing = any(db.scalar(select(model.id).where(model.user_id == user_id).limit(1)) is not None for model in (Account, Transaction, Budget, SavingsGoal))
        if existing:
            return
        now = datetime.now(timezone.utc)
        accounts = [
            Account(user_id=user_id, name="Everyday account", account_type="checking", currency="PHP", balance=Decimal("28450.00"), available_balance=Decimal("27950.00"), synced_at=now, source=self.source_name),
            Account(user_id=user_id, name="Savings account", account_type="savings", currency="PHP", balance=Decimal("62000.00"), available_balance=Decimal("62000.00"), synced_at=now, source=self.source_name),
            Account(user_id=user_id, name="Travel wallet", account_type="wallet", currency="USD", balance=Decimal("85.00"), available_balance=Decimal("85.00"), synced_at=now - timedelta(days=2), source=self.source_name),
        ]
        db.add_all(accounts)
        db.flush()
        tx_data = [
            ("Salary", "Employer", "42000.00", "PHP", "income", "Income", 17),
            ("Groceries", "Market Basket", "2450.00", "PHP", "expense", "Food", 1),
            ("Train fare", "Transit", "180.00", "PHP", "expense", "Transportation", 2),
            ("Streaming", "StreamCo", "399.00", "PHP", "expense", "Entertainment", 3),
            ("Keyboard", "Tech Store", "3500.00", "PHP", "expense", "Shopping", 4),
            ("Coffee", "Daily Cup", "165.00", "PHP", "expense", "Food", 5),
            ("Clinic", "Community Clinic", "850.00", "PHP", "expense", "Health", 7),
            ("Electric bill", "Power Company", "2800.00", "PHP", "expense", "Bills", 9),
            ("Work reimbursement", "Employer", "600.00", "PHP", "refund", "Shopping", 10),
            ("Savings transfer", "Own accounts", "5000.00", "PHP", "transfer", "Transfers", 11),
            ("Lunch", "Noodle House", "420.00", "PHP", "expense", "Food", 12),
            ("Book", "Bookshop", "780.00", "PHP", "expense", "Education", 14),
            ("Cloud storage", "CloudBox", "2.99", "USD", "expense", "Bills", 16),
            ("Freelance work", "Client payment", "120.00", "USD", "income", "Income", 20),
        ]
        checking_id = accounts[0].id
        wallet_id = accounts[2].id
        for index, (description, merchant, amount, currency, kind, category, days_ago) in enumerate(tx_data):
            db.add(Transaction(
                user_id=user_id,
                account_id=wallet_id if currency == "USD" else checking_id,
                external_id=f"demo-{index + 1}",
                description=description,
                merchant=merchant,
                amount=Decimal(amount),
                currency=currency,
                kind=kind,
                category=category,
                status="posted",
                occurred_at=now - timedelta(days=days_ago),
                source=self.source_name,
            ))
        db.add_all([
            Budget(user_id=user_id, name="Monthly food", category="Food", amount=Decimal("12000.00"), currency="PHP", period="monthly", source=self.source_name),
            Budget(user_id=user_id, name="Monthly shopping", category="Shopping", amount=Decimal("8000.00"), currency="PHP", period="monthly", source=self.source_name),
            Budget(user_id=user_id, name="Monthly total", category=None, amount=Decimal("30000.00"), currency="PHP", period="monthly", source=self.source_name),
            SavingsGoal(user_id=user_id, name="Emergency fund", target_amount=Decimal("100000.00"), current_amount=Decimal("62000.00"), currency="PHP", source=self.source_name),
        ])
        db.commit()

    def get_accounts(self, db: Session, user_id: str) -> list[Account]:
        return list(db.scalars(select(Account).where(Account.user_id == user_id, Account.source == self.source_name)).all())

    def get_transactions(self, db: Session, user_id: str) -> list[Transaction]:
        return list(db.scalars(select(Transaction).where(Transaction.user_id == user_id, Transaction.source == self.source_name).order_by(Transaction.occurred_at.desc())).all())

    def get_sync_info(self, db: Session, user_id: str) -> dict[str, object]:
        accounts = self.get_accounts(db, user_id)
        return {"source": self.source_name, "last_synced_at": max((a.synced_at for a in accounts), default=None), "simulated": True}

    async def disconnect(self, user_id: str) -> None:
        # Demo records are local fixtures and cannot be remotely disconnected.
        return None
