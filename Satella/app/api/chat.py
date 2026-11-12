from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.memory import active_memories
from app.ai.prompts import PERSONALITIES, normalize_personality
from app.core.config import get_settings
from app.core.security import authenticated_user
from app.database.database import get_db
from app.database.models import Conversation, Message
from app.providers.demo import DemoFinancialProvider
from app.schemas.chat import ChatRequest, ChatResponse, ConversationView, MessageView

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


def _seed_demo(db: Session, user_id: str, settings) -> None:
    if settings.app_env.lower() == "development" and settings.demo_data_enabled:
        DemoFinancialProvider().ensure_seeded(db, user_id)


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request, db: Session = Depends(get_db), user_id: str = Depends(authenticated_user)) -> ChatResponse:
    _seed_demo(db, user_id, request.app.state.settings)
    requested_personality = normalize_personality(payload.personality)
    if payload.personality and requested_personality not in PERSONALITIES:
        raise HTTPException(status_code=422, detail={"code": "invalid_personality", "message": "Choose one of the supported personalities."})
    if payload.conversation_id:
        conversation = db.scalar(select(Conversation).where(Conversation.id == payload.conversation_id, Conversation.user_id == user_id))
        if conversation is None:
            raise HTTPException(status_code=404, detail={"code": "conversation_not_found", "message": "Conversation not found."})
    else:
        conversation = Conversation(id=str(uuid4()), user_id=user_id, title=payload.message[:80], personality=requested_personality if payload.personality else request.app.state.settings.ai_personality)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    conversation.personality = normalize_personality(conversation.personality)
    if payload.personality:
        conversation.personality = requested_personality
    prior = list(db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at.desc()).limit(request.app.state.settings.max_chat_history_messages)).all())
    prior.reverse()
    model_history = [{"role": item.role, "content": item.content} for item in prior]
    model_history.append({"role": "user", "content": payload.message})
    db.add(Message(conversation_id=conversation.id, role="user", content=payload.message))
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()

    result = await request.app.state.orchestrator.respond(user_id, model_history, conversation.personality, active_memories(db, user_id))
    answer = result["content"]
    db.add(Message(conversation_id=conversation.id, role="assistant", content=answer))
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()
    has_simulated = get_settings().app_env.lower() == "development"
    return ChatResponse(
        answer=answer,
        conversation_id=conversation.id,
        metadata={"personality": conversation.personality, "data_source": "simulated" if has_simulated else "recorded data when tools are used", "simulated": has_simulated},
        tool_executions=result["tool_summaries"],
    )


@router.get("/{conversation_id}", response_model=ConversationView)
def get_conversation(conversation_id: str, db: Session = Depends(get_db), user_id: str = Depends(authenticated_user)) -> ConversationView:
    conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id))
    if conversation is None:
        raise HTTPException(status_code=404, detail={"code": "conversation_not_found", "message": "Conversation not found."})
    messages = db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at, Message.id)).all()
    return ConversationView(conversation_id=conversation.id, title=conversation.title, personality=normalize_personality(conversation.personality), messages=[MessageView(role=m.role, content=m.content, created_at=m.created_at) for m in messages])


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str, db: Session = Depends(get_db), user_id: str = Depends(authenticated_user)) -> dict[str, str]:
    conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id))
    if conversation is None:
        raise HTTPException(status_code=404, detail={"code": "conversation_not_found", "message": "Conversation not found."})
    db.query(Message).filter(Message.conversation_id == conversation.id).delete(synchronize_session=False)
    db.delete(conversation)
    db.commit()
    return {"status": "deleted"}
