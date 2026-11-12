package com.example.paypalhackathon

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.res.ColorStateList
import android.graphics.Bitmap
import android.graphics.Color
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
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
import com.example.paypalhackathon.data.PurchaseBudgetInput
import com.example.paypalhackathon.data.PurchaseBudgetParser
import com.example.paypalhackathon.data.ShoppingResponse
import com.example.paypalhackaton.ChatHeadService
import java.util.Locale

class MainActivity : AppCompatActivity() {

    private lateinit var bubbleButton: Button
    private lateinit var menuButton: Button
    private lateinit var menuPanel: LinearLayout
    private lateinit var paypalBalance: TextView
    private lateinit var transactionHistoryButton: Button
    private lateinit var apiStatus: TextView
    private lateinit var apiResult: TextView
    private lateinit var apiProgress: ProgressBar
    private lateinit var purchaseSection: LinearLayout
    private lateinit var purchasePreview: ImageView
    private lateinit var purchaseBudgetAmount: EditText
    private lateinit var purchaseBudgetCurrency: EditText
    private lateinit var analyzePurchaseButton: Button
    private lateinit var cancelPurchaseButton: Button
    private val apiClient by lazy { BackendApiClient.get(applicationContext) }
    private var requestInProgress = false
    private var purchaseAnalysisActive = false
    private var purchaseCancellationRequested = false
    private var selectedPurchaseBitmap: Bitmap? = null

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
        menuButton = findViewById(R.id.menu_button)
        menuPanel = findViewById(R.id.balance_box)
        paypalBalance = findViewById(R.id.paypal_balance)
        transactionHistoryButton = findViewById(R.id.page_switch_button)
        apiStatus = findViewById(R.id.api_status)
        apiResult = findViewById(R.id.api_result)
        apiProgress = findViewById(R.id.api_progress)
        purchaseSection = findViewById(R.id.purchase_section)
        purchasePreview = findViewById(R.id.purchase_preview)
        purchaseBudgetAmount = findViewById(R.id.purchase_budget_amount)
        purchaseBudgetCurrency = findViewById(R.id.purchase_budget_currency)
        analyzePurchaseButton = findViewById(R.id.analyze_purchase_button)
        cancelPurchaseButton = findViewById(R.id.cancel_purchase_button)
        updateButton()
        bubbleButton.setOnClickListener { toggleBubbleMode() }
        findViewById<Button>(R.id.saved_image_button).setOnClickListener {
            openScreenshotPicker()
        }
        analyzePurchaseButton.setOnClickListener { analyzeSelectedPurchase() }
        cancelPurchaseButton.setOnClickListener { cancelPurchaseAnalysis() }

        menuButton.setOnClickListener {
            val opening = menuPanel.visibility != View.VISIBLE
            menuPanel.visibility = if (opening) View.VISIBLE else View.GONE
            if (opening) loadSandboxWallet()
        }
        transactionHistoryButton.setOnClickListener {
            startActivity(Intent(this, TransactionHistory::class.java))
        }

