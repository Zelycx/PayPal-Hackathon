package com.satella.ellie.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import java.net.SocketTimeoutException
import java.util.concurrent.TimeUnit

class BackendException(
    val httpStatus: Int? = null,
    message: String,
    cause: Throwable? = null,
) : Exception(message, cause)

class EllieBackendClient(
    private val httpClient: OkHttpClient = defaultHttpClient(),
) {
    suspend fun sendMessage(
        baseUrl: String,
        userId: String,
        message: String,
        conversationId: String?,
    ): ChatReply = withContext(Dispatchers.IO) {
        val payload = JSONObject().put("message", message)
        if (!conversationId.isNullOrBlank()) payload.put("conversation_id", conversationId)
        val body = payload.toString().toRequestBody(JSON_MEDIA_TYPE)
        val request = Request.Builder()
            .url("${baseUrl.trimEnd('/')}/api/v1/chat")
            .header("Accept", "application/json")
            .header("Content-Type", "application/json")
            .header("X-Dev-User-ID", userId)
            .post(body)
            .build()

        execute(request) { json ->
            val answer = json.nullableString("answer")?.trim().orEmpty()
            val id = json.nullableString("conversation_id")?.trim().orEmpty()
            if (answer.isBlank()) throw BackendException(message = "Ellie returned an empty reply. Please try again.")
            if (id.isBlank()) throw BackendException(message = "The backend returned an invalid conversation. Please start a new chat.")
            ChatReply(answer = answer, conversationId = id)
        }
    }

    suspend fun getConversation(baseUrl: String, userId: String, conversationId: String): ConversationHistory = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("${baseUrl.trimEnd('/')}/api/v1/chat/${conversationId.encodePathSegment()}")
            .header("Accept", "application/json")
            .header("X-Dev-User-ID", userId)
            .get()
            .build()

        execute(request) { json ->
            val id = json.nullableString("conversation_id")?.trim().orEmpty()
            if (id.isBlank()) throw BackendException(message = "The backend returned an invalid conversation.")
            val array = json.optJSONArray("messages")
                ?: throw BackendException(message = "The backend returned invalid conversation history.")
            val messages = buildList {
                for (index in 0 until array.length()) {
                    val item = array.optJSONObject(index) ?: continue
                    val role = item.nullableString("role")?.lowercase() ?: continue
                    val content = item.nullableString("content") ?: continue
                    if (role == "user" || role == "assistant") add(ChatMessage(role = role, content = content))
                }
            }
            ConversationHistory(conversationId = id, messages = messages)
        }
    }

    private inline fun <T> execute(request: Request, parse: (JSONObject) -> T): T {
        try {
            httpClient.newCall(request).execute().use { response ->
                val raw = response.body?.string().orEmpty()
                val json = runCatching { JSONObject(raw) }.getOrNull()
                if (!response.isSuccessful) {
                    val code = json?.optJSONObject("error")?.nullableString("code")
                        ?: json?.optJSONObject("detail")?.nullableString("code")
                    val backendMessage = json?.optJSONObject("error")?.nullableString("message")
                        ?: json?.optJSONObject("detail")?.nullableString("message")
                    val message = when {
                        response.code == 401 -> "The backend requires credentials. Local testing expects APP_API_KEY to be blank; production sign-in is not configured in this app."
                        response.code == 404 -> backendMessage ?: "This conversation was not found. Start a new chat."
                        response.code == 429 -> "Ellie is busy right now. Please try again shortly."
                        !backendMessage.isNullOrBlank() -> backendMessage
                        !code.isNullOrBlank() -> "The backend could not complete the request ($code)."
                        else -> "The backend returned an error (${response.code}). Please try again."
                    }
                    throw BackendException(httpStatus = response.code, message = message)
                }
                val responseJson = json ?: throw BackendException(message = "The backend returned an unreadable response.")
                return parse(responseJson)
            }
        } catch (error: BackendException) {
            throw error
        } catch (error: SocketTimeoutException) {
            throw BackendException(message = "The request timed out. Check the backend and try again.", cause = error)
        } catch (error: IOException) {
            throw BackendException(message = "Can't reach the backend. Check that FastAPI is running and the selected URL is correct.", cause = error)
        } catch (error: IllegalArgumentException) {
            throw BackendException(message = "The backend URL is invalid. Check the connection settings.", cause = error)
        }
    }

    private fun String.encodePathSegment(): String =
        java.net.URLEncoder.encode(this, Charsets.UTF_8.name()).replace("+", "%20")

    private fun JSONObject.nullableString(key: String): String? =
        if (isNull(key)) null else optString(key).takeUnless { it == "null" }

    companion object {
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()

        private fun defaultHttpClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(90, TimeUnit.SECONDS)
            .writeTimeout(15, TimeUnit.SECONDS)
            .callTimeout(105, TimeUnit.SECONDS)
            .build()
    }
}
