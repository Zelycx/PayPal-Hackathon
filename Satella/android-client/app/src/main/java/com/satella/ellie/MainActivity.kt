package com.satella.ellie

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.satella.ellie.ui.EllieChatScreen
import com.satella.ellie.ui.EllieChatViewModel
import com.satella.ellie.ui.theme.EllieTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            EllieTheme {
                val viewModel: EllieChatViewModel = viewModel()
                val state = viewModel.state.collectAsStateWithLifecycle().value
                EllieChatScreen(state = state, viewModel = viewModel)
            }
        }
    }
}
