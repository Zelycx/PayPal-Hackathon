from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.memory import clear_memories, delete_memory, edit_memory, list_memories, save_memory, set_memory_enabled
from app.core.security import authenticated_user
from app.database.database import get_db

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


class MemoryRequest(BaseModel):
    operation: Literal["save", "edit", "disable", "enable", "clear"]
    key: str | None = Field(default=None, min_length=1, max_length=80)
    value: str | None = Field(default=None, min_length=1, max_length=500)
    memory_id: int | None = Field(default=None, gt=0)
    approved: bool = False


@router.get("")
def get_memories(db: Session = Depends(get_db), user_id: str = Depends(authenticated_user)):
    return list_memories(db, user_id)


@router.post("")
def mutate_memory(payload: MemoryRequest, db: Session = Depends(get_db), user_id: str = Depends(authenticated_user)):
    if payload.operation == "disable":
        set_memory_enabled(db, user_id, False)
        return {"status": "disabled", "memories": []}
    if payload.operation == "enable":
        set_memory_enabled(db, user_id, True)
        return {"status": "enabled"}
    if payload.operation == "clear":
        return {"status": "cleared", "deleted_count": clear_memories(db, user_id)}
    if not payload.key or not payload.value:
        raise HTTPException(status_code=422, detail={"code": "invalid_memory", "message": "Key and value are required."})
    try:
        if payload.operation == "save":
            row = save_memory(db, user_id, payload.key, payload.value, payload.approved)
        else:
            if payload.memory_id is None:
                raise HTTPException(status_code=422, detail={"code": "invalid_memory", "message": "memory_id is required for edits."})
            row = edit_memory(db, user_id, payload.memory_id, payload.key, payload.value, payload.approved)
            if row is None:
                raise HTTPException(status_code=404, detail={"code": "memory_not_found", "message": "Memory not found."})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "approval_required", "message": str(exc)}) from exc
    return {"id": row.id, "key": row.key, "value": row.value, "enabled": row.enabled}


@router.delete("")
def clear_all_memories(db: Session = Depends(get_db), user_id: str = Depends(authenticated_user)):
    return {"status": "cleared", "deleted_count": clear_memories(db, user_id)}


@router.delete("/{memory_id}")
def remove_memory(memory_id: int, db: Session = Depends(get_db), user_id: str = Depends(authenticated_user)):
    if not delete_memory(db, user_id, memory_id):
        raise HTTPException(status_code=404, detail={"code": "memory_not_found", "message": "Memory not found."})
    return {"status": "deleted"}
