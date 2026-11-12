package com.satella.ellie.ui

import android.app.Application
import android.content.Context
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.satella.ellie.BuildConfig
import com.satella.ellie.data.BackendConnection
import com.satella.ellie.data.BackendException
import com.satella.ellie.data.BackendTarget
import com.satella.ellie.data.ChatMessage
import com.satella.ellie.data.EllieBackendClient
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class EllieChatState(
    val messages: List<ChatMessage> = emptyList(),
    val isSending: Boolean = false,
    val isLoadingHistory: Boolean = false,
    val errorMessage: String? = null,
    val connection: BackendConnection = BackendConnection(
        target = BackendTarget.EMULATOR,
        physicalDeviceUrl = BuildConfig.PHYSICAL_DEVICE_BASE_URL,
    ),
)

class EllieChatViewModel(application: Application) : AndroidViewModel(application) {
    private val preferences = application.getSharedPreferences("ellie_chat", Context.MODE_PRIVATE)
    private val backend = EllieBackendClient()
    private val _state = MutableStateFlow(
        EllieChatState(
            connection = BackendConnection(
                target = runCatching {
                    BackendTarget.valueOf(preferences.getString(KEY_TARGET, BackendTarget.EMULATOR.name)!!)
                }.getOrDefault(BackendTarget.EMULATOR),
                physicalDeviceUrl = preferences.getString(KEY_PHYSICAL_URL, BuildConfig.PHYSICAL_DEVICE_BASE_URL)
                    ?: BuildConfig.PHYSICAL_DEVICE_BASE_URL,
            ),
        ),
    )
    val state: StateFlow<EllieChatState> = _state.asStateFlow()

    private var conversationId: String? = preferences.getString(KEY_CONVERSATION_ID, null)

    init {
        if (!conversationId.isNullOrBlank()) restoreHistory()
    }

    fun sendMessage(text: String) {
        val message = text.trim()
        if (message.isEmpty() || _state.value.isSending || _state.value.isLoadingHistory) return

        _state.update {
            it.copy(messages = it.messages + ChatMessage(role = "user", content = message), isSending = true, errorMessage = null)
        }
        viewModelScope.launch {
            try {
                val current = _state.value
                val reply = backend.sendMessage(
                    baseUrl = current.connection.baseUrl,
                    userId = BuildConfig.DEVELOPMENT_USER_ID,
                    message = message,
                    conversationId = conversationId,
                )
                conversationId = reply.conversationId
                preferences.edit().putString(KEY_CONVERSATION_ID, conversationId).apply()
                _state.update {
                    it.copy(messages = it.messages + ChatMessage(role = "assistant", content = reply.answer), isSending = false)
                }
            } catch (error: Exception) {
                _state.update { it.copy(isSending = false, errorMessage = error.toUserMessage()) }
            }
        }
    }

    fun newConversation() {
        if (_state.value.isSending) return
        conversationId = null
        preferences.edit().remove(KEY_CONVERSATION_ID).apply()
        _state.update { it.copy(messages = emptyList(), errorMessage = null, isLoadingHistory = false) }
    }

    fun saveConnection(target: BackendTarget, physicalUrl: String) {
        val normalizedPhysicalUrl = physicalUrl.trim().trimEnd('/')
        if (target == BackendTarget.PHYSICAL_DEVICE && !isValidBaseUrl(normalizedPhysicalUrl)) {
            _state.update { it.copy(errorMessage = "Enter a valid physical-device URL, such as http://192.168.1.25:8000.") }
            return
        }
        preferences.edit()
            .putString(KEY_TARGET, target.name)
            .putString(KEY_PHYSICAL_URL, normalizedPhysicalUrl)
            .apply()
        _state.update {
            it.copy(
                connection = BackendConnection(target, normalizedPhysicalUrl),
                errorMessage = null,
            )
        }
        if (!conversationId.isNullOrBlank()) restoreHistory()
    }

    fun dismissError() {
        _state.update { it.copy(errorMessage = null) }
    }

    private fun restoreHistory() {
        val id = conversationId ?: return
        if (_state.value.isLoadingHistory) return
        _state.update { it.copy(isLoadingHistory = true, errorMessage = null) }
        viewModelScope.launch {
            try {
                val current = _state.value
                val history = backend.getConversation(current.connection.baseUrl, BuildConfig.DEVELOPMENT_USER_ID, id)
                conversationId = history.conversationId
                _state.update { it.copy(messages = history.messages, isLoadingHistory = false, errorMessage = null) }
            } catch (error: Exception) {
                if (error is BackendException && error.httpStatus == 404) {
                    conversationId = null
                    preferences.edit().remove(KEY_CONVERSATION_ID).apply()
                    _state.update { it.copy(messages = emptyList(), isLoadingHistory = false, errorMessage = "Saved conversation not found. You can start a new chat.") }
                } else {
                    _state.update { it.copy(isLoadingHistory = false, errorMessage = error.toUserMessage()) }
                }
            }
        }
    }

    private fun isValidBaseUrl(value: String): Boolean {
        val uri = runCatching { Uri.parse(value) }.getOrNull() ?: return false
        return uri.scheme in setOf("http", "https") && !uri.host.isNullOrBlank()
    }

    private fun Exception.toUserMessage(): String = when (this) {
        is BackendException -> message ?: "The request could not be completed."
        else -> "Can't reach the backend. Check that FastAPI is running and the selected URL is correct."
    }

    companion object {
        private const val KEY_TARGET = "backend_target"
        private const val KEY_PHYSICAL_URL = "physical_backend_url"
        private const val KEY_CONVERSATION_ID = "conversation_id"
    }
}
