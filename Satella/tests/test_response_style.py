import asyncio
import re

from app.ai.model_client import ModelResponse
from app.ai.orchestrator import AIOrchestrator
from app.ai.prompts import system_prompt


USER_MESSAGES = [
    "Hi Ellie!",
    "What can you do?",
    "Can I afford a ₱500 purchase?",
    "Explain my spending.",
    "Explain that in detail.",
]

MOCK_ANSWERS = [
    "Hi! I can help with budgets, spending, purchases, and financial questions.",
    "I can summarize recorded spending, check budgets, track savings goals, and compare planned purchases with your available information.",
    "I can check ₱500 against your recorded budget and expenses. The result is only as reliable as those records; it is not a guarantee of affordability.",
    "I can summarize recorded income and expenses by category or date. I will label missing, simulated, or imported information clearly.",
    "I can explain spending by grouping recorded expenses into categories and time periods. I will compare totals only within the same currency. Refunds reduce recorded expenses, while transfers are excluded from cash flow. If records are incomplete or simulated, I will say so and avoid treating the summary as a complete picture of your finances.",
]


class ScenarioModel:
    def __init__(self):
        self.index = 0
        self.system_prompts = []

    async def complete(self, messages, tools=None, model=None, tool_choice="auto"):
        self.system_prompts.append(messages[0]["content"])
        assert messages[-1]["content"] == USER_MESSAGES[self.index]
        answer = MOCK_ANSWERS[self.index]
        self.index += 1
        return ModelResponse(answer)

    async def analyze_image(self, image, mime_type, prompt):
        raise AssertionError("Image path is not used in these chat scenarios")

    async def transcribe(self, audio, filename, model):
        raise AssertionError("Audio path is not used in these chat scenarios")


class NoTools:
    def definitions(self):
        return []

    async def execute(self, name, arguments, user_id):
        raise AssertionError("No tools expected in the response-style contract test")


def words(text):
    return re.findall(r"\b[\w₱’'-]+\b", text)


def sentence_count(text):
    return len(re.findall(r"[.!?](?:\s|$)", text))


def test_five_requested_messages_use_concise_default_and_allow_detail_on_request():
    model = ScenarioModel()
    orchestrator = AIOrchestrator(model, NoTools(), max_tool_rounds=1, chat_model="mock")
    answers = []
    for message in USER_MESSAGES:
        result = asyncio.run(orchestrator.respond("test-user", [{"role": "user", "content": message}]))
        answers.append(result["content"])

    for prompt in model.system_prompts:
        assert "1–2 short sentences" in prompt
        assert "15–40 words" in prompt
        assert "plain text by default" in prompt
    for answer in answers[:4]:
        assert len(words(answer)) <= 40
        assert sentence_count(answer) <= 2
        assert not re.search(r"(?:\*\*|__|^#{1,6}\s|^\s*[-*+]\s)", answer, re.MULTILINE)
        assert r"\*\*" not in answer and r"\-" not in answer
    assert len(words(answers[4])) > 40
    assert "same currency" in answers[4]
    assert "transfers are excluded" in answers[4]
    assert len(words(system_prompt())) > 100  # safeguards remain present alongside brevity rules
