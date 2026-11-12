
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.session import require_session
from app.services.paypal_service import test_paypal_connection
from app.services.paypal_service import get_paypal_balances
from app.services.paypal_service import get_paypal_transactions


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
    session: dict = Depends(require_session)
):
    try:
        transactions = await get_paypal_transactions(
            days=days,
            page=page,
            page_size=page_size
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
