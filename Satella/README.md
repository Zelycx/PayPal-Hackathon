# AI Financial Companion Backend

A modular FastAPI backend for Ellie, an AI financial companion. She answers directly and concisely by default while preserving the financial caveats and evidence needed for accurate guidance. The backend combines a configurable Groq model adapter with deterministic `Decimal` calculations, read-only financial tools, persistent conversations, user-controlled memory, demo and manual financial records, vision, and audio transcription.

This is a local-development MVP, not a production-ready financial service. It does not connect to live bank or PayPal personal accounts, initiate payments, or make financial changes through AI tools.

## Current status

The FastAPI backend provides persistent chat and conversation history, user-controlled memory, deterministic financial calculations, read-only financial tools, manual CSV import, image analysis, and audio transcription. Groq supplies chat, vision, and transcription when a valid backend key is configured. Demo records are fictional; imported records are explicitly marked as manual.

The Android app currently provides chat and saved-conversation restoration through the backend. Finance, memory, image, and audio APIs are backend capabilities without Android screens or upload controls. The running Android app does not capture the screen, connect to PayPal, or speak responses aloud.

## Architecture

```text
Android chat client (chat/history only)
   │ REST/JSON
   ▼
FastAPI backend ── auth boundary ── SQLAlchemy / SQLite or PostgreSQL
   ├─ chat API ─ AI orchestrator ─ registered read-only tools ─ deterministic finance engine
   │               └─ provider-neutral model interface ─ Groq SDK
   ├─ finance and memory APIs
   ├─ vision API (backend endpoint; not wired into Android)
   └─ transcription API (backend endpoint; not wired into Android)
```

The model can only call functions registered in `app/ai/tool_registry.py`. Tool arguments are validated with Pydantic, each invocation opens its own database session, and no model-generated Python, SQL, shell command, or file path is executed. Financial arithmetic stays in the finance modules and uses `Decimal`.

The Android client currently calls the chat and conversation-history routes only. Finance, memory, vision, and audio routes are available through the backend API but are not wired into Android UI.

## Project structure

```text
app/
  ai/          model adapter, prompts, orchestration, tools, memory, vision, audio
  api/         chat, finance, health, memory, vision, and audio routes
  core/        settings, safe errors, authentication boundary, logging
  database/    SQLAlchemy engine and persistent models
  finance/     calculations, analysis, categorization, purchase advice
  providers/   demo, manual CSV, PayPal XS2A boundary
  schemas/     request and response models
tests/         deterministic unit and API tests; provider calls are mocked
.env.example   configuration names and non-secret defaults
run.py         optional local runner
```

## Requirements and Windows setup

Use Python 3.11 or later (the project was implemented with Python 3.12). From Windows CMD in the project folder:

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
copy .env.example .env
notepad .env
```

Put your Groq key only in the backend `.env` as `GROQ_API_KEY=...`. `.env` is ignored by Git. Do not put the key in Android or commit it. Leaving the key blank still lets the server and local finance endpoints start; chat, vision, and transcription return a safe configuration error until it is set.

Start the local development server:

```bat
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

or run `python run.py`. API docs: <http://127.0.0.1:8000/docs>.

The default database is `./ai_companion.db`. SQLite is used locally; `DATABASE_URL` can be changed to a SQLAlchemy PostgreSQL URL for deployment. The schema is PostgreSQL-compatible; production deployments should use migrations rather than relying on `create_all`.

## Configuration

Important settings are in `.env.example`:

| Setting | Purpose |
|---|---|
| `APP_ENV` | `development` or `production`; production refuses to start without `APP_API_KEY` |
| `APP_HOST`, `APP_PORT` | Uvicorn bind address and port |
| `APP_API_KEY` | Local shared API gate when set; required for production |
| `DEMO_DATA_ENABLED` | Enable fictional development fixtures; set `false` for Android testing without seeded financial records |
| `DATABASE_URL` | SQLite or PostgreSQL SQLAlchemy connection |
| `GROQ_API_KEY` | Server-side Groq credential |
| `GROQ_CHAT_MODEL` | Chat/tool model; default `qwen/qwen3.8-27b` |
| `GROQ_VISION_MODEL` | Vision model; default `qwen/qwen3.8-27b` |
| `GROQ_TRANSCRIPTION_MODEL` | Audio model; default `whisper-large-v3-turbo` |
| `GROQ_TIMEOUT_SECONDS` | Provider request timeout |
| `GROQ_TEMPERATURE` | Chat sampling temperature; defaults to `0.2` for steadier answers |
| `GROQ_MAX_COMPLETION_TOKENS` | Optional output cap; blank leaves the model's natural stop behavior enabled |
| `GROQ_MAX_CONTINUATIONS` | Continuation attempts if Groq reports a length cutoff; incomplete output is returned as an error, never a partial answer |
| `AI_PERSONALITY` | Initial companion tone; defaults to `ellie` |
| `MAX_CHAT_HISTORY_MESSAGES`, `MAX_TOOL_ROUNDS` | Model context and tool-call limits |
| `MAX_IMAGE_BYTES`, `MAX_AUDIO_BYTES` | Upload limits |
| `CORS_ORIGINS` | Comma-separated allowed browser origins |
| `PAYPAL_ENABLED` | Defaults off; does not grant PayPal access |

