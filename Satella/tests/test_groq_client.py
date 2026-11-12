import asyncio
from types import SimpleNamespace

import httpx
import pytest
from groq import APITimeoutError, AuthenticationError, RateLimitError

from app.ai.model_client import GroqModelClient, ToolCall
from app.core.exceptions import ServiceError


def response(message, finish_reason="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


def client_with(fake_create):
    client = object.__new__(GroqModelClient)
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
    client.chat_model = "qwen/qwen3.8-27b"
    client.temperature = 0.2
    client.max_completion_tokens = None
    client.max_continuations = 2
    return client


def test_groq_successful_chat_and_tool_call_parsing():
    async def create(**kwargs):
        assert kwargs["model"] == "qwen/qwen3.8-27b"
        assert kwargs["tool_choice"] == "auto"
        assert kwargs["temperature"] == 0.2
        assert "max_completion_tokens" not in kwargs
        return response(SimpleNamespace(content=None, tool_calls=[SimpleNamespace(id="1", function=SimpleNamespace(name="get_budget_status", arguments='{"currency":"PHP"}'))]))

    result = asyncio.run(client_with(create).complete([{"role": "user", "content": "budget?"}], tools=[{"type": "function"}]))
    assert result.tool_calls == [ToolCall("1", "get_budget_status", '{"currency":"PHP"}')]


def test_groq_token_cap_is_configurable_and_cutoffs_continue_to_completion():
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return response(SimpleNamespace(content="Your budget leaves", tool_calls=None), finish_reason="length")
        assert kwargs["messages"][-1]["content"].startswith("Continue the unfinished answer")
        return response(SimpleNamespace(content=" PHP 200 for this month.", tool_calls=None), finish_reason="stop")

    client = client_with(create)
    client.temperature = 0.1
    client.max_completion_tokens = 128
    client.max_continuations = 1
    result = asyncio.run(client.complete([{"role": "user", "content": "Budget status?"}]))
    assert result.content == "Your budget leaves PHP 200 for this month."
    assert len(calls) == 2
    assert all(call["max_completion_tokens"] == 128 for call in calls)
    assert all(call["temperature"] == 0.1 for call in calls)


def test_groq_never_returns_a_response_still_cut_off_at_the_limit():
    async def truncated(**kwargs):
        return response(SimpleNamespace(content="An unfinished", tool_calls=None), finish_reason="length")

    client = client_with(truncated)
    client.max_completion_tokens = 64
    client.max_continuations = 0
    with pytest.raises(ServiceError) as exc:
        asyncio.run(client.complete([{"role": "user", "content": "Answer."}]))
    assert exc.value.code == "incomplete_model_response"
    assert "An unfinished" not in exc.value.message


def test_groq_empty_response_and_auth_rate_limit_timeout_mapping():
    async def empty(**kwargs):
        return SimpleNamespace(choices=[])

    with pytest.raises(ServiceError) as exc:
        asyncio.run(client_with(empty).complete([{"role": "user", "content": "hello"}]))
    assert exc.value.code == "empty_model_response"

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    auth_response = httpx.Response(401, request=request, json={"error": {"message": "invalid"}})
    rate_response = httpx.Response(429, request=request, json={"error": {"message": "slow down"}})
    auth_error = AuthenticationError("credential rejected", response=auth_response, body={"error": "redacted"})
    rate_error = RateLimitError("limited", response=rate_response, body={"error": "redacted"})
    timeout_error = APITimeoutError(request)

    async def fail(error):
        async def create(**kwargs):
            raise error
        return await client_with(create).complete([{"role": "user", "content": "hello"}])

    for error, expected in [(auth_error, "ai_authentication_failed"), (rate_error, "ai_rate_limited"), (timeout_error, "ai_timeout")]:
        with pytest.raises(ServiceError) as mapped:
            asyncio.run(fail(error))
        assert mapped.value.code == expected
        assert "credential rejected" not in mapped.value.message
