from app.ai.memory import active_memories, clear_memories, delete_memory, edit_memory, list_memories, save_memory, set_memory_enabled


def test_memory_save_edit_delete_and_user_isolation(db_factory):
    db = db_factory()
    try:
        row = save_memory(db, "alice", "preferred_currency", "PHP", True)
        assert active_memories(db, "alice") == [{"key": "preferred_currency", "value": "PHP"}]
        assert active_memories(db, "bob") == []
        edited = edit_memory(db, "alice", row.id, "preferred_currency", "USD", True)
        assert edited.value == "USD"
        assert delete_memory(db, "alice", row.id) is True
        assert list_memories(db, "alice")["memories"] == []
    finally:
        db.close()


def test_memory_disable_persists_even_when_empty(db_factory):
    db = db_factory()
    try:
        set_memory_enabled(db, "alice", False)
        assert list_memories(db, "alice")["enabled"] is False
        assert active_memories(db, "alice") == []
        set_memory_enabled(db, "alice", True)
        row = save_memory(db, "alice", "tone", "concise", True)
        assert row.enabled
        assert clear_memories(db, "alice") == 1
    finally:
        db.close()
