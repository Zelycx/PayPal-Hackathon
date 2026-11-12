# Ellie Android Client

The first Android client is a small Kotlin and Jetpack Compose chat app. It uses the existing FastAPI chat contract only:

- `POST /api/v1/chat` with `{ "message": "...", "conversation_id": "optional-id" }`
- response fields `answer` and `conversation_id`
- `GET /api/v1/chat/{conversation_id}` to restore the most recent saved conversation

Development requests send `X-Dev-User-ID: ellie-android`. The backend accepts this header without an API key only when `APP_ENV=development` and `APP_API_KEY` is blank. The app does not contain a Groq key, app API key, or other private credential. Production's shared `X-API-Key` mode is intentionally unsupported in the Android app; add per-user sign-in/token authentication before production use.

No local finance fixtures or account connections are created by the Android app. To keep backend development requests from seeding its fictional fixtures while testing this client, set `DEMO_DATA_ENABLED=false` in the backend `.env`. The backend still needs `GROQ_API_KEY` set on the server to generate real Ellie responses; that key never belongs in this Android project.

## Android Studio

1. Open the `android-client` folder in Android Studio and allow Gradle Sync to finish.
2. Start an Android emulator from Device Manager. The emulator build defaults to `http://10.0.2.2:8000`.
3. Start the backend from the project root in another terminal:

   ```bat
   python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

4. Select the `app` run configuration and the emulator, then press Run.
5. In the app, use the connection button to select emulator or physical-device mode. For a physical phone, bind FastAPI to `0.0.0.0`, put the computer and phone on the same network, and enter the computer's local address, for example `http://192.168.1.25:8000`. Allow the port through the Windows firewall if prompted.

For a development conversation backed by real Groq responses, set `GROQ_API_KEY` in the backend `.env` only. Keep `APP_API_KEY` blank for local app testing. On startup, the app retrieves its last conversation from the backend; “New chat” starts another conversation without deleting saved server history. The backend has no conversation-list endpoint, so this first client resumes only the last conversation.

The UI follows the device's light/dark setting. It displays backend text as plain text and surfaces connection, timeout, authentication, and empty-response errors.

## Build and tests on Windows

From a CMD prompt:

```bat
cd C:\Users\Yor\Desktop\Projects\Satella\android-client
gradlew.bat assembleDebug
gradlew.bat testDebugUnitTest
```

The unit tests verify the JSON body, development user header, conversation ID reuse, history retrieval, authentication errors, empty replies, and timeouts. They use a local mock HTTP server and do not call Groq.

The emulator URL is defined by `ellieEmulatorUrl` in `gradle.properties`. The physical-device default is `elliePhysicalDeviceUrl`; it can also be changed in the app's backend settings. To change either value at build time, pass the corresponding Gradle property, for example `gradlew.bat assembleDebug -PelliePhysicalDeviceUrl=http://192.168.1.25:8000`.
