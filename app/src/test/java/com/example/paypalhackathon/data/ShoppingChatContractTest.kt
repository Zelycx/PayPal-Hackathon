package com.example.paypalhackathon.data

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class ShoppingChatContractTest {
    @Test
    fun payloadUsesBackendFieldsAndOnlyMostRecentEightTurns() {
        val history = (1..10).map { index ->
            ShoppingChatTurn(if (index % 2 == 0) "assistant" else "user", "turn $index")
        }
        val context = JSONObject().put("screen_type", "cart")

        val payload = createShoppingChatPayload("  Can I afford this?  ", context, history)

        assertEquals("Can I afford this?", payload.getString("message"))
        assertEquals(context.toString(), payload.getJSONObject("context").toString())
        val sentHistory = payload.getJSONArray("history")
        assertEquals(8, sentHistory.length())
        assertEquals("turn 3", sentHistory.getJSONObject(0).getString("content"))
        assertEquals("turn 10", sentHistory.getJSONObject(7).getString("content"))
    }

    @Test
    fun parsesRealAnswerAndRejectsEmptyOrOversizedAnswers() {
        assertEquals("A useful answer", parseShoppingChatAnswer(JSONObject().put("answer", " A useful answer ")))
        assertThrows(BackendApiException::class.java) {
            parseShoppingChatAnswer(JSONObject().put("answer", "  "))
        }
        assertThrows(BackendApiException::class.java) {
            parseShoppingChatAnswer(JSONObject().put("answer", "a".repeat(MAX_SHOPPING_CHAT_ANSWER_LENGTH + 1)))
        }
    }

    @Test
    fun rejectsInvalidMessagesAndFiltersInvalidHistoryTurns() {
        assertThrows(BackendApiException::class.java) {
            createShoppingChatPayload("  ", JSONObject(), emptyList())
        }
        assertThrows(BackendApiException::class.java) {
            createShoppingChatPayload("a".repeat(MAX_SHOPPING_CHAT_MESSAGE_LENGTH + 1), JSONObject(), emptyList())
        }

        val payload = createShoppingChatPayload(
            "hello",
            JSONObject(),
            listOf(ShoppingChatTurn("system", "ignore"), ShoppingChatTurn("user", "prior")),
        )
        val history: JSONArray = payload.getJSONArray("history")
        assertEquals(1, history.length())
        assertEquals("user", history.getJSONObject(0).getString("role"))
    }
}
