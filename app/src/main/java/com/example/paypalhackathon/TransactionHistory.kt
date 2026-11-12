package com.example.paypalhackathon

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Color
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.example.paypalhackathon.data.BackendApiClient
import com.example.paypalhackaton.ChatHeadService

class TransactionHistory : AppCompatActivity() {
    private lateinit var menuButton: Button
    private lateinit var menuPanel: LinearLayout
    private lateinit var chatbotButton: Button
    private lateinit var bubbleButton: Button
    private lateinit var paypalBalance: TextView
    private lateinit var apiStatus: TextView
    private lateinit var apiResult: TextView
    private lateinit var apiProgress: ProgressBar

    private val apiClient by lazy { BackendApiClient.get(applicationContext) }
    private var requestInProgress = false
    private var receiverRegistered = false

    private val serviceStateReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == ChatHeadService.ACTION_STATE_CHANGED) updateButton()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.transaction_history)

        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main)) { view, insets ->
            val systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom)
            insets
        }

        menuButton = findViewById(R.id.menu_button)
        menuPanel = findViewById(R.id.balance_box)
        chatbotButton = findViewById(R.id.page_switch_button_chatbot)
        bubbleButton = findViewById(R.id.bubble_button)
        paypalBalance = findViewById(R.id.paypal_balance)
        apiStatus = findViewById(R.id.api_status)
        apiResult = findViewById(R.id.api_result)
        apiProgress = findViewById(R.id.api_progress)

        menuButton.setOnClickListener {
            menuPanel.visibility =
                if (menuPanel.visibility == View.VISIBLE) View.GONE else View.VISIBLE
        }
        chatbotButton.setOnClickListener {
            startActivity(
                Intent(this, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            )
            finish()
        }
        bubbleButton.setOnClickListener {
            startActivity(
                Intent(this, MainActivity::class.java)
                    .setAction(MainActivity.ACTION_TOGGLE_BUBBLE)
                    .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            )
        }

        updateButton()
        loadSandboxWallet()
    }

    override fun onStart() {
        super.onStart()
        if (!receiverRegistered) {
            ContextCompat.registerReceiver(
                this,
                serviceStateReceiver,
                IntentFilter(ChatHeadService.ACTION_STATE_CHANGED),
                ContextCompat.RECEIVER_NOT_EXPORTED,
            )
            receiverRegistered = true
        }
        updateButton()
    }

    override fun onStop() {
        if (receiverRegistered) {
            unregisterReceiver(serviceStateReceiver)
            receiverRegistered = false
        }
        super.onStop()
    }

    override fun onResume() {
        super.onResume()
        if (::bubbleButton.isInitialized) updateButton()
    }

    private fun loadSandboxWallet() {
        if (requestInProgress) return
        setBusy(true, "Loading PayPal Sandbox transactions...")
        apiResult.text = ""
        apiClient.loadPayPalSandbox { result ->
            if (isFinishing || isDestroyed) return@loadPayPalSandbox
            setBusy(false)
            result.onSuccess { wallet ->
                paypalBalance.text = wallet.balanceSummary()
                apiResult.text = wallet.toDisplayText()
                setStatus("Sandbox data loaded.")
            }.onFailure { error ->
                paypalBalance.text = "Unavailable"
                apiResult.text = "PayPal Sandbox data could not be loaded.\n\n" +
                    (error.message ?: "The Sandbox service is unavailable.")
                setStatus("PayPal Sandbox unavailable.")
            }
        }
    }

    private fun setBusy(busy: Boolean, message: String? = null) {
        requestInProgress = busy
        apiProgress.visibility = if (busy) View.VISIBLE else View.GONE
        bubbleButton.isEnabled = !busy
        message?.let(::setStatus)
    }

    private fun setStatus(message: String) {
        apiStatus.text = message
    }

    private fun updateButton() {
        if (!::bubbleButton.isInitialized) return
        val active = ChatHeadService.isRunning
        bubbleButton.backgroundTintList = android.content.res.ColorStateList.valueOf(
            Color.parseColor(if (active) "#777777" else "#FF9800"),
        )
        bubbleButton.setTextColor(Color.WHITE)
        bubbleButton.text = if (active) "Bubble Mode: ON" else "Bubble Mode"
    }
}
