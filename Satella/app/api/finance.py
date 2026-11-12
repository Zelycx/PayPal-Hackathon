from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import authenticated_user
from app.database.database import get_db
from app.database.models import Account, Budget, SavingsGoal, Transaction
from app.finance.financial_context import budgets_view, overview, savings_view
from app.finance.calculations import source_summary
from app.providers.demo import DemoFinancialProvider
from app.providers.manual_import import parse_csv

router = APIRouter(prefix="/api/v1/finance", tags=["finance"])
ALLOWED_CATEGORIES = {"Food", "Transportation", "Shopping", "Entertainment", "Education", "Bills", "Health", "Income", "Transfers", "Other"}


def _prepare(db: Session, user_id: str, settings) -> None:
    if settings.app_env.lower() == "development" and settings.demo_data_enabled:
        DemoFinancialProvider().ensure_seeded(db, user_id)


@router.get("/overview")
def finance_overview(request: Request, db: Session = Depends(get_db), user_id: str = Depends(authenticated_user)):
    _prepare(db, user_id, request.app.state.settings)
    return overview(db, user_id)


@router.get("/accounts")
def accounts(request: Request, db: Session = Depends(get_db), user_id: str = Depends(authenticated_user)):
    _prepare(db, user_id, request.app.state.settings)
    rows = db.scalars(select(Account).where(Account.user_id == user_id).order_by(Account.id)).all()
    return {**source_summary(rows), "accounts": [{"id": r.id, "name": r.name, "type": r.account_type, "currency": r.currency, "balance": r.balance, "available_balance": r.available_balance, "synced_at": r.synced_at, "stale": (datetime.now(timezone.utc) - (r.synced_at.replace(tzinfo=timezone.utc) if r.synced_at.tzinfo is None else r.synced_at)).total_seconds() > 86400} for r in rows]}


@router.get("/transactions")
def transactions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    days: int | None = Query(default=90, ge=1, le=730),
    category: str | None = Query(default=None, max_length=40),
    currency: str | None = Query(default=None, pattern=r"^[A-Z]{3}$"),
    db: Session = Depends(get_db),
    user_id: str = Depends(authenticated_user),
):
    _prepare(db, user_id, request.app.state.settings)
    query = select(Transaction).where(Transaction.user_id == user_id).order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
    if days:
        query = query.where(Transaction.occurred_at >= datetime.now(timezone.utc) - timedelta(days=days))
    if category:
        query = query.where(Transaction.category == category)
    if currency:
        query = query.where(Transaction.currency == currency)
    rows = db.scalars(query.limit(limit)).all()
    return {**source_summary(rows), "transactions": [{"id": t.id, "description": t.description, "merchant": t.merchant, "amount": t.amount, "currency": t.currency, "kind": t.kind, "category": t.category, "category_source": t.category_source, "status": t.status, "occurred_at": t.occurred_at, "source": t.source} for t in rows]}


class CategoryCorrection(BaseModel):
    category: str = Field(min_length=1, max_length=40)


@router.patch("/transactions/{transaction_id}/category")
def correct_category(transaction_id: int, payload: CategoryCorrection, db: Session = Depends(get_db), user_id: str = Depends(authenticated_user)):
    if payload.category not in ALLOWED_CATEGORIES:
        raise HTTPException(status_code=422, detail={"code": "invalid_category", "message": "Choose a supported transaction category."})
    row = db.scalar(select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == user_id))
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "transaction_not_found", "message": "Transaction not found."})
    row.category = payload.category
    row.category_source = "user"
    db.commit()
    return {"id": row.id, "category": row.category, "category_source": row.category_source}


@router.post("/import/csv")
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db), user_id: str = Depends(authenticated_user)):
    if file.content_type not in {"text/csv", "application/vnd.ms-excel", "application/csv"}:
        raise HTTPException(status_code=415, detail={"code": "unsupported_file", "message": "Upload a CSV file."})
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail={"code": "file_too_large", "message": "CSV exceeds the 5 MB limit."})
    try:
        imported = parse_csv(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_csv", "message": str(exc)}) from exc
    inserted = 0
    skipped = 0
    for item in imported:
        exists = db.scalar(select(Transaction.id).where(Transaction.user_id == user_id, Transaction.external_id == item.external_id))
        if exists:
            skipped += 1
            continue
        db.add(Transaction(user_id=user_id, external_id=item.external_id, description=item.description, amount=item.amount, currency=item.currency, kind=item.kind, category=item.category, category_source="import", status="posted", occurred_at=item.date, source="manual"))
        inserted += 1
    db.commit()
    return {"imported": inserted, "duplicates_skipped": skipped, "source": "manual", "data_is_live_account_data": False}


@router.get("/budgets")
def budgets(request: Request, db: Session = Depends(get_db), user_id: str = Depends(authenticated_user)):
    _prepare(db, user_id, request.app.state.settings)
    rows = db.scalars(select(Budget).where(Budget.user_id == user_id)).all()
    return {**source_summary(rows), "budgets": budgets_view(db, user_id)}


@router.get("/savings")
def savings(request: Request, db: Session = Depends(get_db), user_id: str = Depends(authenticated_user)):
    _prepare(db, user_id, request.app.state.settings)
    rows = db.scalars(select(SavingsGoal).where(SavingsGoal.user_id == user_id)).all()
    return {**source_summary(rows), "goals": savings_view(db, user_id)}
