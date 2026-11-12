from app.ai.model_client import ModelClient
from app.core.exceptions import ServiceError

SUPPORTED_AUDIO = {".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".wav", ".webm"}


def validate_audio(data: bytes, filename: str, max_bytes: int) -> str:
    if not data:
        raise ServiceError("invalid_audio", "Audio upload is empty.", 422)
    if len(data) > max_bytes:
        raise ServiceError("audio_too_large", "Audio exceeds the upload size limit.", 413)
    import os
    extension = os.path.splitext(filename.casefold())[1]
    if extension not in SUPPORTED_AUDIO:
        raise ServiceError("unsupported_audio", "Use FLAC, MP3, MP4, MPEG, MPGA, M4A, OGG, WAV, or WebM audio.", 415)
    # Basic container signatures catch common mislabeled uploads before forwarding them.
    signatures = {
        ".wav": data.startswith(b"RIFF") and data[8:12] == b"WAVE",
        ".flac": data.startswith(b"fLaC"),
        ".ogg": data.startswith(b"OggS"),
        ".mp3": data.startswith(b"ID3") or data.startswith(b"\xff\xfb") or data.startswith(b"\xff\xf3") or data.startswith(b"\xff\xf2"),
        ".mp4": b"ftyp" in data[:32],
        ".m4a": b"ftyp" in data[:32],
        ".mpeg": data.startswith(b"\x00\x00\x01"),
        ".mpga": data.startswith(b"ID3") or data.startswith(b"\xff\xfb") or data.startswith(b"\xff\xf3") or data.startswith(b"\xff\xf2"),
        ".webm": data.startswith(b"\x1aE\xdf\xa3"),
    }
    if not signatures[extension]:
        raise ServiceError("invalid_audio", "The audio data does not match the selected file format.", 422)
    return extension


class AudioService:
    def __init__(self, model_client: ModelClient, model: str, max_bytes: int) -> None:
        self.model_client = model_client
        self.model = model
        self.max_bytes = max_bytes

    async def transcribe(self, data: bytes, filename: str) -> str:
        validate_audio(data, filename, self.max_bytes)
        return await self.model_client.transcribe(data, filename, self.model)
