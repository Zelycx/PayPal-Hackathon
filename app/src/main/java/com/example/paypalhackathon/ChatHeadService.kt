
package com.example.paypalhackathon

import android.app.Service
import android.content.Intent
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.IBinder
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.widget.AppCompatImageView
import androidx.constraintlayout.widget.ConstraintLayout
import kotlin.math.abs
import android.content.BroadcastReceiver
import android.content.Context
import android.content.IntentFilter
import androidx.core.content.ContextCompat

class ChatHeadService : Service() {

    companion object {

        const val ACTION_STATE_CHANGED =
            "com.example.paypalhackathon.STATE_CHANGED"

        const val ACTION_ACTIVATE =
            "com.example.paypalhackathon.ACTIVATE"

        const val ACTION_APP_FOREGROUND =
            "com.example.paypalhackathon.APP_FOREGROUND"

        const val ACTION_APP_BACKGROUND =
            "com.example.paypalhackathon.APP_BACKGROUND"

        @Volatile
        var isRunning = false
            private set

        @Volatile
        var appInForeground = false
    }

    private val appVisibilityReceiver = object : BroadcastReceiver() {

        override fun onReceive(context: Context?, intent: Intent?) {

            when (intent?.action) {

                ACTION_APP_FOREGROUND -> {
                    appInForeground = true
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

    private var chatHeadParams: WindowManager.LayoutParams? = null
    private var chatWindow: View? = null

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

        ContextCompat.registerReceiver(
            this,
            appVisibilityReceiver,
            IntentFilter().apply {
                addAction(ACTION_APP_FOREGROUND)
                addAction(ACTION_APP_BACKGROUND)
            },
            ContextCompat.RECEIVER_NOT_EXPORTED
        )

        isRunning = true

        createChatHead()

        sendBroadcast(
            Intent(ACTION_STATE_CHANGED).setPackage(packageName)
        )
    }

    override fun onStartCommand(
        intent: Intent?,
        flags: Int,
        startId: Int
    ): Int {

        when (intent?.action) {

            ACTION_ACTIVATE -> {

                // IMPORTANT:
                // Force the bubble to appear immediately.
                appInForeground = false

                addChatHead()
            }

            ACTION_APP_FOREGROUND -> {

                appInForeground = true
                hideAllOverlays()
            }

            ACTION_APP_BACKGROUND -> {

                appInForeground = false
                showAllOverlays()
            }

            else -> {

                if (appInForeground) {
                    hideAllOverlays()
                } else {
                    addChatHead()
                }
            }
        }

        return START_STICKY
    }

    private fun createChatHead() {

        chatHead = AppCompatImageView(this).apply {

            setImageResource(
                R.drawable.chat_head_placeholder
            )

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

        if (!chatHeadAdded) {

            chatHeadParams?.let {

                windowManager.addView(
                    chatHead,
                    it
                )

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

            windowManager.updateViewLayout(
                chatHead,
                params
            )
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

                setColor(
                    Color.rgb(190, 35, 35)
                )
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

        windowManager.addView(
            target,
            params
        )

        dropTargetAdded = true
    }

    private fun isOverDropTarget(
        x: Float,
        y: Float
    ): Boolean {

        val centerX = screenWidth() / 2f

        val centerY =
            screenHeight() - dp(35f) - dp(36f)

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
            .inflate(
                R.layout.float_window,
                null
            ) as ConstraintLayout

        // ACTION BUTTONS

        val cart = container.findViewById<ImageView>(R.id.cart)
        val selector = container.findViewById<ImageView>(R.id.selector)
        val wallet = container.findViewById<ImageView>(R.id.wallet)

        cart.setImageResource(R.drawable.u_cart)
        selector.setImageResource(R.drawable.u_selector)
        wallet.setImageResource(R.drawable.u_wallet)

        // ACTIVE / INACTIVE COLORS

        val activeColor = Color.rgb(255, 165, 0)

        fun updateIcon(icon: ImageView, active: Boolean) {

            if (active) {
                icon.setColorFilter(activeColor)
            } else {
                icon.clearColorFilter()
            }
        }

        // TRANSLUCENT SELECTOR OVERLAY

        val selectorOverlay = SelectorOverlay(this).apply {

            visibility = View.VISIBLE

            selectorEnabled = false

            isClickable = false
            isFocusable = false
        }

        container.addView(
            selectorOverlay,
            0,
            ConstraintLayout.LayoutParams(
                ConstraintLayout.LayoutParams.MATCH_PARENT,
                ConstraintLayout.LayoutParams.MATCH_PARENT
            )
        )

        cart.bringToFront()
        selector.bringToFront()
        wallet.bringToFront()

        // INFORMATION BOXES

        val cartBox =
            container.findViewById<LinearLayout>(R.id.cart_box)

        val walletBox =
            container.findViewById<LinearLayout>(R.id.wallet_box)

        val cartInfo =
            container.findViewById<TextView>(R.id.cart_info)

        val walletInfo =
            container.findViewById<TextView>(R.id.wallet_info)

        // TRACK OPENING ORDER

        val openBoxes = mutableListOf<View>()

        // POSITION BOXES

        fun updateBoxPositions() {

            container.post {

                var offset = 0f

                for (box in openBoxes) {

                    box.translationY = offset

                    offset += box.height.toFloat()
                }
            }
        }

        // OPEN / CLOSE BOX

        fun toggleBox(box: View) {

            if (box.visibility == View.VISIBLE) {

                box.visibility = View.GONE

                openBoxes.remove(box)

            } else {

                box.visibility = View.VISIBLE

                openBoxes.remove(box)
                openBoxes.add(box)
            }

            updateBoxPositions()
        }

        // SELECTOR BUTTON

        selector.setOnClickListener {

            selectorOverlay.selectorEnabled =
                !selectorOverlay.selectorEnabled

            selectorOverlay.isClickable =
                selectorOverlay.selectorEnabled

            updateIcon(
                selector,
                selectorOverlay.selectorEnabled
            )

            Toast.makeText(
                this@ChatHeadService,
                if (selectorOverlay.selectorEnabled)
                    "Selector activated"
                else
                    "Selector deactivated",
                Toast.LENGTH_SHORT
            ).show()
        }

        // CART BUTTON

        cart.isClickable = true
        cart.isEnabled = true

        cart.setOnClickListener {

            if (selectorOverlay.selectorEnabled) {

                toggleBox(cartBox)

            } else {

                cart.setImageResource(
                    R.drawable.avatar_placeholder
                )

                Toast.makeText(
                    this@ChatHeadService,
                    "Nothing selected. Please activate the selector first.",
                    Toast.LENGTH_LONG
                ).show()
            }
        }

        // WALLET BUTTON

        wallet.setOnClickListener {

            toggleBox(walletBox)

            updateIcon(
                wallet,
                walletBox.visibility == View.VISIBLE
            )
        }

        // FOOTER AVATAR

        chatHead.setImageResource(
            R.drawable.chat_foot_placeholder
        )

        // FULL-SCREEN TRANSLUCENT WINDOW

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            overlayType(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {

            gravity = Gravity.TOP or Gravity.START
        }

        chatWindow = container
        chatWindowOpen = true

        windowManager.addView(
            container,
            params
        )

        // KEEP BUBBLE ABOVE OVERLAY

        if (chatHeadAdded) {

            windowManager.removeView(chatHead)

            chatHeadAdded = false

            addChatHead()
        }
    }

    private fun hideChatWindow() {

        chatWindow?.let {

            windowManager.removeView(it)
        }

        chatWindow = null
        chatWindowOpen = false

        if (::chatHead.isInitialized) {

            chatHead.setImageResource(
                R.drawable.chat_head_placeholder
            )
        }
    }

    private fun hideAllOverlays() {

        removeDropTarget()

        chatWindow?.let {

            windowManager.removeView(it)
        }

        chatWindow = null
        chatWindowOpen = false

        if (::chatHead.isInitialized) {

            chatHead.setImageResource(
                R.drawable.chat_head_placeholder
            )
        }

        removeChatHead()
    }

    private fun showAllOverlays() {

        if (appInForeground) return

        addChatHead()
    }

    override fun onDestroy() {

        removeDropTarget()

        hideChatWindow()

        removeChatHead()

        isRunning = false

        sendBroadcast(
            Intent(ACTION_STATE_CHANGED).setPackage(packageName)
        )

        unregisterReceiver(appVisibilityReceiver)

        super.onDestroy()
    }
}
