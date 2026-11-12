from app.ai.prompts import PERSONALITIES, normalize_personality, system_prompt
from app.core.config import Settings


def test_ellie_prompt_is_concise_and_keeps_financial_safeguards():
    prompt = system_prompt()
    assert "You are Ellie" in prompt
    assert "Ciel" not in prompt
    assert "Answer the actual question immediately in 1–2 short sentences" in prompt
    assert "Aim for 15–40 words" in prompt
    assert "Use plain text by default" in prompt
    assert "Never emit escaped Markdown" in prompt
    assert "simple, everyday English" in prompt
    assert "Expand only when the user asks for detail" in prompt
    assert "important financial warnings, assumptions, calculation inputs or results, and uncertainty" in prompt
    assert "Never invent account balances" in prompt
    assert "Ask only relevant follow-up questions" in prompt


def test_ellie_is_the_default_personality_and_legacy_name_is_compatible():
    assert "ellie" in PERSONALITIES
    assert "ciel" not in PERSONALITIES
    assert normalize_personality("Ciel") == "ellie"
    assert Settings(_env_file=None).ai_personality == "ellie"
    assert Settings(_env_file=None, ai_personality="ciel").ai_personality == "ellie"


def test_completion_token_cap_is_optional_and_generation_settings_are_configurable(monkeypatch):
    monkeypatch.setenv("GROQ_MAX_COMPLETION_TOKENS", "")
    settings = Settings(_env_file=None)
    assert settings.groq_temperature == 0.2
    assert settings.groq_max_completion_tokens is None
    configured = Settings(_env_file=None, groq_temperature=0.1, groq_max_completion_tokens=512, groq_max_continuations=3)
    assert configured.groq_temperature == 0.1
    assert configured.groq_max_completion_tokens == 512
    assert configured.groq_max_continuations == 3
