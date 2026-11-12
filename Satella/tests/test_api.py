import io

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.database.database import Base, get_db
from app.main import create_app
from app.ai.model_client import ModelResponse


class FakeModel:
    async def complete(self, messages, tools=None, model=None, tool_choice="auto"):
        return ModelResponse("Ellie is ready.")

    async def analyze_image(self, image, mime_type, prompt):
        return '{"visible_text":[],"products":[],"prices":[],"discounts":[],"shipping_fees":[],"clearly_readable":[],"inferred":[],"unknown":[]}'

    async def transcribe(self, audio, filename, model):
        return "test transcription"


def make_client(app_env="development", api_key="", demo_data_enabled=True):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    app = create_app(FakeModel(), Settings(_env_file=None, app_env=app_env, app_api_key=api_key, demo_data_enabled=demo_data_enabled))

    def override_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), engine


def test_health_finance_chat_and_conversation_storage():
    client, engine = make_client()
    try:
        finance = client.get("/api/v1/finance/accounts")
        assert finance.status_code == 200
        assert finance.json()["source"] == "simulated"
        response = client.post("/api/v1/chat", json={"message": "Hi"})
        assert response.status_code == 200
        body = response.json()
        assert body["answer"] == "Ellie is ready."
        assert body["metadata"]["personality"] == "ellie"
        history = client.get(f"/api/v1/chat/{body['conversation_id']}")
        assert history.status_code == 200 and len(history.json()["messages"]) == 2
        assert client.delete(f"/api/v1/chat/{body['conversation_id']}").status_code == 200
    finally:
        client.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_memory_consent_and_scoped_not_found():
    client, engine = make_client()
    try:
        denied = client.post("/api/v1/memory", json={"operation": "save", "key": "currency", "value": "PHP"})
        assert denied.status_code == 400
        saved = client.post("/api/v1/memory", json={"operation": "save", "key": "currency", "value": "PHP", "approved": True})
        assert saved.status_code == 200
        assert client.get("/api/v1/memory").json()["memories"][0]["value"] == "PHP"
        assert client.delete("/api/v1/memory/999").status_code == 404
    finally:
        client.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_production_requires_valid_app_key():
    client, engine = make_client("production", "secret-test-key")
    try:
        assert client.get("/api/v1/finance/accounts").status_code == 401
        assert client.get("/api/v1/finance/accounts", headers={"X-API-Key": "secret-test-key"}).status_code == 200
    finally:
        client.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_demo_seed_can_be_disabled_for_android_without_financial_fixtures():
    client, engine = make_client(demo_data_enabled=False)
    try:
        result = client.get("/api/v1/finance/accounts").json()
        assert result["source"] == "none"
        assert result["accounts"] == []
    finally:
        client.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_vision_consent_and_manual_csv_import():
    client, engine = make_client()
    stream = io.BytesIO()
    Image.new("RGB", (3, 3), color="blue").save(stream, format="PNG")
    image = stream.getvalue()
    headers = {"X-Dev-User-ID": "alice"}
    try:
        denied = client.post("/api/v1/vision/analyze", files={"file": ("screen.png", image, "image/png")}, headers=headers)
        assert denied.status_code == 403
        approved = client.post("/api/v1/vision/analyze", files={"file": ("screen.png", image, "image/png")}, headers={**headers, "X-User-Authorized": "true"})
        assert approved.status_code == 200
        assert approved.json()["persisted"] is False
        csv = b"date,description,amount,currency,kind,category\n2026-10-05,Test coffee,125.50,PHP,expense,Food\n"
        imported = client.post("/api/v1/finance/import/csv", files={"file": ("tx.csv", csv, "text/csv")}, headers=headers)
        assert imported.status_code == 200
        assert imported.json()["imported"] == 1
        repeated = client.post("/api/v1/finance/import/csv", files={"file": ("tx.csv", csv, "text/csv")}, headers=headers)
        assert repeated.json()["duplicates_skipped"] == 1
    finally:
        client.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