        if (intent?.action == null) {
            apiClient.ensureGuestSession { result ->
                if (isFinishing || isDestroyed || requestInProgress) return@ensureGuestSession
                result.onSuccess {
                    setStatus("Guest session ready. Choose a saved screenshot or open PayPal Sandbox.")
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
            startService(
                Intent(this, ChatHeadService::class.java)
                    .setAction(ChatHeadService.ACTION_ACTIVATE),
            )
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

        updateButton()
    }

    override fun onStop() {
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
            ACTION_OPEN_SHOPPING -> openShoppingAssistant()
            ACTION_OPEN_WALLET -> loadSandboxWallet()
            ACTION_TOGGLE_BUBBLE -> toggleBubbleMode()
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
        if (requestInProgress) return
        setStatus("Choose a saved JPEG, PNG, or WebP shopping screenshot.")
        screenshotPicker.launch("image/*")
    }

    /** The cart action opens this assistant view and transfers the confirmed crop to the Activity. */
    private fun openShoppingAssistant() {
        val confirmedCrop = SelectedScreenRegion.takeConfirmedBitmap()
        if (confirmedCrop == null) {
            showCachedShoppingResults()
            return
        }
        val previous = selectedPurchaseBitmap
        purchasePreview.setImageDrawable(null)
        if (previous !== confirmedCrop && previous != null && !previous.isRecycled) previous.recycle()
        selectedPurchaseBitmap = confirmedCrop
        purchasePreview.setImageBitmap(confirmedCrop)
        purchaseSection.visibility = View.VISIBLE
        analyzePurchaseButton.text = "Analyze Purchase"
        analyzePurchaseButton.isEnabled = true
        apiResult.text = ""
        setStatus("Selected crop ready. Set an optional one-time spending limit, then tap Analyze Purchase.")
    }

    private fun analyzeSelectedPurchase() {
        if (requestInProgress) return
        val bitmap = selectedPurchaseBitmap
        if (bitmap == null || bitmap.isRecycled || bitmap.width <= 0 || bitmap.height <= 0) {
            setStatus("No usable crop is available. Select a screen region again.")
            return
        }

        val amountText = purchaseBudgetAmount.text.toString().trim()
        val currencyText = purchaseBudgetCurrency.text.toString().trim().uppercase(Locale.ROOT)
        val budget = try {
            PurchaseBudgetParser.parse(amountText, currencyText)
        } catch (error: IllegalArgumentException) {
            setStatus(error.message ?: "Check the optional spending limit.")
            return
        }

        apiResult.text = ""
        purchaseAnalysisActive = true
        purchaseCancellationRequested = false
        setBusy(true, "Identifying products and calculating the purchase…")
        apiClient.analyzePurchase(bitmap, budget) { result ->
            if (isFinishing || isDestroyed) {
                if (selectedPurchaseBitmap === bitmap) selectedPurchaseBitmap = null
                if (!bitmap.isRecycled) bitmap.recycle()
                return@analyzePurchase
            }
            if (purchaseCancellationRequested) {
                purchaseCancellationRequested = false
                purchaseAnalysisActive = false
                setBusy(false)
                setStatus("Analysis cancelled. The confirmed crop is still available to retry.")
                return@analyzePurchase
            }
            purchaseAnalysisActive = false
            setBusy(false)
            result.onSuccess { response ->
                purchasePreview.setImageDrawable(null)
                if (selectedPurchaseBitmap === bitmap) selectedPurchaseBitmap = null
                if (!bitmap.isRecycled) bitmap.recycle()
                purchaseSection.visibility = View.GONE
                renderShopping(response)
                val evaluation = response.purchaseEvaluation
                if (evaluation == null) {
                    setStatus("Shopping analysis completed, but the backend did not return a financial evaluation. Results are retained.")
                    apiResult.append("\n\nFinancial evaluation unavailable: the backend response contained no purchase evaluation.")
                } else {
                    setEvaluationStatus(evaluation)
                }
            }.onFailure { error ->
                analyzePurchaseButton.text = "Retry Analysis"
                setStatus(error.message ?: "Purchase analysis failed. The selected crop is still available to retry.")
            }
        }
    }

    private fun cancelPurchaseAnalysis() {
        if (!purchaseAnalysisActive || !requestInProgress) return
        purchaseCancellationRequested = true
        apiClient.cancelPurchaseAnalysis()
        setBusy(true, "Cancelling purchase analysis…")
        cancelPurchaseButton.visibility = View.GONE
    }

    private fun analyzeScreenshot(uri: Uri) {
        if (requestInProgress) return
        releaseSelectedPurchaseCrop()
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

    private fun releaseSelectedPurchaseCrop() {
        if (::purchasePreview.isInitialized) purchasePreview.setImageDrawable(null)
        val previous = selectedPurchaseBitmap
        selectedPurchaseBitmap = null
        if (previous != null && !previous.isRecycled) previous.recycle()
        if (::purchaseSection.isInitialized) purchaseSection.visibility = View.GONE
    }

    private fun showCachedShoppingResults() {
        val response = apiClient.cachedShoppingResponse()
        if (response == null) {
            setStatus("No shopping results yet. Choose a saved screenshot from the button above.")
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
                paypalBalance.text = wallet.balanceSummary()
                setStatus("Sandbox data loaded.")
            }.onFailure { error ->
                val detail = error.message ?: "PayPal Sandbox is unavailable."
                paypalBalance.text = "Unavailable"
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
        analyzePurchaseButton.isEnabled = !busy
        cancelPurchaseButton.visibility = if (busy && purchaseAnalysisActive) View.VISIBLE else View.GONE
        findViewById<Button>(R.id.saved_image_button).isEnabled = !busy
        message?.let(::setStatus)
    }

    private fun setStatus(message: String) {
        apiStatus.text = message
        apiStatus.setTextColor(Color.WHITE)
    }

    private fun setEvaluationStatus(evaluation: com.example.paypalhackathon.data.PurchaseEvaluation) {
        val color = when (evaluation.status) {
            "WITHIN_BUDGET_AND_BALANCE", "WITHIN_BUDGET", "WITHIN_BALANCE" -> Color.rgb(120, 220, 155)
            "OVER_BUDGET", "INSUFFICIENT_BALANCE", "BOTH_LIMITS_EXCEEDED" -> Color.rgb(255, 115, 115)
            "CURRENCY_MISMATCH" -> Color.rgb(255, 202, 105)
            else -> Color.rgb(255, 210, 125)
        }
        apiStatus.text = "${evaluation.displayStatus()} · PayPal Sandbox · advisory only"
        apiStatus.setTextColor(color)
    }

    override fun onDestroy() {
        if (purchaseAnalysisActive) apiClient.cancelPurchaseAnalysis()
        if (::purchasePreview.isInitialized) purchasePreview.setImageDrawable(null)
        if (!requestInProgress) {
            selectedPurchaseBitmap?.let { if (!it.isRecycled) it.recycle() }
            selectedPurchaseBitmap = null
        }
        super.onDestroy()
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
        const val ACTION_TOGGLE_BUBBLE = "com.example.paypalhackathon.TOGGLE_BUBBLE"
    }
}
