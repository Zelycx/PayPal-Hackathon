package com.satella.ellie.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.satella.ellie.BuildConfig
import com.satella.ellie.data.BackendConnection
import com.satella.ellie.data.BackendTarget
import com.satella.ellie.data.ChatMessage

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EllieChatScreen(state: EllieChatState, viewModel: EllieChatViewModel) {
    var draft by rememberSaveable { mutableStateOf("") }
    var showSettings by rememberSaveable { mutableStateOf(false) }
    val listState = rememberLazyListState()
    val busy = state.isSending || state.isLoadingHistory

    LaunchedEffect(state.messages.size, state.isSending, state.isLoadingHistory) {
        val lastIndex = state.messages.size + if (state.isSending) 0 else -1
        if (lastIndex >= 0) listState.scrollToItem(lastIndex)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("Ellie", fontWeight = FontWeight.SemiBold)
                        Text("Your financial companion", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                },
                actions = {
                    TextButton(onClick = { showSettings = true }) {
                        Text(if (state.connection.target == BackendTarget.EMULATOR) "Emulator" else "Device")
                    }
                    TextButton(onClick = viewModel::newConversation, enabled = !state.isSending) {
                        Text("New chat")
                    }
                },
            )
        },
    ) { contentPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding),
        ) {
            Column(
                modifier = Modifier
                    .fillMaxHeight()
                    .widthIn(max = 800.dp)
                    .fillMaxWidth()
                    .align(Alignment.Center)
                    .imePadding(),
            ) {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.weight(1f).fillMaxWidth(),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp, vertical = 18.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    if (state.messages.isEmpty()) {
                        item(key = "welcome") {
                            MessageBubble(ChatMessage(id = "welcome", role = "assistant", content = "Hi, I’m Ellie. What would you like help with?"))
                        }
                    } else {
                        items(state.messages, key = { it.id }) { message -> MessageBubble(message) }
                    }

                    if (state.isLoadingHistory) {
                        item(key = "history-loading") {
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                                CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                                Text("Loading your conversation…", Modifier.padding(start = 10.dp), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    } else if (state.isSending) {
                        item(key = "ellie-thinking") { ThinkingBubble() }
                    }
                }

                state.errorMessage?.let { message ->
                    ErrorNotice(message = message, onDismiss = viewModel::dismissError)
                }

                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.55f))
                MessageComposer(
                    value = draft,
                    enabled = !busy,
                    onValueChange = { draft = it },
                    onSend = {
                        val outgoing = draft.trim()
                        if (outgoing.isNotEmpty()) {
                            draft = ""
                            viewModel.sendMessage(outgoing)
                        }
                    },
                )
            }
        }
    }

    if (showSettings) {
        BackendSettingsDialog(
            connection = state.connection,
            onDismiss = { showSettings = false },
            onSave = { target, physicalUrl ->
                viewModel.saveConnection(target, physicalUrl)
                showSettings = false
            },
        )
    }
}

@Composable
private fun MessageBubble(message: ChatMessage) {
    val isUser = message.role == "user"
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Surface(
            color = if (isUser) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceContainerHigh,
            contentColor = if (isUser) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onSurface,
            shape = RoundedCornerShape(topStart = 20.dp, topEnd = 20.dp, bottomEnd = if (isUser) 6.dp else 20.dp, bottomStart = if (isUser) 20.dp else 6.dp),
            tonalElevation = 1.dp,
            modifier = Modifier.widthIn(max = 340.dp),
        ) {
            Column(Modifier.padding(horizontal = 15.dp, vertical = 11.dp)) {
                Text(
                    text = if (isUser) "You" else "Ellie",
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.primary,
                )
                Text(
                    text = message.content,
                    modifier = Modifier.padding(top = 3.dp),
                    style = MaterialTheme.typography.bodyLarge,
                    lineHeight = 23.sp,
                )
            }
        }
    }
}

@Composable
private fun ThinkingBubble() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Start,
    ) {
        CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
        Text("Ellie is responding…", Modifier.padding(start = 10.dp), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun ErrorNotice(message: String, onDismiss: () -> Unit) {
    Surface(
        color = MaterialTheme.colorScheme.errorContainer,
        contentColor = MaterialTheme.colorScheme.onErrorContainer,
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 8.dp),
    ) {
        Row(
            modifier = Modifier.padding(start = 14.dp, top = 8.dp, bottom = 8.dp, end = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(message, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = onDismiss) { Text("Dismiss") }
        }
    }
}

@Composable
private fun MessageComposer(
    value: String,
    enabled: Boolean,
    onValueChange: (String) -> Unit,
    onSend: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.Bottom,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            enabled = enabled,
            modifier = Modifier.weight(1f),
            placeholder = { Text("Message Ellie") },
            shape = RoundedCornerShape(24.dp),
            maxLines = 4,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(onSend = { onSend() }),
        )
        Button(
            onClick = onSend,
            enabled = enabled && value.isNotBlank(),
            modifier = Modifier.size(54.dp),
            shape = CircleShape,
        ) {
            Text("↑", fontSize = 25.sp, textAlign = TextAlign.Center)
        }
    }
}

@Composable
private fun BackendSettingsDialog(
    connection: BackendConnection,
    onDismiss: () -> Unit,
    onSave: (BackendTarget, String) -> Unit,
) {
    var target by remember(connection.target) { mutableStateOf(connection.target) }
    var physicalUrl by remember(connection.physicalDeviceUrl) { mutableStateOf(connection.physicalDeviceUrl) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Backend connection") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                TargetOption(
                    label = "Android emulator",
                    url = BuildConfig.EMULATOR_BASE_URL,
                    selected = target == BackendTarget.EMULATOR,
                    onClick = { target = BackendTarget.EMULATOR },
                )
                TargetOption(
                    label = "Physical device",
                    url = "Use your computer’s Wi-Fi address",
                    selected = target == BackendTarget.PHYSICAL_DEVICE,
                    onClick = { target = BackendTarget.PHYSICAL_DEVICE },
                )
                if (target == BackendTarget.PHYSICAL_DEVICE) {
                    OutlinedTextField(
                        value = physicalUrl,
                        onValueChange = { physicalUrl = it },
                        label = { Text("Backend URL") },
                        placeholder = { Text("http://192.168.1.25:8000") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Text(
                        "Run FastAPI on 0.0.0.0 and enter your computer’s local IP address.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        },
        confirmButton = { TextButton(onClick = { onSave(target, physicalUrl) }) { Text("Save") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun TargetOption(label: String, url: String, selected: Boolean, onClick: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(MaterialTheme.colorScheme.surfaceContainerLow).padding(horizontal = 10.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected = selected, onClick = onClick)
        Column(Modifier.padding(start = 4.dp)) {
            Text(label, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
            Text(url, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
