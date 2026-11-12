
package com.example.paypalhackaton

import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Point
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.widget.AppCompatImageView
import androidx.core.content.ContextCompat
import com.example.paypalhackathon.LiveSelectionOverlay
import com.example.paypalhackathon.R
import com.example.paypalhackathon.MainActivity
import com.example.paypalhackathon.PayPalHackathonApp
import com.example.paypalhackathon.ScreenReader
import com.example.paypalhackathon.SelectedScreenRegion
import com.example.paypalhackathon.data.BackendApiClient
import com.example.paypalhackathon.data.PurchaseBudgetParser
import com.example.paypalhackathon.data.PurchaseBudgetInput
import com.example.paypalhackathon.data.ShoppingChatTurn
import com.example.paypalhackathon.data.ShoppingResponse
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min

class ChatHeadService : Service() {

    companion object {

        const val ACTION_STATE_CHANGED =
            "com.example.paypalhackaton.STATE_CHANGED"

        const val ACTION_ACTIVATE =
            "com.example.paypalhackaton.ACTIVATE"
        @Volatile
        var isRunning = false
            private set

        @Volatile
        var appInForeground = false

        private val sharedConversationHistory = mutableListOf<ShoppingChatTurn>()

        const val ACTION_APP_FOREGROUND =
            "com.example.paypalhackaton.APP_FOREGROUND"

        const val ACTION_APP_BACKGROUND =
            "com.example.paypalhackaton.APP_BACKGROUND"
    }

