import io
import json

from PIL import Image, ImageOps, UnidentifiedImageError

from app.ai.model_client import ModelClient
from app.core.exceptions import ServiceError

SUPPORTED_MIME = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def sanitize_image(data: bytes, declared_mime: str, max_bytes: int) -> tuple[bytes, str]:
    if not data or len(data) > max_bytes:
        raise ServiceError("invalid_image_size", "Image is empty or exceeds the upload size limit.", 413 if len(data) > max_bytes else 422)
    expected_format = SUPPORTED_MIME.get(declared_mime.lower())
    if expected_format is None:
        raise ServiceError("unsupported_image", "Use a JPEG, PNG, or WebP image.", 415)
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != expected_format:
                raise ServiceError("invalid_image", "The uploaded image content does not match its declared format.", 422)
            if image.width > 8000 or image.height > 8000 or image.width * image.height > 40_000_000:
                raise ServiceError("invalid_image_dimensions", "Image dimensions exceed the supported limit.", 413)
            image = ImageOps.exif_transpose(image)
            mode = "RGBA" if "A" in image.getbands() else "RGB"
            converted = image.convert(mode)
            clean = Image.new(mode, image.size)
            clean.paste(converted)
            output = io.BytesIO()
            clean.save(output, format=expected_format, optimize=True)
            cleaned = output.getvalue()
            if len(cleaned) > max_bytes:
                raise ServiceError("invalid_image_size", "Processed image exceeds the upload size limit.", 413)
            return cleaned, declared_mime.lower()
    except ServiceError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ServiceError("invalid_image", "The uploaded image could not be decoded.", 422) from exc


class VisionService:
    def __init__(self, model_client: ModelClient, max_bytes: int) -> None:
        self.model_client = model_client
        self.max_bytes = max_bytes

    async def analyze(self, data: bytes, mime_type: str, prompt: str) -> dict[str, object]:
        image, mime = sanitize_image(data, mime_type, self.max_bytes)
        response = await self.model_client.analyze_image(image, mime, prompt[:1000])
        try:
            result = json.loads(response)
            if not isinstance(result, dict):
                raise ValueError("Expected object")
            return result
        except (json.JSONDecodeError, ValueError) as exc:
            raise ServiceError("malformed_model_response", "The vision model returned an unreadable analysis. Please retry.", 502) from exc
