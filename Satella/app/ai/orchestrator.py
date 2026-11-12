from typing import Any

from app.ai.model_client import ModelClient
from app.ai.prompts import system_prompt
from app.ai.tool_registry import FinancialToolRegistry
from app.core.config import get_settings


class AIOrchestrator:
    def __init__(self, model_client: ModelClient, tool_registry: FinancialToolRegistry, max_tool_rounds: int | None = None, chat_model: str | None = None) -> None:
        self.model_client = model_client
        self.tool_registry = tool_registry
        self.max_tool_rounds = max_tool_rounds or get_settings().max_tool_rounds
        self.chat_model = chat_model or get_settings().groq_chat_model

    async def respond(self, user_id: str, history: list[dict[str, Any]], personality: str = "ellie", memories: list[dict[str, str]] | None = None) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt(personality, memories)}, *history]
        tool_summaries: list[dict[str, Any]] = []
        for round_index in range(self.max_tool_rounds + 1):
            allow_tools = round_index < self.max_tool_rounds
            response = await self.model_client.complete(
                messages,
                tools=self.tool_registry.definitions() if allow_tools else None,
                model=self.chat_model,
                tool_choice="auto" if allow_tools else "none",
            )
            if not response.tool_calls:
                return {"content": (response.content or "").strip(), "tool_summaries": tool_summaries}

            messages.append({"role": "assistant", "content": response.content, "tool_calls": [
                {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}} for call in response.tool_calls
            ]})
            for call in response.tool_calls:
                result, metadata = await self.tool_registry.execute(call.name, call.arguments, user_id)
                tool_summaries.append(metadata)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
        return {"content": "I couldn't complete the analysis within the allowed number of data lookups. Please narrow the question and try again.", "tool_summaries": tool_summaries}
