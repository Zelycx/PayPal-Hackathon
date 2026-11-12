import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ai.audio import AudioService
from app.ai.model_client import GroqModelClient, MissingModelClient, ModelClient
from app.ai.orchestrator import AIOrchestrator
from app.ai.tool_registry import build_registry
from app.ai.vision import VisionService
from app.api import audio, chat, finance, health, memory, vision
from app.core.config import Settings, get_settings
from app.core.exceptions import ServiceError
from app.core.logging import configure_logging
from app.database.database import Base, SessionLocal, engine
from app.database.migrations import migrate_legacy_assistant_personality
from app.providers.demo import DemoFinancialProvider

logger = logging.getLogger(__name__)


def create_app(model_client: ModelClient | None = None, settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        Base.metadata.create_all(bind=engine)
        migrate_legacy_assistant_personality(engine)
        yield

    application = FastAPI(
        title="AI Financial Companion Backend",
        version="0.1.0",
        description="Read-only financial analysis and conversational AI backend.",
        docs_url="/docs" if config.app_env.lower() == "development" else None,
        redoc_url="/redoc" if config.app_env.lower() == "development" else None,
        openapi_url="/openapi.json" if config.app_env.lower() == "development" else None,
        lifespan=lifespan,
    )
    application.state.settings = config
    provider = DemoFinancialProvider()

    def seed_demo(db, user_id: str) -> None:
        if config.app_env.lower() == "development" and config.demo_data_enabled:
            provider.ensure_seeded(db, user_id)

    selected_model = model_client or (GroqModelClient(
        config.groq_api_key,
        config.groq_timeout_seconds,
        config.groq_chat_model,
        config.groq_vision_model,
        temperature=config.groq_temperature,
        max_completion_tokens=config.groq_max_completion_tokens,
        max_continuations=config.groq_max_continuations,
    ) if config.groq_api_key else MissingModelClient())
    tools = build_registry(SessionLocal, seed_demo)
    application.state.financial_tools = tools
    application.state.model_client = selected_model
    application.state.orchestrator = AIOrchestrator(selected_model, tools, config.max_tool_rounds, config.groq_chat_model)
    application.state.vision_service = VisionService(selected_model, config.max_image_bytes)
    application.state.audio_service = AudioService(selected_model, config.groq_transcription_model, config.max_audio_bytes)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Dev-User-ID", "X-User-Authorized"],
    )

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": "Request validation failed."}})

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        logger.error("unhandled_request_error type=%s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "The request could not be completed."}})

    application.include_router(health.router)
    application.include_router(chat.router)
    application.include_router(finance.router)
    application.include_router(vision.router)
    application.include_router(audio.router)
    application.include_router(memory.router)
    return application


app = create_app()
