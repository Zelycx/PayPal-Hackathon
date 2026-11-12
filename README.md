# PayPal Hackathon Android App

The Android client connects to the FastAPI service in `backend/`. PayPal access is through the backend's Sandbox integration; PayPal and Groq credentials belong only in `backend/.env`.

## Start the backend

From the repository root in PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `backend/.env` with a Groq API key and PayPal Sandbox client ID and secret. Then start the service:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Use Sandbox credentials only. The backend provides `/health` for a basic availability check. The session store is in memory, so a backend restart expires existing guest sessions.

## Run Android

Open the repository root in Android Studio and run the `app` configuration. The default debug backend URL is `http://10.0.2.2:8000`, which reaches the development computer from the Android emulator.

For a physical Android device, connect the device and computer to the same LAN, allow inbound port 8000 through the computer firewall, then build/install with the computer's LAN address:

```powershell
.\gradlew.bat :app:installDebug -PPAYPAL_BACKEND_URL=http://192.168.1.20:8000
```

Replace `192.168.1.20` with the reachable address of the computer. The URL is a Gradle property, so it is not stored in Android source. Debug builds permit cleartext HTTP for local development; release builds require HTTPS.

In Bubble Mode, tap the selector icon to choose a saved JPEG, PNG, or WebP shopping screenshot. The app sends it to `POST /shopping/analyze` and displays the returned item, price, quantity, currency, totals, and warnings. Tap the cart icon to reopen the latest result. Tap the wallet icon to load the PayPal Sandbox connection, balances, and 30-day transactions.

This Android project currently has no in-app screen capture or crop implementation. The selector uses Android's image picker for a saved screenshot; it does not capture or crop another app's screen.

## API and backend notes

- Guest sessions are started with `POST /session/start`; the returned token is encrypted with an Android Keystore AES-GCM key and sent as a Bearer token on protected calls.
- Shopping uploads use multipart field `image`. The backend's public response schema is documented in [backend/SHOPPING_API.md](backend/SHOPPING_API.md).
- PayPal credentials and OAuth stay on the backend. The Android app contains no PayPal or Groq credentials and does not connect to live PayPal.
- The floating companion does not use voice or TTS.
