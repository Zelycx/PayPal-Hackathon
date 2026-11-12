
package com.example.paypalhackaton

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
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.widget.AppCompatImageView
import com.example.paypalhackathon.R
import com.example.paypalhackathon.MainActivity
import com.example.paypalhackathon.ScreenReader
import kotlin.math.abs

class ChatHeadService : Service() {

    companion object {

        const val ACTION_STATE_CHANGED =
            "com.example.paypalhackaton.STATE_CHANGED"
        @Volatile
        var isRunning = false
            private set

        @Volatile
        var appInForeground = false

        const val ACTION_APP_FOREGROUND =
            "com.example.paypalhackaton.APP_FOREGROUND"

        const val ACTION_APP_BACKGROUND =
            "com.example.paypalhackaton.APP_BACKGROUND"
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

        windowManager =
            getSystemService(WINDOW_SERVICE) as WindowManager

        createChatHead()

        isRunning = true

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

        container.findViewById<View>(R.id.cart_button).setOnClickListener {
            openMainActivity(MainActivity.ACTION_OPEN_SHOPPING)
        }
        container.findViewById<View>(R.id.selector).setOnClickListener {
            openMainActivity(MainActivity.ACTION_SELECT_SCREENSHOT)
        }
        container.findViewById<View>(R.id.wallet).setOnClickListener {
            openMainActivity(MainActivity.ACTION_OPEN_WALLET)
        }

        // The footer avatar closes the overlay.
        chatHead.setImageResource(R.drawable.chat_foot_placeholder)

        chatHead.setOnClickListener {
            hideChatWindow()
        }

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

        chatHead.setImageResource(
            R.drawable.chat_foot_placeholder
        )

        windowManager.addView(container, params)

        // Keep the bubble above the overlay.
        if (chatHeadAdded) {
            windowManager.removeView(chatHead)
            chatHeadAdded = false

            addChatHead()
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

        removeChatHead()
    }

    private fun showAllOverlays() {

        if (appInForeground) return

        addChatHead()

        if (chatWindowOpen) {
            showChatWindow()
        }
    }

    override fun onDestroy() {
        // The close-target path calls stopSelf(), so this also ends capture
        // when Bubble Mode is closed without MainActivity being open.
        ScreenReader.stop(this)
        removeDropTarget()
        hideChatWindow()
        removeChatHead()

        isRunning = false

        sendBroadcast(
            Intent(ACTION_STATE_CHANGED).setPackage(packageName)
        )

        super.onDestroy()
    }
}
