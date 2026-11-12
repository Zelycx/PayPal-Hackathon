import asyncio
import io

import pytest
from PIL import Image

from app.ai.audio import validate_audio
from app.ai.model_client import ModelResponse
from app.ai.vision import VisionService, sanitize_image
from app.core.exceptions import ServiceError


class FakeModel:
    async def analyze_image(self, image, mime_type, prompt):
        assert image and mime_type == "image/png"
        return '{"prices":[],"clearly_readable":[]}'

    async def complete(self, *args, **kwargs):
        return ModelResponse("ok")

    async def transcribe(self, *args):
        return "spoken words"


def png_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (4, 4), color="red").save(stream, format="PNG")
    return stream.getvalue()


def test_vision_valid_image_and_non_persistence():
    response = asyncio.run(VisionService(FakeModel(), 100_000).analyze(png_bytes(), "image/png", "What is visible?"))
    assert response["prices"] == []


def test_vision_rejects_invalid_unsupported_and_oversized_images():
    with pytest.raises(ServiceError):
        sanitize_image(b"bad", "image/png", 1000)
    with pytest.raises(ServiceError) as exc:
        sanitize_image(png_bytes(), "image/gif", 1000)
    assert exc.value.code == "unsupported_image"
    with pytest.raises(ServiceError) as exc:
        sanitize_image(png_bytes(), "image/png", 10)
    assert exc.value.status_code == 413


def test_audio_signature_and_size_validation():
    validate_audio(b"RIFF" + b"\x00\x00\x00\x00" + b"WAVEdata", "voice.wav", 100)
    with pytest.raises(ServiceError):
        validate_audio(b"bad", "voice.wav", 100)
    with pytest.raises(ServiceError) as exc:
        validate_audio(b"RIFF" + b"\x00\x00\x00\x00" + b"WAVEdata", "voice.wav", 5)
    assert exc.value.status_code == 413
