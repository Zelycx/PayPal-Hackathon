from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Memory, MemoryPreference


def list_memories(db: Session, user_id: str) -> dict[str, object]:
    rows = list(db.scalars(select(Memory).where(Memory.user_id == user_id).order_by(Memory.id)).all())
    preference = db.get(MemoryPreference, user_id)
    enabled = preference.enabled if preference else True
    return {"enabled": enabled, "memories": [{"id": row.id, "key": row.key, "value": row.value, "enabled": row.enabled, "created_at": row.created_at} for row in rows]}


def active_memories(db: Session, user_id: str) -> list[dict[str, str]]:
    preference = db.get(MemoryPreference, user_id)
    if preference and not preference.enabled:
        return []
    rows = list(db.scalars(select(Memory).where(Memory.user_id == user_id, Memory.enabled.is_(True))).all())
    return [{"key": row.key, "value": row.value} for row in rows]


def save_memory(db: Session, user_id: str, key: str, value: str, approved: bool) -> Memory:
    if not approved:
        raise ValueError("Explicit user approval is required to save a memory.")
    preference = db.get(MemoryPreference, user_id)
    if preference and not preference.enabled:
        raise ValueError("Memory is disabled. Enable it before saving a preference.")
    row = Memory(user_id=user_id, key=key, value=value, enabled=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def edit_memory(db: Session, user_id: str, memory_id: int, key: str, value: str, approved: bool) -> Memory | None:
    if not approved:
        raise ValueError("Explicit user approval is required to edit a memory.")
    row = db.scalar(select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id))
    if row is None:
        return None
    row.key, row.value = key, value
    db.commit()
    return row


def set_memory_enabled(db: Session, user_id: str, enabled: bool) -> None:
    preference = db.get(MemoryPreference, user_id)
    if preference is None:
        preference = MemoryPreference(user_id=user_id, enabled=enabled)
        db.add(preference)
    else:
        preference.enabled = enabled
    rows = db.scalars(select(Memory).where(Memory.user_id == user_id)).all()
    for row in rows:
        row.enabled = enabled
    db.commit()


def delete_memory(db: Session, user_id: str, memory_id: int) -> bool:
    row = db.scalar(select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id))
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def clear_memories(db: Session, user_id: str) -> int:
    rows = list(db.scalars(select(Memory).where(Memory.user_id == user_id)).all())
    for row in rows:
        db.delete(row)
    db.commit()
    return len(rows)