The selected default chat/vision model currently appears in Groq's official [vision docs](https://console.groq.com/docs/vision) and [tool-use model list](https://console.groq.com/docs/tool-use/overview). `whisper-large-v3-turbo` is listed by Groq's official [speech-to-text docs](https://console.groq.com/docs/speech-to-text). Model availability can change; update the environment setting after checking Groq's current model catalog.

Ellie's prompt targets 1–2 sentences and roughly 15–40 words for ordinary answers, using plain text by default. It permits longer focused explanations when requested or needed for financial accuracy and safety. No restrictive completion-token cap is set by default. The backend returns the model's answer as a JSON string and does not render Markdown; no frontend source is included in this project to inspect or configure.

## Local data and finance behavior

In development, the first financial or chat request for a user seeds a small fictional dataset and labels its records `simulated`. It includes PHP and USD accounts, income, purchases, a refund, a transfer, budgets, and an emergency-fund goal. Transactions are scoped by user ID; currencies are never added together. The `X-Dev-User-ID` header selects a local development user, defaulting to `demo-user`.

Manual import is available at `POST /api/v1/finance/import/csv`. CSV must be UTF-8 and include `date,description,amount,currency,kind`; `kind` is `income`, `expense`, `refund`, or `transfer`. Optional columns include `category`. The endpoint validates and stores user-submitted entries as manual data, rejects duplicates on repeat import, and does not let AI initiate imports. A user's direct category corrections are available at `PATCH /api/v1/finance/transactions/{id}/category`.

Implemented finance tools include account/balance retrieval, transaction lists, daily/category/spending/income summaries, budget use, savings progress, potentially recurring and unusually large patterns, trend limitations, purchase comparisons, savings-goal context, categorization suggestions, and a straight-line month-end spending estimate. Refunds reduce recorded expenses; transfers are excluded from net cash flow; pending expenses can be considered by purchase analysis. Predictions and unusual-pattern findings are explicitly labeled as estimates or candidates.

## API routes

| Method | Path | Description |
|---|---|---|
| `GET` | `/health`, `/api/v1/health` | Service/database status and model IDs; no credentials are returned |
| `POST` | `/api/v1/chat` | Create or continue a persistent conversation |
| `GET`, `DELETE` | `/api/v1/chat/{conversation_id}` | Retrieve or delete a conversation owned by the caller |
| `GET` | `/api/v1/finance/overview` | Currency-separated balances and current-month summary |
| `GET` | `/api/v1/finance/accounts` | Account balances and stale-data flags |
| `GET` | `/api/v1/finance/transactions` | Filtered transaction list |
| `GET` | `/api/v1/finance/budgets`, `/api/v1/finance/savings` | Budget and savings-goal status |
| `POST` | `/api/v1/finance/import/csv` | User-directed validated manual import |
| `PATCH` | `/api/v1/finance/transactions/{id}/category` | User category correction |
| `POST` | `/api/v1/vision/analyze` | Analyze one selected JPEG/PNG/WebP image; consent header required |
| `POST` | `/api/v1/audio/transcribe` | Transcribe supported audio; upload is not retained |
| `GET`, `POST`, `DELETE` | `/api/v1/memory` | List, approve/save/edit, disable/enable, or clear memories |
| `DELETE` | `/api/v1/memory/{memory_id}` | Delete one caller-owned memory |

Memory is separate from chat history. Saving or editing requires `approved: true`; disable state is persisted. The AI does not turn transactions into memories automatically.

For vision, an API client must send `X-User-Authorized: true` after the user selects or consents to an image. The current Android app does not provide this flow, and the backend does not implement Android `MediaProjection` or live-screen capture. Images sent to the endpoint are validated, normalized in memory to strip metadata, forwarded to Groq, and not persisted. Set `evaluate_purchase=true` in the multipart form to compare one clearly readable price/currency with recorded financial data; ambiguous prices produce an insufficient-information result.

## Test and validate

```bat
python -m pytest -q
```

Tests use local SQLite and mock the model client. No Groq key or PayPal account is needed. For a quick endpoint check after starting the server:

```bat
curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:8000/api/v1/finance/overview
curl.exe "http://127.0.0.1:8000/api/v1/finance/transactions?days=30"
```

To verify the configured Groq chat path, send a normal request (the secret stays in backend `.env`):

```bat
curl.exe -X POST http://127.0.0.1:8000/api/v1/chat -H "Content-Type: application/json" -d "{\"message\":\"Reply with a short greeting.\"}"
```

A successful response has an `answer`, `conversation_id`, and metadata. Without a valid key, the response reports `ai_not_configured` or a sanitized provider error. To exercise tool selection, ask “How much of my monthly food budget is left?” or “Can I afford a PHP 3,500 keyboard?” in `/docs`; the response lists sanitized tool names, success states, and durations.

## Android connection

For Android Studio's standard emulator, use `http://10.0.2.2:8000` as the development API base URL (`10.0.2.2` maps to the host machine's loopback). A physical phone must use the development computer's LAN address, with Uvicorn bound to `0.0.0.0` and local firewall access allowed. Keep cleartext HTTP confined to local development. A deployed app should use HTTPS and an authenticated per-user token flow. The current Android app sends JSON for chat and history only; it does not expose the backend's finance, memory, vision, or audio routes. Never send the Groq key from Android.

