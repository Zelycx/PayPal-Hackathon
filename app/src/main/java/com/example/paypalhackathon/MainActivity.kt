package com.example.paypalhackathon

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.res.ColorStateList
import android.graphics.Color
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.Button
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.example.paypalhackathon.data.BackendApiClient
import com.example.paypalhackathon.data.ShoppingResponse
import com.example.paypalhackaton.ChatHeadService

class MainActivity : AppCompatActivity() {

    private lateinit var bubbleButton: Button
    private lateinit var apiStatus: TextView
    private lateinit var apiResult: TextView
    private lateinit var apiProgress: ProgressBar
    private val apiClient by lazy { BackendApiClient.get(applicationContext) }
    private var requestInProgress = false

    private val screenshotPicker = registerForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        if (uri == null) {
            setStatus("No screenshot selected.")
        } else {
            analyzeScreenshot(uri)
        }
    }

    // Register before the activity is started so Android can restore the
    // result callback correctly if the activity is recreated during consent.
    private val screenCaptureConsentLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK && result.data != null) {
            startBubbleMode(result.resultCode, result.data)
        } else {
            startBubbleMode()
        }
    }

    private val serviceStateReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == ChatHeadService.ACTION_STATE_CHANGED) updateButton()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_main)

        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main)) { view, insets ->
            val systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom)
            insets
        }

        bubbleButton = findViewById(R.id.bubble_button)
        apiStatus = findViewById(R.id.api_status)
        apiResult = findViewById(R.id.api_result)
        apiProgress = findViewById(R.id.api_progress)
        updateButton()
        bubbleButton.setOnClickListener { toggleBubbleMode() }

        if (intent?.action == null) {
            apiClient.ensureGuestSession { result ->
                if (isFinishing || isDestroyed || requestInProgress) return@ensureGuestSession
                result.onSuccess {
                    setStatus("Guest session ready. Choose a screenshot with the selector or open PayPal Sandbox.")
                }.onFailure {
                    setStatus("Backend unavailable: " + (it.message ?: "could not start a guest session."))
                }
            }
        }

        handleAction(intent?.action)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleAction(intent.action)
    }

    /** Starts Bubble Mode; capture starts only when the consent data is present. */
    private fun startBubbleMode(resultCode: Int? = null, resultData: Intent? = null) {
        try {
            startService(Intent(this, ChatHeadService::class.java))
        } catch (e: Exception) {
            Toast.makeText(
                this,
                "Service error: ${e.message}",
                Toast.LENGTH_LONG
            ).show()
            return
        }

        if (resultCode != null && resultData != null) {
            try {
                ScreenReader.start(this, resultCode, resultData)
                Toast.makeText(this, "Bubble Mode activated", Toast.LENGTH_SHORT).show()
            } catch (_: Exception) {
                // Bubble Mode remains useful even if the capture service cannot start.
                ScreenReader.stop(this)
                Toast.makeText(
                    this,
                    "Bubble Mode activated. Screen Read is unavailable.",
                    Toast.LENGTH_LONG
                ).show()
            }
        } else {
            Toast.makeText(
                this,
                "Bubble Mode activated. Screen Read is unavailable.",
                Toast.LENGTH_LONG
            ).show()
        }
        finish()
    }

    override fun onStart() {
        super.onStart()
        ContextCompat.registerReceiver(
            this,
            serviceStateReceiver,
            IntentFilter(ChatHeadService.ACTION_STATE_CHANGED),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )

        ChatHeadService.appInForeground = true
        if (ChatHeadService.isRunning) {
            startService(Intent(this, ChatHeadService::class.java).setAction(ChatHeadService.ACTION_APP_FOREGROUND))
        }
        updateButton()
    }

    override fun onStop() {
        ChatHeadService.appInForeground = false
        if (ChatHeadService.isRunning) {
            startService(Intent(this, ChatHeadService::class.java).setAction(ChatHeadService.ACTION_APP_BACKGROUND))
        }
        unregisterReceiver(serviceStateReceiver)
        super.onStop()
    }

    override fun onResume() {
        super.onResume()
        if (::bubbleButton.isInitialized) updateButton()
    }

    private fun handleAction(action: String?) {
        when (action) {
            ACTION_SELECT_SCREENSHOT -> openScreenshotPicker()
            ACTION_OPEN_SHOPPING -> showCachedShoppingResults()
            ACTION_OPEN_WALLET -> loadSandboxWallet()
            else -> Unit
        }
    }

    private fun toggleBubbleMode() {
        if (ChatHeadService.isRunning) {
            ScreenReader.stop(this)
            stopService(Intent(this, ChatHeadService::class.java))
            Toast.makeText(this, "Bubble Mode deactivated", Toast.LENGTH_SHORT).show()
            return
        }

        if (!Settings.canDrawOverlays(this)) {
            val settingsIntent = Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName"),
            )
            startActivity(settingsIntent)
            Toast.makeText(this, "Please allow Display over other apps.", Toast.LENGTH_LONG).show()
            return
        }

        try {
            val projectionManager = getSystemService(MEDIA_PROJECTION_SERVICE)
                as MediaProjectionManager
            screenCaptureConsentLauncher.launch(
                projectionManager.createScreenCaptureIntent(),
            )
        } catch (error: Exception) {
            Toast.makeText(this, "Service error: ${error.message}", Toast.LENGTH_LONG).show()
        }
    }

    private fun openScreenshotPicker() {
        setStatus("Choose a saved JPEG, PNG, or WebP shopping screenshot.")
        screenshotPicker.launch("image/*")
    }

    private fun analyzeScreenshot(uri: Uri) {
        if (requestInProgress) return
        setBusy(true, "Analyzing screenshot…")
        apiResult.text = ""
        apiClient.analyzeShoppingImage(uri) { result ->
            if (isFinishing || isDestroyed) return@analyzeShoppingImage
            setBusy(false)
            result.onSuccess { response ->
                renderShopping(response)
                setStatus(if (response.requiresReview) "Analysis complete · review the warnings and uncertain fields." else "Analysis complete.")
            }.onFailure { error ->
                apiResult.text = ""
                setStatus(error.message ?: "Shopping analysis failed.")
            }
        }
    }

    private fun showCachedShoppingResults() {
        val response = apiClient.cachedShoppingResponse()
        if (response == null) {
            setStatus("No shopping results yet. Use the selector button to choose a saved screenshot.")
            apiResult.text = ""
            return
        }
        renderShopping(response)
        setStatus(if (response.requiresReview) "Shopping results · review requested." else "Shopping results")
    }

    private fun renderShopping(response: ShoppingResponse) {
        apiResult.text = response.toDisplayText()
    }

    private fun loadSandboxWallet() {
        if (requestInProgress) return
        setBusy(true, "Loading PayPal Sandbox connection, balances, and transactions…")
        apiResult.text = ""
        apiClient.loadPayPalSandbox { result ->
            if (isFinishing || isDestroyed) return@loadPayPalSandbox
            setBusy(false)
            result.onSuccess { wallet ->
                apiResult.text = wallet.toDisplayText()
                setStatus("Sandbox data loaded.")
            }.onFailure { error ->
                val detail = error.message ?: "PayPal Sandbox is unavailable."
                apiResult.text = "PayPal Sandbox data could not be loaded.\n\n" + detail +
                    "\n\nCheck the backend's Sandbox credentials and reporting permissions."
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
        bubbleButton.backgroundTintList = ColorStateList.valueOf(
            Color.parseColor(if (active) "#777777" else "#FF9800"),
        )
        bubbleButton.setTextColor(Color.WHITE)
        bubbleButton.text = if (active) "Bubble Mode: ON" else "Bubble Mode: OFF"
    }

    companion object {
        const val ACTION_SELECT_SCREENSHOT = "com.example.paypalhackathon.SELECT_SCREENSHOT"
        const val ACTION_OPEN_SHOPPING = "com.example.paypalhackathon.OPEN_SHOPPING"
        const val ACTION_OPEN_WALLET = "com.example.paypalhackathon.OPEN_WALLET"
    }
}
