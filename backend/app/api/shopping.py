"""HTTP API for guest-authenticated Shopping AI analysis."""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.session import require_session
from app.schemas.shopping import ShoppingResponse
from app.services.shopping_service import (
    MAX_UPLOAD_BYTES,
    ShoppingService,
    ShoppingServiceError,
    get_shopping_service,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shopping", tags=["Shopping AI"])


def _http_error(error: ShoppingServiceError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    )


@router.post(
    "/analyze",
    response_model=ShoppingResponse,
    summary="Analyze a cropped shopping screenshot",
)
async def analyze_shopping_image(
    image: UploadFile = File(..., description="A JPEG, PNG, or WebP shopping screenshot, up to 10 MB."),
    session: dict = Depends(require_session),
    service: ShoppingService = Depends(get_shopping_service),
) -> ShoppingResponse:
    # The session dependency is intentionally the guest Bearer token flow. The
    # returned session is not sent to the vision provider or included in logs.
    _ = session
    try:
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
        return await service.analyze(contents, mime_type)
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