    private val appVisibilityReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                ACTION_APP_FOREGROUND -> {
                    appInForeground = true
                    cancelLiveSelection(restoreOverlays = false, message = null)
                    hideAllOverlays()
                }
                ACTION_APP_BACKGROUND -> {
                    appInForeground = false
                    showAllOverlays()
                }
            }
        }
    }

    private lateinit var windowManager: WindowManager
    private lateinit var chatHead: AppCompatImageView
    private val mainHandler = Handler(Looper.getMainLooper())
    private val selectionExecutor: ExecutorService = Executors.newSingleThreadExecutor()
    private val apiClient by lazy { BackendApiClient.get(applicationContext) }

    private var chatHeadParams: WindowManager.LayoutParams? = null
    private var chatWindow: View? = null
    private var chatWindowParams: WindowManager.LayoutParams? = null
    private var selectionPreview: ImageView? = null
    private var panelText: TextView? = null
    private var assistantStatus: TextView? = null
    private var assistantResult: TextView? = null
    private var assistantHistory: TextView? = null
    private var assistantProgress: ProgressBar? = null
    private var budgetAmountInput: EditText? = null
    private var budgetCurrencyInput: EditText? = null
    private var analyzeButton: Button? = null
    private var cancelAnalysisButton: Button? = null
    private var findStoresButton: Button? = null
    private var chatInput: EditText? = null
    private var sendChatButton: Button? = null
    private var selectedPreviewBitmap: Bitmap? = null
    private var pendingPurchaseBitmap: Bitmap? = null
    private var currentShoppingResponse: ShoppingResponse? = null
    private var currentWalletText: String? = null
    private var savedBudgetAmount = ""
    private var savedBudgetCurrency = ""
    private var hasConfirmedCrop = false
    private var lastAssistantStatus = "Select a screen region or open PayPal Sandbox."
    private var analysisInProgress = false
    private var chatInProgress = false
    private var operationGeneration = 0
    private val conversationHistory: MutableList<ShoppingChatTurn>
        get() = sharedConversationHistory
    private var selectionOverlay: LiveSelectionOverlay? = null
    private var selectionSnapshot: Bitmap? = null
    private var selectionFrameListener: ScreenReader.FrameListener? = null
    private var selectionTimeout: Runnable? = null
    private var selectionFramesWithSameSize = 0
    private var previousSelectionFrameSize: Pair<Int, Int>? = null
    private var selectionGeneration = 0
    private var selectionInProgress = false
    private var selectionStartOrientation = Configuration.ORIENTATION_UNDEFINED

    private var chatHeadAdded = false
    private var chatWindowOpen = false
    private var dropTarget: TextView? = null
    private var dropTargetAdded = false

    private var initialX = 0
    private var initialY = 0
    private var initialTouchX = 0f
    private var initialTouchY = 0f

    private var isDragging = false

    private fun dp(value: Float): Int {
        return TypedValue.applyDimension(
            TypedValue.COMPLEX_UNIT_DIP,
            value,
            resources.displayMetrics
        ).toInt()
    }

    @Suppress("DEPRECATION")
    private fun overlayType(): Int {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            WindowManager.LayoutParams.TYPE_PHONE
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()

        appInForeground = PayPalHackathonApp.appInForeground

        windowManager =
            getSystemService(WINDOW_SERVICE) as WindowManager
        currentShoppingResponse = apiClient.cachedShoppingResponse()

        ContextCompat.registerReceiver(
            this,
            appVisibilityReceiver,
            IntentFilter().apply {
                addAction(ACTION_APP_FOREGROUND)
                addAction(ACTION_APP_BACKGROUND)
            },
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )

        createChatHead()

        isRunning = true

        sendBroadcast(Intent(ACTION_STATE_CHANGED).setPackage(packageName))

        if (appInForeground) {
            hideAllOverlays()
        }
    }

    override fun onStartCommand(
        intent: Intent?,
        flags: Int,
        startId: Int
    ): Int {

        when (intent?.action) {

            ACTION_ACTIVATE -> {
                appInForeground = false
                addChatHead()
            }

            ACTION_APP_FOREGROUND -> hideAllOverlays()

            ACTION_APP_BACKGROUND -> showAllOverlays()

            else -> {
                if (appInForeground) {
                    hideAllOverlays()
                }
            }
        }

        return START_STICKY
    }

    private fun createChatHead() {

        chatHead = AppCompatImageView(this).apply {
            setImageResource(R.drawable.chat_head_placeholder)
            scaleType = ImageView.ScaleType.CENTER_CROP
        }

        val params = WindowManager.LayoutParams(
            dp(60f),
            dp(60f),
            overlayType(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = 0
            y = dp(200f)
        }

        chatHeadParams = params

        @Suppress("ClickableViewAccessibility")
        chatHead.setOnTouchListener { _, event ->

            when (event.action) {

                MotionEvent.ACTION_DOWN -> {

                    initialX = params.x
                    initialY = params.y

                    initialTouchX = event.rawX
                    initialTouchY = event.rawY

                    isDragging = false

                    true
                }

                MotionEvent.ACTION_MOVE -> {

                    val dx = event.rawX - initialTouchX
                    val dy = event.rawY - initialTouchY

                    if (
                        abs(dx) > dp(8f) ||
                        abs(dy) > dp(8f)
                    ) {
                        if (!isDragging) {
                            isDragging = true
                            showDropTarget()
                        }
                    }

                    if (isDragging) {

                        params.x = (
                                initialX + dx.toInt()
                                ).coerceIn(
                                0,
                                screenWidth() - dp(60f)
                            )

                        params.y = (
                                initialY + dy.toInt()
                                ).coerceIn(
                                0,
                                screenHeight() - dp(60f)
                            )

                        windowManager.updateViewLayout(
                            chatHead,
                            params
                        )
                    }

                    true
                }

                MotionEvent.ACTION_UP -> {

                    if (isDragging) {

                        val droppedOnX = isOverDropTarget(
                            event.rawX,
                            event.rawY
                        )

                        removeDropTarget()

                        if (droppedOnX) {
                            stopSelf()
                        } else {
                            snapToEdge()
                        }

                    } else {
                        toggleChatWindow()
                    }

                    isDragging = false

                    true
                }

                MotionEvent.ACTION_CANCEL -> {

                    removeDropTarget()
                    snapToEdge()
                    isDragging = false

                    true
                }

                else -> false
            }
        }

        if (!appInForeground) {
            addChatHead()
        }
    }

    private fun screenWidth(): Int {
        return resources.displayMetrics.widthPixels
    }

    private fun screenHeight(): Int {
        return resources.displayMetrics.heightPixels
    }

    private fun addChatHead() {

        if (!chatHeadAdded && !appInForeground) {

            chatHeadParams?.let {
                windowManager.addView(chatHead, it)
                chatHeadAdded = true
            }
        }
    }

    private fun removeChatHead() {

        if (chatHeadAdded) {
            windowManager.removeView(chatHead)
            chatHeadAdded = false
        }
    }

    private fun snapToEdge() {

        val params = chatHeadParams ?: return

        val bubbleCenter = params.x + dp(30f)

        params.x = if (bubbleCenter < screenWidth() / 2) {
            0
        } else {
            screenWidth() - dp(60f)
        }

        params.y = params.y.coerceIn(
            0,
            screenHeight() - dp(60f)
        )

        if (chatHeadAdded) {
            windowManager.updateViewLayout(chatHead, params)
        }
    }

    private fun showDropTarget() {

        if (dropTargetAdded) return

        val target = TextView(this).apply {

            text = "✕"
            textSize = 28f
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)

            background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(Color.rgb(190, 35, 35))
            }
        }

        val params = WindowManager.LayoutParams(
            dp(72f),
            dp(72f),
            overlayType(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
            y = dp(35f)
        }

        dropTarget = target

        windowManager.addView(target, params)

        dropTargetAdded = true
    }

    private fun isOverDropTarget(
        x: Float,
        y: Float
    ): Boolean {

        val centerX = screenWidth() / 2f
        val centerY = screenHeight() - dp(35f) - dp(36f)

        return abs(x - centerX) < dp(65f) &&
                abs(y - centerY) < dp(65f)
    }

    private fun removeDropTarget() {

        dropTarget?.let {

            if (dropTargetAdded) {
                windowManager.removeView(it)
            }
        }

        dropTarget = null
        dropTargetAdded = false
    }

    private fun toggleChatWindow() {

        if (chatWindow == null) {

            chatHead.setImageResource(
                R.drawable.chat_foot_placeholder
            )

            showChatWindow()

        } else {

            hideChatWindow()
        }
    }

    private fun showChatWindow() {
        if (chatWindow != null) return

        val container = android.view.LayoutInflater
            .from(this)
            .inflate(R.layout.float_window, null)

        selectionPreview = container.findViewById<ImageView>(R.id.selection_preview)
        panelText = container.findViewById(R.id.panel_text)
        assistantStatus = container.findViewById(R.id.assistant_status)
        assistantResult = container.findViewById(R.id.analysis_result)
        assistantHistory = container.findViewById(R.id.assistant_history)
        assistantProgress = container.findViewById(R.id.assistant_progress)
        budgetAmountInput = container.findViewById(R.id.purchase_budget_amount)
        budgetCurrencyInput = container.findViewById(R.id.purchase_budget_currency)
        budgetAmountInput?.setText(savedBudgetAmount)
        budgetCurrencyInput?.setText(savedBudgetCurrency)
        analyzeButton = container.findViewById(R.id.analyze_purchase_button)
        cancelAnalysisButton = container.findViewById(R.id.cancel_analysis_button)
        findStoresButton = container.findViewById(R.id.find_stores_button)
        chatInput = container.findViewById(R.id.chat_input)
        sendChatButton = container.findViewById(R.id.send_chat_button)

        container.findViewById<View>(R.id.cart_button).setOnClickListener {
            openShoppingAssistant()
        }
        container.findViewById<View>(R.id.selector).setOnClickListener {
            startLiveSelection()
        }
        container.findViewById<View>(R.id.wallet).setOnClickListener {
            loadSandboxWallet()
        }
        analyzeButton?.setOnClickListener { analyzeSelectedPurchase() }
        cancelAnalysisButton?.setOnClickListener { cancelPurchaseAnalysis() }
        findStoresButton?.setOnClickListener {
            setAssistantStatus(
                "Product search is not connected. No listings or seller claims are being returned."
            )
        }
        container.findViewById<View>(R.id.panel_minimize).setOnClickListener {
            hideChatWindow()
        }
        container.findViewById<View>(R.id.panel_close).setOnClickListener {
            hideChatWindow()
        }
        sendChatButton?.setOnClickListener { sendChatMessage() }
        chatInput?.setOnTouchListener { view, event ->
            if (event.action == MotionEvent.ACTION_DOWN) {
                setPanelFocusable(true)
                view.requestFocus()
                view.post {
                    (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager)
                        .showSoftInput(view, InputMethodManager.SHOW_IMPLICIT)
                }
            }
            false
        }
        container.setOnTouchListener { _, event ->
            if (event.action == MotionEvent.ACTION_OUTSIDE) {
                dismissChatKeyboard()
            }
            false
        }

        chatHead.setImageResource(R.drawable.chat_foot_placeholder)
        val width = min(
            dp(380f),
            (screenWidth() - dp(24f)).coerceAtLeast(dp(240f))
        )
        val height = min(
            dp(600f),
            (screenHeight() - dp(96f)).coerceAtLeast(dp(360f))
        )
        val params = WindowManager.LayoutParams(
            width,
            height,
            overlayType(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                    WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.BOTTOM or Gravity.END
            x = dp(8f)
            y = dp(84f)
        }

        chatWindow = container
        chatWindowParams = params
        chatWindowOpen = true
        windowManager.addView(container, params)
        renderFloatingPanel()

        // Keep the bubble above the compact panel.
        if (chatHeadAdded) {
            windowManager.removeView(chatHead)
            chatHeadAdded = false
            addChatHead()
        }
    }

    private fun openShoppingAssistant() {
        currentWalletText = null
        SelectedScreenRegion.takeConfirmedBitmap()?.let { selected ->
            recycleBitmap(pendingPurchaseBitmap)
            pendingPurchaseBitmap = selected
            hasConfirmedCrop = true
            lastAssistantStatus = "Confirmed crop ready. Review the optional limit, then analyze."
        }
        currentShoppingResponse = currentShoppingResponse ?: apiClient.cachedShoppingResponse()
        chatWindowOpen = true
        if (chatWindow == null) showChatWindow() else renderFloatingPanel()
    }

    private fun analyzeSelectedPurchase() {
        if (analysisInProgress) return
        val crop = pendingPurchaseBitmap ?: SelectedScreenRegion.takeConfirmedBitmap()?.also {
            pendingPurchaseBitmap = it
            hasConfirmedCrop = true
        }
        if (crop == null || crop.isRecycled || crop.width <= 0 || crop.height <= 0) {
            setAssistantStatus("No confirmed screen crop is ready. Select a region first.")
            return
        }
        val budget = try {
            PurchaseBudgetParser.parse(
                budgetAmountInput?.text?.toString().orEmpty().trim(),
                budgetCurrencyInput?.text?.toString().orEmpty().trim().uppercase(java.util.Locale.ROOT),
            )
        } catch (error: IllegalArgumentException) {
            setAssistantStatus(error.message ?: "Check the optional spending limit.")
            return
        }

        analysisInProgress = true
        val generation = ++operationGeneration
        setAssistantStatus("Identifying products and evaluating the purchase…")
        renderFloatingPanel()
        apiClient.analyzePurchase(crop, budget) { result ->
            if (!isRunning || generation != operationGeneration) return@analyzePurchase
            analysisInProgress = false
            result.onSuccess { response ->
                currentShoppingResponse = response
                currentWalletText = null
                pendingPurchaseBitmap = null
                hasConfirmedCrop = false
                recycleBitmap(crop)
                lastAssistantStatus = if (response.requiresReview) {
                    "Analysis complete. Review uncertain fields and warnings."
                } else {
                    "Analysis complete · PayPal Sandbox comparison is advisory."
                }
            }.onFailure { error ->
                lastAssistantStatus =
                    error.message ?: "Analysis failed. The selected crop is available to retry."
            }
            renderFloatingPanel()
        }
    }

    private fun cancelPurchaseAnalysis() {
        if (!analysisInProgress) return
        operationGeneration++
        apiClient.cancelPurchaseAnalysis()
        analysisInProgress = false
        lastAssistantStatus = "Analysis cancelled. The selected crop is available to retry."
        renderFloatingPanel()
    }

    private fun loadSandboxWallet() {
        if (analysisInProgress || chatInProgress) return
        chatInProgress = true
        lastAssistantStatus = "Loading PayPal Sandbox connection, balances, and transactions…"
        renderFloatingPanel()
        apiClient.loadPayPalSandbox { result ->
            if (!isRunning) return@loadPayPalSandbox
            chatInProgress = false
            result.onSuccess { wallet ->
                currentWalletText = wallet.toDisplayText()
                lastAssistantStatus = "PayPal Sandbox data loaded."
            }.onFailure { error ->
                currentWalletText = "PayPal Sandbox unavailable.\n\n" +
                        (error.message ?: "The backend request failed.")
                lastAssistantStatus = "PayPal Sandbox data is unavailable."
            }
            renderFloatingPanel()
        }
    }

    private fun sendChatMessage() {
        if (chatInProgress || analysisInProgress) return
        val message = chatInput?.text?.toString()?.trim().orEmpty()
        if (message.isBlank()) {
            setAssistantStatus("Enter a question about this purchase.")
            return
        }
        val previousTurns = conversationHistory.takeLast(8).toList()
        conversationHistory += ShoppingChatTurn("user", message)
        while (conversationHistory.size > 40) conversationHistory.removeAt(0)
        chatInput?.text?.clear()
        dismissChatKeyboard()
        chatInProgress = true
        lastAssistantStatus = "Preparing a contextual response…"
        renderFloatingPanel()

        val context = currentShoppingResponse?.toChatContextJson() ?: org.json.JSONObject()
        val generation = ++operationGeneration
        apiClient.sendShoppingChat(message, context, previousTurns) { result ->
            if (!isRunning || generation != operationGeneration) return@sendShoppingChat
            chatInProgress = false
            result.onSuccess { answer ->
                conversationHistory += ShoppingChatTurn("assistant", answer)
                while (conversationHistory.size > 40) conversationHistory.removeAt(0)
                lastAssistantStatus = "Response ready."
            }.onFailure { error ->
                conversationHistory += ShoppingChatTurn(
                    "assistant",
                    "I couldn't complete that request: " + (error.message ?: "backend unavailable"),
                )
                while (conversationHistory.size > 40) conversationHistory.removeAt(0)
                lastAssistantStatus = "Assistant request failed. You can try again."
            }
            renderFloatingPanel()
        }
    }

    private fun renderFloatingPanel() {
        panelText?.text = when {
            hasConfirmedCrop -> "A confirmed screen region is ready."
            else -> "Choose an action"
        }
        selectionPreview?.apply {
            setImageBitmap(selectedPreviewBitmap)
            visibility = if (selectedPreviewBitmap == null) View.GONE else View.VISIBLE
        }
        assistantStatus?.text = lastAssistantStatus
        assistantProgress?.visibility = if (analysisInProgress || chatInProgress) View.VISIBLE else View.GONE
        analyzeButton?.apply {
            isEnabled = !analysisInProgress && hasConfirmedCrop
            text = if (currentShoppingResponse == null) "Analyze selected region" else "Analyze another region"
        }
        cancelAnalysisButton?.visibility = if (analysisInProgress) View.VISIBLE else View.GONE
        sendChatButton?.isEnabled = !chatInProgress && !analysisInProgress
        assistantResult?.text = currentWalletText
            ?: currentShoppingResponse?.toDisplayText().orEmpty()
        assistantHistory?.text = conversationHistory.joinToString("\n\n") { turn ->
            val speaker = if (turn.role == "user") "You" else "Assistant"
            "$speaker: ${turn.content}"
        }
    }

    private fun setAssistantStatus(message: String) {
        lastAssistantStatus = message
        assistantStatus?.text = message
    }

    private fun setPanelFocusable(focusable: Boolean) {
        val panel = chatWindow ?: return
        val params = chatWindowParams ?: return
        val flags = WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH or
                (if (focusable) 0 else WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE)
        if (params.flags == flags) return
        params.flags = flags
        try {
            windowManager.updateViewLayout(panel, params)
        } catch (_: RuntimeException) {
            // The panel may have been removed while the keyboard was closing.
        }
    }

    private fun dismissChatKeyboard() {
        val input = chatInput ?: return
        (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager)
            .hideSoftInputFromWindow(input.windowToken, 0)
        input.clearFocus()
        setPanelFocusable(false)
    }

    private fun saveBudgetInputs() {
        savedBudgetAmount = budgetAmountInput?.text?.toString().orEmpty()
        savedBudgetCurrency = budgetCurrencyInput?.text?.toString().orEmpty()
    }

    /** Starts selection from the existing ScreenReader session; never asks for new consent. */
    private fun startLiveSelection() {
        if (selectionInProgress || selectionOverlay != null) return
        if (analysisInProgress || chatInProgress) {
            showSelectionMessage("Wait for the current assistant request to finish.")
            return
        }

        selectionInProgress = true
        selectionStartOrientation = resources.configuration.orientation
        val generation = ++selectionGeneration
        try {
            selectionExecutor.execute {
                val availableFrame = try {
                    ScreenReader.getLatestFrame()
                } catch (_: RuntimeException) {
                    null
                }
                val available = availableFrame?.let {
                    val usable = it.width > 0 && it.height > 0 && !it.isRecycled
                    if (!it.isRecycled) it.recycle()
                    usable
                } ?: false

                mainHandler.post {
                    if (generation != selectionGeneration || !isRunning) return@post
                    if (!available) {
                        selectionInProgress = false
                        showSelectionMessage(
                            "Screen capture is not ready. Activate Bubble Mode and grant Screen Read permission first."
                        )
                        return@post
                    }
                    awaitFreshSelectionSnapshot(generation)
                }
            }
        } catch (_: RuntimeException) {
            selectionInProgress = false
            showSelectionMessage("Could not prepare screen selection.")
        }
    }

    /** Hides our own overlays, then retains two consecutive fresh captured frames. */
    private fun awaitFreshSelectionSnapshot(generation: Int) {
        if (generation != selectionGeneration || !selectionInProgress || !isRunning) return

        selectionFramesWithSameSize = 0
        previousSelectionFrameSize = null
        lateinit var listener: ScreenReader.FrameListener
        listener = ScreenReader.FrameListener { frame ->
            if (selectionFrameListener !== listener || generation != selectionGeneration || !selectionInProgress) {
                recycleBitmap(frame)
                return@FrameListener
            }
            if (resources.configuration.orientation != selectionStartOrientation) {
                recycleBitmap(frame)
                cancelLiveSelection(
                    restoreOverlays = true,
                    message = "Selection was cancelled because the screen rotated. Try again."
                )
                return@FrameListener
            }

            val size = frame.width to frame.height
            if (size == previousSelectionFrameSize) {
                selectionFramesWithSameSize++
            } else {
                previousSelectionFrameSize = size
                selectionFramesWithSameSize = 1
            }

            if (selectionFramesWithSameSize >= 2) {
                ScreenReader.removeFrameListener(listener)
                selectionFrameListener = null
                selectionTimeout?.let(mainHandler::removeCallbacks)
                selectionTimeout = null
                selectionSnapshot = frame
                showSelectionOverlay(generation)
            } else {
                recycleBitmap(frame)
            }
        }

        selectionFrameListener = listener
        ScreenReader.addFrameListener(listener)
        hideAllOverlays()

        val timeout = Runnable {
            if (generation == selectionGeneration && selectionFrameListener === listener) {
                cancelLiveSelection(
                    restoreOverlays = true,
                    message = "A fresh screen frame was not available. Try again while Screen Read is active."
                )
            }
        }
        selectionTimeout = timeout
        mainHandler.postDelayed(timeout, 3_500L)
    }

    private fun showSelectionOverlay(generation: Int) {
        if (generation != selectionGeneration || !selectionInProgress || !isRunning) {
            releaseSelectionSnapshot()
            return
        }
        val snapshot = selectionSnapshot
        val displaySize = realDisplaySize()
        if (snapshot == null || displaySize.x <= 0 || displaySize.y <= 0) {
            cancelLiveSelection(restoreOverlays = true, message = "The captured screen is no longer available.")
            return
        }
        val frameAspect = snapshot.width.toDouble() / snapshot.height
        val displayAspect = displaySize.x.toDouble() / displaySize.y
        if (abs(frameAspect - displayAspect) / displayAspect > 0.02) {
            cancelLiveSelection(
                restoreOverlays = true,
                message = "Screen Read captured an app window. Restart Bubble Mode and choose Entire screen for region selection."
            )
            return
        }

        val overlay = LiveSelectionOverlay(
            this,
            onConfirm = { selected -> confirmSelection(generation, selected) },
            onCancel = {
                cancelLiveSelection(restoreOverlays = true, message = null)
            }
        )
        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            overlayType(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                layoutInDisplayCutoutMode =
                    WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                setFitInsetsTypes(0)
            }
        }
        overlay.systemUiVisibility = (
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
                        View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                        View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                )

        var laidOutWidth = 0
        var laidOutHeight = 0
        overlay.addOnLayoutChangeListener { _, left, top, right, bottom, _, _, _, _ ->
            val currentWidth = right - left
            val currentHeight = bottom - top
            if (laidOutWidth == 0 || laidOutHeight == 0) {
                laidOutWidth = currentWidth
                laidOutHeight = currentHeight
            } else if (currentWidth != laidOutWidth || currentHeight != laidOutHeight) {
                mainHandler.post {
                    if (selectionOverlay === overlay) {
                        cancelLiveSelection(
                            restoreOverlays = true,
                            message = "Selection was cancelled because the screen size changed."
                        )
                    }
                }
            }
        }

        selectionOverlay = overlay
        try {
            windowManager.addView(overlay, params)
        } catch (_: RuntimeException) {
            selectionOverlay = null
            cancelLiveSelection(
                restoreOverlays = true,
                message = "Could not display the screen selection overlay."
            )
        }
    }

    private fun confirmSelection(
        generation: Int,
        selected: LiveSelectionOverlay.Selection
    ) {
        if (generation != selectionGeneration || !selectionInProgress) return
        val snapshot = selectionSnapshot ?: run {
            cancelLiveSelection(
                restoreOverlays = true,
                message = "The captured screen is no longer available. Try again."
            )
            return
        }
        if (selected.surfaceWidth <= 0 || selected.surfaceHeight <= 0) {
            cancelLiveSelection(restoreOverlays = true, message = "Select a valid screen region.")
            return
        }

        val rectangle = Rect(
            floor(selected.rectangle.left).toInt(),
            floor(selected.rectangle.top).toInt(),
            ceil(selected.rectangle.right).toInt(),
            ceil(selected.rectangle.bottom).toInt()
        )
        val displaySize = realDisplaySize()
        if (displaySize.x <= 0 || displaySize.y <= 0) {
            cancelLiveSelection(restoreOverlays = true, message = "Could not read the screen size.")
            return
        }
        val frameAspect = snapshot.width.toDouble() / snapshot.height
        val displayAspect = displaySize.x.toDouble() / displaySize.y
        if (abs(frameAspect - displayAspect) / displayAspect > 0.02) {
            cancelLiveSelection(
                restoreOverlays = true,
                message = "Selection was cancelled because the captured screen size changed. Choose Entire screen in Bubble Mode."
            )
            return
        }

        selectionSnapshot = null // The worker now owns this immutable snapshot.
        removeSelectionOverlay()
        selectionInProgress = true
        val displayWidth = displaySize.x
        val displayHeight = displaySize.y
        val screenLeft = selected.screenLeft
        val screenTop = selected.screenTop

        try {
            selectionExecutor.execute {
                var crop: Bitmap? = null
                var preview: Bitmap? = null
                try {
                    crop = ScreenReader.cropFrame(
                        snapshot,
                        rectangle,
                        displayWidth,
                        displayHeight,
                        screenLeft,
                        screenTop
                    )
                    if (crop != null) preview = makeSelectionPreview(crop)
                } catch (_: RuntimeException) {
                    // Report a clear UI error below; never crash the service.
                } finally {
                    recycleBitmap(snapshot)
                }

                val completedCrop = crop
                val completedPreview = preview
                mainHandler.post {
                    if (generation != selectionGeneration || !isRunning) {
                        recycleBitmap(completedCrop)
                        recycleBitmap(completedPreview)
                        return@post
                    }

                    selectionInProgress = false
                    if (completedCrop == null) {
                        recycleBitmap(completedPreview)
                        showSelectionMessage("That selection did not produce a valid image. Try a larger region.")
                    } else {
                        recycleBitmap(pendingPurchaseBitmap)
                        pendingPurchaseBitmap = null
                        currentWalletText = null
                        hasConfirmedCrop = true
                        SelectedScreenRegion.replace(completedCrop)
                        replaceSelectionPreview(completedPreview)
                        lastAssistantStatus = "Screen region selected. Open the cart to review and analyze it."
                        showSelectionMessage("Screen region selected and ready.")
                        renderFloatingPanel()
                    }
                    showAllOverlays()
                }
            }
        } catch (_: RuntimeException) {
            recycleBitmap(snapshot)
            selectionInProgress = false
            cancelLiveSelection(
                restoreOverlays = true,
                message = "Could not process the selected screen region."
            )
        }
    }

    private fun cancelLiveSelection(restoreOverlays: Boolean, message: String?) {
        selectionGeneration++
        selectionInProgress = false
        selectionFrameListener?.let(ScreenReader::removeFrameListener)
        selectionFrameListener = null
        selectionTimeout?.let(mainHandler::removeCallbacks)
        selectionTimeout = null
        selectionFramesWithSameSize = 0
        previousSelectionFrameSize = null
        removeSelectionOverlay()
        releaseSelectionSnapshot()

        if (message != null) showSelectionMessage(message)
        if (restoreOverlays && !appInForeground && isRunning) showAllOverlays()
    }

    private fun removeSelectionOverlay() {
        selectionOverlay?.let { overlay ->
            try {
                windowManager.removeView(overlay)
            } catch (_: IllegalArgumentException) {
                // It may already have been detached by a system window change.
            } catch (_: RuntimeException) {
                // Cleanup remains idempotent if WindowManager is shutting down.
            }
        }
        selectionOverlay = null
    }

    private fun releaseSelectionSnapshot() {
        val snapshot = selectionSnapshot
        selectionSnapshot = null
        recycleBitmap(snapshot)
    }

    private fun replaceSelectionPreview(preview: Bitmap?) {
        selectionPreview?.setImageDrawable(null)
        val previous = selectedPreviewBitmap
        selectedPreviewBitmap = preview
        selectionPreview?.apply {
            setImageBitmap(preview)
            visibility = if (preview == null) View.GONE else View.VISIBLE
        }
        if (previous !== preview) recycleBitmap(previous)
    }

    private fun clearSelectionPreviewView() {
        selectionPreview?.setImageDrawable(null)
        selectionPreview = null
    }

    private fun clearPanelViewReferences() {
        panelText = null
        assistantStatus = null
        assistantResult = null
        assistantHistory = null
        assistantProgress = null
        budgetAmountInput = null
        budgetCurrencyInput = null
        analyzeButton = null
        cancelAnalysisButton = null
        findStoresButton = null
        chatInput = null
        sendChatButton = null
        chatWindowParams = null
    }

    private fun makeSelectionPreview(source: Bitmap): Bitmap? {
        val longestEdge = max(source.width, source.height)
        if (longestEdge <= 0) return null
        val scale = min(1f, 256f / longestEdge)
        val width = max(1, (source.width * scale).toInt())
        val height = max(1, (source.height * scale).toInt())
        val scaled = Bitmap.createScaledBitmap(source, width, height, true)
        return if (scaled === source) scaled.copy(Bitmap.Config.ARGB_8888, false) else scaled
    }

    private fun realDisplaySize(): Point {
        val point = Point()
        @Suppress("DEPRECATION")
        windowManager.defaultDisplay.getRealSize(point)
        return point
    }

    private fun recycleBitmap(bitmap: Bitmap?) {
        if (bitmap != null && !bitmap.isRecycled) bitmap.recycle()
    }

    private fun showSelectionMessage(message: String) {
        setAssistantStatus(message)
        Toast.makeText(applicationContext, message, Toast.LENGTH_LONG).show()
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        if (selectionInProgress && newConfig.orientation != selectionStartOrientation) {
            cancelLiveSelection(
                restoreOverlays = true,
                message = "Selection was cancelled because the screen rotated. Try again."
            )
        }
    }

    private fun openMainActivity(action: String) {
        val intent = Intent(this, MainActivity::class.java)
            .setAction(action)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        try {
            startActivity(intent)
        } catch (_: Exception) {
            Toast.makeText(this, "Could not open the companion screen.", Toast.LENGTH_SHORT).show()
        }
    }

    private fun hideChatWindow() {
        saveBudgetInputs()
        dismissChatKeyboard()
        clearSelectionPreviewView()
        chatWindow?.let {
            try {
                windowManager.removeView(it)
            } catch (_: RuntimeException) {
                // The panel may already have been removed during a lifecycle transition.
            }
        }

        chatWindow = null
        chatWindowOpen = false
        clearPanelViewReferences()

        if (::chatHead.isInitialized) {
            chatHead.setImageResource(
                R.drawable.chat_head_placeholder
            )
        }
    }

    private fun hideAllOverlays() {
        saveBudgetInputs()
        removeDropTarget()
        dismissChatKeyboard()
        clearSelectionPreviewView()
        chatWindow?.let {
            try {
                windowManager.removeView(it)
            } catch (_: RuntimeException) {
                // The panel may already have been removed during a lifecycle transition.
            }
        }

        chatWindow = null
        clearPanelViewReferences()

        removeChatHead()
    }

    private fun showAllOverlays() {

        if (appInForeground || selectionInProgress) return

        addChatHead()

        if (chatWindowOpen) {
            showChatWindow()
        }
    }

    override fun onDestroy() {
        operationGeneration++
        if (analysisInProgress) apiClient.cancelPurchaseAnalysis()
        analysisInProgress = false
        chatInProgress = false
        // The close-target path calls stopSelf(), so this also ends capture
        // when Bubble Mode is closed without MainActivity being open.
        cancelLiveSelection(restoreOverlays = false, message = null)
        ScreenReader.stop(this)
        unregisterReceiver(appVisibilityReceiver)
        removeDropTarget()
        clearSelectionPreviewView()
        recycleBitmap(selectedPreviewBitmap)
        selectedPreviewBitmap = null
        recycleBitmap(pendingPurchaseBitmap)
        pendingPurchaseBitmap = null
        SelectedScreenRegion.clear()
        hideChatWindow()
        removeChatHead()
        selectionExecutor.shutdown()

        isRunning = false

        sendBroadcast(
            Intent(ACTION_STATE_CHANGED).setPackage(packageName)
        )

        super.onDestroy()
    }
}
