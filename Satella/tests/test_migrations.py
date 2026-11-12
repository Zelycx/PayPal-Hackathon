from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database.database import Base
from app.database.migrations import migrate_legacy_assistant_personality
from app.database.models import Conversation, Memory, Message, Transaction


def test_legacy_name_migration_preserves_conversations_memories_and_financial_data():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        conversation = Conversation(id="legacy-conversation", user_id="alice", title="Budget question", personality="ciel")
        db.add(conversation)
        db.add(Message(conversation_id=conversation.id, role="assistant", content="Earlier answer remains unchanged."))
        db.add(Memory(user_id="alice", key="currency", value="PHP", enabled=True))
        db.add(Transaction(user_id="alice", description="Existing entry", amount=Decimal("42.00"), currency="PHP", kind="expense", category="Food", status="posted", occurred_at=datetime.now(timezone.utc), source="manual"))
        db.commit()

    assert migrate_legacy_assistant_personality(engine) == 1
    with Session(engine) as db:
        conversation = db.get(Conversation, "legacy-conversation")
        assert conversation.personality == "ellie"
        assert db.scalar(select(Message.content).where(Message.conversation_id == conversation.id)) == "Earlier answer remains unchanged."
        assert db.scalar(select(Memory.value).where(Memory.user_id == "alice")) == "PHP"
        assert db.scalar(select(Transaction.amount).where(Transaction.user_id == "alice")) == Decimal("42.00")
    engine.dispose()
