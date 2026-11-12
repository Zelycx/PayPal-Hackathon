from typing import Annotated
import json
import re
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile

from app.core.security import authenticated_user
from app.schemas.vision import VisionResponse

router = APIRouter(prefix="/api/v1/vision", tags=["vision"])


@router.post("/analyze", response_model=VisionResponse)
async def analyze_image(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    prompt: Annotated[str, Form()] = "Describe the visible information and clearly label uncertainty.",
    evaluate_purchase: Annotated[bool, Form()] = False,
    budget_category: Annotated[str, Form()] = "Shopping",
    x_user_authorized: Annotated[bool, Header(alias="X-User-Authorized")] = False,
    user_id: str = Depends(authenticated_user),
):
    if not x_user_authorized:
        raise HTTPException(status_code=403, detail={"code": "user_consent_required", "message": "Confirm that this image was selected for analysis."})
    settings = request.app.state.settings
    if len(prompt) > 1000:
        raise HTTPException(status_code=422, detail={"code": "prompt_too_long", "message": "Prompt must be 1,000 characters or fewer."})
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail={"code": "unsupported_image", "message": "Use a JPEG, PNG, or WebP image."})
    contents = await file.read(settings.max_image_bytes + 1)
    result = await request.app.state.vision_service.analyze(contents, file.content_type, prompt)
    if evaluate_purchase:
        prices = result.get("prices")
        if not isinstance(prices, list):
            prices = []
        clear_prices = [item for item in prices if isinstance(item, dict) and item.get("readability") == "clear" and item.get("amount") is not None and isinstance(item.get("currency"), str) and re.fullmatch(r"[A-Z]{3}", item["currency"])]
        if len(clear_prices) != 1:
            result["affordability"] = {"verdict": "insufficient_information", "missing_information": ["A single clearly readable price and currency could not be identified."], "tool_executed": False}
        else:
            try:
                price = Decimal(str(clear_prices[0]["amount"]))
                if not price.is_finite() or price <= 0:
                    raise InvalidOperation
                tool_result, tool_metadata = await request.app.state.financial_tools.execute(
                    "evaluate_purchase",
                    json.dumps({"price": str(price), "currency": clear_prices[0]["currency"], "category": budget_category}),
                    user_id,
                )
                result["affordability"] = json.loads(tool_result)
                result["affordability_tool_execution"] = tool_metadata
            except (InvalidOperation, ValueError, json.JSONDecodeError):
                result["affordability"] = {"verdict": "insufficient_information", "missing_information": ["The displayed amount could not be safely interpreted."], "tool_executed": False}
    return VisionResponse(analysis=result, persisted=False)
