import asyncio
from app.ai.model_client import ModelResponse, ToolCall
from app.ai.orchestrator import AIOrchestrator


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, messages, tools=None, model=None, tool_choice="auto"):
        self.calls.append({"messages": messages, "tools": tools, "tool_choice": tool_choice})
        return self.responses.pop(0)

    async def analyze_image(self, image, mime_type, prompt):
        return "{}"

    async def transcribe(self, audio, filename, model):
        return "hello"


class FakeTools:
    def __init__(self, results=None):
        self.results = results or []
        self.executed = []

    def definitions(self):
        return [{"type": "function", "function": {"name": "get_budget_status", "parameters": {"type": "object"}}}]

    async def execute(self, name, arguments, user_id):
        self.executed.append((name, arguments, user_id))
        return self.results.pop(0) if self.results else ('{"remaining":"100"}', {"tool": name, "ok": True})


def test_normal_conversation():
    model = FakeModel([ModelResponse("Hello!", [])])
    result = asyncio.run(AIOrchestrator(model, FakeTools()).respond("alice", [{"role": "user", "content": "Hi"}]))
    assert result["content"] == "Hello!"
    assert model.calls[0]["tools"]


def test_tool_call_then_answer_and_no_unregistered_execution():
    model = FakeModel([
        ModelResponse(None, [ToolCall("call-1", "get_budget_status", '{"currency":"PHP"}')]),
        ModelResponse("You have PHP 100 left.", []),
    ])
    tools = FakeTools()
    result = asyncio.run(AIOrchestrator(model, tools).respond("alice", [{"role": "user", "content": "Food budget?"}]))
    assert result["content"] == "You have PHP 100 left."
    assert tools.executed == [("get_budget_status", '{"currency":"PHP"}', "alice")]
    assert result["tool_summaries"][0]["ok"]


def test_max_tool_rounds_force_final_without_tools():
    model = FakeModel([
        ModelResponse(None, [ToolCall("call-1", "get_budget_status", "{}")]),
        ModelResponse("Summary after tools", []),
    ])
    result = asyncio.run(AIOrchestrator(model, FakeTools(), max_tool_rounds=1).respond("alice", []))
    assert result["content"] == "Summary after tools"
    assert model.calls[-1]["tools"] is None
    assert len(model.calls) == 2
