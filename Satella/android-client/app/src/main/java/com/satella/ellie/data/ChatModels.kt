package com.satella.ellie.data

import com.satella.ellie.BuildConfig
import java.util.UUID

data class ChatMessage(
    val id: String = UUID.randomUUID().toString(),
    val role: String,
    val content: String,
)

data class ChatReply(
    val answer: String,
    val conversationId: String,
)

data class ConversationHistory(
    val conversationId: String,
    val messages: List<ChatMessage>,
)

enum class BackendTarget(val label: String) {
    EMULATOR("Android emulator"),
    PHYSICAL_DEVICE("Physical device"),
}

data class BackendConnection(
    val target: BackendTarget,
    val physicalDeviceUrl: String,
) {
    val baseUrl: String
        get() = when (target) {
            BackendTarget.EMULATOR -> BuildConfig.EMULATOR_BASE_URL
            BackendTarget.PHYSICAL_DEVICE -> physicalDeviceUrl
        }.trim().trimEnd('/')
}
