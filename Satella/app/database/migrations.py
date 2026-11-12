from sqlalchemy import Engine, text


def migrate_legacy_assistant_personality(engine: Engine) -> int:
    """Rename the stored persona label without touching conversation messages or other user data."""
    with engine.begin() as connection:
        result = connection.execute(
            text("UPDATE conversations SET personality = :current WHERE LOWER(personality) = :legacy"),
            {"current": "ellie", "legacy": "ciel"},
        )
        return result.rowcount or 0
