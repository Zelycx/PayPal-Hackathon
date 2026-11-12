package com.satella.ellie.data

import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

class EllieBackendClientTest {
    private lateinit var server: MockWebServer
    private lateinit var backend: EllieBackendClient

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        backend = EllieBackendClient(
            OkHttpClient.Builder()
                .connectTimeout(1, TimeUnit.SECONDS)
                .readTimeout(1, TimeUnit.SECONDS)
                .writeTimeout(1, TimeUnit.SECONDS)
                .callTimeout(2, TimeUnit.SECONDS)
                .build(),
        )
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun postUsesBackendChatContractAndDevelopmentIdentityHeader() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"answer":"Hi!","conversation_id":"conversation-123"}"""))

        val reply = backend.sendMessage(server.url("/").toString(), "ellie-android", "Hello", null)
        val request = server.takeRequest()
        val body = JSONObject(request.body.readUtf8())

        assertEquals("POST", request.method)
        assertEquals("/api/v1/chat", request.path)
        assertEquals("ellie-android", request.getHeader("X-Dev-User-ID"))
        assertEquals("Hello", body.getString("message"))
        assertTrue(!body.has("conversation_id"))
        assertEquals("Hi!", reply.answer)
        assertEquals("conversation-123", reply.conversationId)
    }

    @Test
    fun continuedChatSendsConversationIdAndHistoryUsesGetRoute() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"answer":"Welcome back.","conversation_id":"conversation-123"}"""))
        backend.sendMessage(server.url("/").toString(), "ellie-android", "Again", "conversation-123")
        val postBody = JSONObject(server.takeRequest().body.readUtf8())
        assertEquals("conversation-123", postBody.getString("conversation_id"))

        server.enqueue(MockResponse().setBody("""{"conversation_id":"conversation-123","title":"Hello","personality":"ellie","messages":[{"role":"user","content":"Hello","created_at":"2026-11-10T00:00:00Z"},{"role":"assistant","content":"Hi!","created_at":"2026-11-10T00:00:01Z"}]}"""))
        val history = backend.getConversation(server.url("/").toString(), "ellie-android", "conversation-123")
        val request = server.takeRequest()
        assertEquals("GET", request.method)
        assertEquals("/api/v1/chat/conversation-123", request.path)
        assertEquals(2, history.messages.size)
        assertEquals("assistant", history.messages.last().role)
        assertEquals("Hi!", history.messages.last().content)
    }

    @Test
    fun backendAuthAndEmptyReplyBecomeClearErrors() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":{"code":"unauthorized","message":"Valid API credentials are required."}}"""))
        val authError = runCatching { backend.sendMessage(server.url("/").toString(), "ellie-android", "Hello", null) }.exceptionOrNull()
        assertTrue(authError is BackendException)
        assertTrue(authError?.message?.contains("APP_API_KEY") == true)

        server.enqueue(MockResponse().setBody("""{"answer":"  ","conversation_id":"conversation-123"}"""))
        val emptyError = runCatching { backend.sendMessage(server.url("/").toString(), "ellie-android", "Hello", null) }.exceptionOrNull()
        assertTrue(emptyError is BackendException)
        assertTrue(emptyError?.message?.contains("empty reply") == true)
    }

    @Test
    fun readTimeoutReturnsUserFacingTimeoutMessage() = runBlocking {
        server.enqueue(MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.NO_RESPONSE))
        val error = runCatching { backend.sendMessage(server.url("/").toString(), "ellie-android", "Hello", null) }.exceptionOrNull()
        assertTrue(error is BackendException)
        assertTrue(error?.message?.contains("timed out") == true)
    }
}
