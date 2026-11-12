from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.core.security import authenticated_user

router = APIRouter(prefix="/api/v1/audio", tags=["audio"])


@router.post("/transcribe")
async def transcribe_audio(request: Request, file: Annotated[UploadFile, File(...)], user_id: str = Depends(authenticated_user)):
    settings = request.app.state.settings
    filename = PurePath(file.filename or "audio").name
    contents = await file.read(settings.max_audio_bytes + 1)
    text = await request.app.state.audio_service.transcribe(contents, filename)
    return {"text": text, "model": settings.groq_transcription_model, "persisted": False}
