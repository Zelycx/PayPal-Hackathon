
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.session import require_session
from app.schemas.paypal_analysis import PayPalAnalysisResponse
from app.services.paypal_analysis_service import (
    PayPalAnalysisError,
    analyze_paypal_data,
)
from app.services.paypal_service import (
    get_paypal_balances,
    get_paypal_transactions,
    test_paypal_connection,
)


router = APIRouter(
    prefix="/paypal",
    tags=["PayPal Integration"]
)


@router.get("/connection")
async def check_connection(
    session: dict = Depends(require_session)
):
    try:
        result = await test_paypal_connection()
        return result

    except RuntimeError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error)
        )

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to PayPal Sandbox."
        )


@router.get("/balances")
async def read_paypal_balances(
    session: dict = Depends(require_session)
):
    try:
        balances = await get_paypal_balances()

        return {
            "success": True,
            "environment": "sandbox",
            "data": balances
        }

    except RuntimeError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error)
        )

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve PayPal balances."
        )


@router.get("/transactions")
async def read_paypal_transactions(
    days: int = Query(default=30, ge=1, le=31),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    transaction_id: str | None = Query(default=None),
    balance_affecting_records_only: bool = Query(default=True),
    session: dict = Depends(require_session)
):
    try:
        transactions = await get_paypal_transactions(
            days=days,
            page=page,
            page_size=page_size,
            start_date=start_date,
            end_date=end_date,
            transaction_id=transaction_id,
            balance_affecting_records_only=balance_affecting_records_only,
        )

        return {
            "success": True,
            "environment": "sandbox",
            "data": transactions
        }

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error)
        )

    except RuntimeError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error)
        )

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve PayPal transactions."
        )


@router.post("/analyze", response_model=PayPalAnalysisResponse)
async def analyze_paypal_transactions(
    session: dict = Depends(require_session),
) -> PayPalAnalysisResponse:
    # Keep the guest-session dependency; session identity is not sent to PayPal
    # or Groq and is not needed for this read-only Sandbox analysis.
    _ = session
    try:
        return await analyze_paypal_data()
    except PayPalAnalysisError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
