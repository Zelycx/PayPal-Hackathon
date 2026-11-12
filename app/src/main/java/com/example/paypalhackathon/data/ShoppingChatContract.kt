package com.example.paypalhackathon.data

import org.json.JSONArray
import org.json.JSONObject

internal const val MAX_SHOPPING_CHAT_MESSAGE_LENGTH = 1_200
internal const val MAX_SHOPPING_CHAT_HISTORY_TURNS = 8
internal const val MAX_SHOPPING_CHAT_ANSWER_LENGTH = 3_000

/** Builds the exact guest-authenticated POST /shopping/chat payload. */
internal fun createShoppingChatPayload(
    message: String,
    context: JSONObject,
    history: List<ShoppingChatTurn>,
): JSONObject {
    val question = message.trim()
    if (question.isEmpty()) {
        throw BackendApiException(null, "Enter a question for the assistant.")
    }
    if (question.length > MAX_SHOPPING_CHAT_MESSAGE_LENGTH) {
        throw BackendApiException(null, "Messages must be 1,200 characters or fewer.")
    }

    val recentHistory = JSONArray()
    history.takeLast(MAX_SHOPPING_CHAT_HISTORY_TURNS).forEach { turn ->
        if (turn.role !in setOf("user", "assistant")) return@forEach
        val content = turn.content.trim().take(MAX_SHOPPING_CHAT_MESSAGE_LENGTH)
        if (content.isNotEmpty()) {
            recentHistory.put(JSONObject().put("role", turn.role).put("content", content))
        }
    }

    return JSONObject()
        .put("message", question)
        .put("context", context)
        .put("history", recentHistory)
}

/** Rejects empty or malformed success payloads so they cannot look like AI answers. */
internal fun parseShoppingChatAnswer(response: JSONObject): String {
    val answer = response.optString("answer").trim()
    if (answer.isEmpty()) {
        throw BackendApiException(null, "The assistant returned an empty response.")
    }
    if (answer.length > MAX_SHOPPING_CHAT_ANSWER_LENGTH) {
        throw BackendApiException(null, "The assistant response was longer than expected.")
    }
    return answer
}