To run the Android app, start the backend using the instructions above, open the `android-client` folder in Android Studio, allow Gradle Sync to finish, start an emulator, and run the `app` configuration. The emulator URL defaults to `http://10.0.2.2:8000`. For a physical device, bind the backend to `0.0.0.0` and select physical-device mode in the app settings. On Windows, the build and client unit checks are:

```bat
cd android-client
gradlew.bat assembleDebug
gradlew.bat testDebugUnitTest
```

See [android-client/README.md](android-client/README.md) for the full device and connection setup.

## Security and privacy limits

- Development authentication is intentionally local: optional `APP_API_KEY` plus a caller-selectable `X-Dev-User-ID`. It is not suitable for an internet-facing service.
- Production currently requires one shared `APP_API_KEY` and maps it to a single `configured-client` identity. Add a verified per-user identity provider/JWT and authorization claims before serving multiple users. This gate is not user authentication.
- Rate limiting is an integration point for an API gateway/reverse proxy; this MVP has no distributed limiter. Apply per-user limits before public deployment.
- HTTPS termination, managed secrets, database encryption/backups, audit retention policy, migrations, and operational monitoring need deployment configuration. SQLite data is not encrypted at rest by this app.
- CORS defaults to local browser origins; configure exact deployed origins. CORS is not authentication.
- Demo records exist only in development and are fictional. Live data failures do not fall back to demo data in production.
- PayPal personal-account access is not implemented. The provider is a disabled boundary only; eligibility, TPP registration, certificates, and XS2A scope approval are external prerequisites. Merchant Reporting API access is not substituted for consumer wallet authorization.
- No bank connection, exchange-rate feed, contribution schedule, investment advice, or fraud detection is implemented. Currency conversions and savings completion dates are omitted without valid source data.
- Image content leaves the backend only when the endpoint is called and the request is authorized; Groq processes that content externally. Voice output/TTS is not implemented; Android can use native TextToSpeech.

The backend should not be described as production-ready until the identity, rate limiting, encryption, TLS, operational, and compliance work above is completed and independently reviewed.

## Android chat client

The initial Kotlin and Jetpack Compose app lives in [android-client](android-client/README.md). It uses the existing `/api/v1/chat` POST and conversation GET routes, sends only the development user header, and keeps Groq credentials on the Python backend. The app defaults to the emulator URL `http://10.0.2.2:8000` and has separate physical-device connection settings.

## Future integrations

These are not working features in the current app or backend and require separate implementation:

- Android live-screen capture and analysis, including a user-consented `MediaProjection` flow.
- PayPal personal-account authorization and live financial data. The current PayPal provider is only a disabled boundary; it does not connect an account.
- Text-to-speech integration. Ellie currently returns text only; Android does not read replies aloud.
- Android screens for finance, memory, image analysis, and audio transcription. Those functions currently require direct backend API requests.
- Live bank connections, exchange-rate data, production per-user sign-in, and operational controls such as distributed rate limiting and encrypted storage.
