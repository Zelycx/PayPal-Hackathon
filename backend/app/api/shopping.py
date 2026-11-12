"""HTTP API for guest-authenticated Shopping AI analysis."""

import asyncio
import logging
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import ValidationError

from app.api.session import require_session
from app.schemas.shopping import (
    LimitComparison,
    PurchaseBudget,
    PurchaseEvaluation,
    PurchaseStatus,
    ShoppingChatRequest,
    ShoppingChatResponse,
    ShoppingResponse,
)
from app.services.purchase_evaluation import (
    PurchaseEvaluationService,
    get_purchase_evaluation_service,
)
from app.services.paypal_chat_data import retrieve_paypal_chat_data
from app.services.shopping_service import (
    MAX_UPLOAD_BYTES,
    GroqVisionProvider,
    ShoppingService,
    ShoppingSettings,
    ShoppingServiceError,
    get_shopping_service,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shopping", tags=["Shopping AI"])
_chat_semaphore = asyncio.Semaphore(3)


def _http_error(error: ShoppingServiceError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    )


@router.post(
    "/chat",
    response_model=ShoppingChatResponse,
    summary="Ask a finance question with relevant PayPal Sandbox data",
)
async def shopping_chat(
    payload: ShoppingChatRequest,
    session: dict = Depends(require_session),
) -> ShoppingChatResponse:
    # This guest token authorizes use of this app's configured Sandbox
    # integration; it is not a PayPal user identity or account link.
    _ = session
    question = payload.message.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Enter a shopping question.")

    context = payload.context.model_dump(exclude_none=True)
    context_json = json.dumps(context, ensure_ascii=True, separators=(",", ":"))
    if len(context_json) > 10_000:
        raise HTTPException(status_code=413, detail="The shopping context is too large.")

    settings = ShoppingSettings.from_environment()
    if not settings.api_key:
        raise HTTPException(
            status_code=503,
            detail={"code": "assistant_not_configured", "message": "Shopping chat is not configured. Set GROQ_API_KEY on the backend."},
        )

    history = [turn.model_dump() for turn in payload.history[-8:]]
    try:
        paypal_context = await retrieve_paypal_chat_data(question, history)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        logger.warning("shopping_chat_paypal_unavailable type=%s", type(error).__name__)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "paypal_data_unavailable",
                "message": "PayPal Sandbox data could not be retrieved. No balance or transaction values were supplied to the assistant.",
            },
        ) from error
    except Exception as error:
        logger.warning("shopping_chat_paypal_failed type=%s", type(error).__name__)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "paypal_data_unavailable",
                "message": "PayPal Sandbox data could not be retrieved. No balance or transaction values were supplied to the assistant.",
            },
        ) from error

    try:
        async with _chat_semaphore:
            answer = await GroqVisionProvider(settings.api_key).answer_purchase_question(
                question=question,
                purchase_context=context,
                history=history,
                model=settings.vision_model,
                timeout_seconds=min(settings.timeout_seconds, 45.0),
                paypal_context=paypal_context,
            )
        return ShoppingChatResponse(answer=answer)
    except ShoppingServiceError as error:
        raise _http_error(error) from error
    except Exception as error:
        logger.warning("shopping_chat_failed type=%s", type(error).__name__)
        raise HTTPException(
            status_code=502,
            detail={"code": "assistant_unavailable", "message": "The shopping assistant is temporarily unavailable."},
        ) from error


@router.post(
    "/analyze",
    response_model=ShoppingResponse,
    summary="Analyze a cropped shopping screenshot",
)
async def analyze_shopping_image(
    request: Request,
    image: UploadFile = File(..., description="A JPEG, PNG, or WebP shopping screenshot, up to 10 MB."),
    include_purchase_evaluation: bool = Form(default=False),
    budget_amount: str | None = Form(default=None),
    budget_currency: str | None = Form(default=None),
    session: dict = Depends(require_session),
    service: ShoppingService = Depends(get_shopping_service),
    evaluator: PurchaseEvaluationService = Depends(get_purchase_evaluation_service),
) -> ShoppingResponse:
    # The session dependency is intentionally the guest Bearer token flow. The
    # returned session is not sent to the vision provider or included in logs.
    _ = session
    try:
        amount_value = budget_amount.strip() if budget_amount and budget_amount.strip() else None
        currency_value = budget_currency.strip().upper() if budget_currency and budget_currency.strip() else None
        if not include_purchase_evaluation and (amount_value is not None or currency_value is not None):
            raise HTTPException(
                status_code=422,
                detail="Budget fields require include_purchase_evaluation=true.",
            )
        budget: PurchaseBudget | None = None
        if include_purchase_evaluation and (amount_value is not None or currency_value is not None):
            if amount_value is None or currency_value is None:
                raise HTTPException(
                    status_code=422,
                    detail="Provide both a budget amount and a three-letter currency code, or leave both blank.",
                )
            try:
                budget = PurchaseBudget(amount=amount_value, currency=currency_value)
            except ValidationError as error:
                raise HTTPException(
                    status_code=422,
                    detail="Enter a valid non-negative budget and three-letter currency code.",
                ) from error

        mime_type = (image.content_type or "").split(";", 1)[0].strip().lower()
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ShoppingServiceError("unsupported_image", "Use a JPEG, PNG, or WebP image.", 415)

        raw_length = image.headers.get("content-length") if hasattr(image, "headers") else None
        if raw_length:
            try:
                if int(raw_length) > MAX_UPLOAD_BYTES:
                    raise ShoppingServiceError("image_too_large", "Image exceeds the 10 MB upload limit.", 413)
            except ValueError:
                pass

        contents = await image.read(MAX_UPLOAD_BYTES + 1)
        if not contents:
            raise ShoppingServiceError("empty_image", "The uploaded image is empty.", 400)
        if len(contents) > MAX_UPLOAD_BYTES:
            raise ShoppingServiceError("image_too_large", "Image exceeds the 10 MB upload limit.", 413)
        shopping = await service.analyze(contents, mime_type)
        if not include_purchase_evaluation:
            return shopping
        if await request.is_disconnected():
            return shopping

        try:
            evaluation = await evaluator.evaluate(
                shopping,
                budget,
                cancellation_check=request.is_disconnected,
            )
        except Exception as error:
            logger.warning("purchase_evaluation_failed type=%s", type(error).__name__)
            evaluation = PurchaseEvaluation(
                status=PurchaseStatus.needs_review,
                total_complete=False,
                balance_available=False,
                balance_freshness="unavailable",
                budget_amount=budget.amount if budget else None,
                budget_currency=budget.currency if budget else None,
                balance_comparison=LimitComparison.unavailable,
                budget_comparison=LimitComparison.needs_review if budget else LimitComparison.not_provided,
                warnings=["Financial evaluation could not be completed. Shopping results are still available."],
            )
        return shopping.model_copy(update={"purchase_evaluation": evaluation})
    except ShoppingServiceError as error:
        raise _http_error(error) from error
    except HTTPException:
        raise
    except Exception as error:
        logger.error("shopping_request_failed type=%s", type(error).__name__)
        raise HTTPException(
            status_code=500,
            detail={"code": "internal_error", "message": "Shopping analysis could not be completed."},
        ) from error
    finally:
        await image.close()
