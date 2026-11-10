
package com.example.paypalhackaton

import android.app.Service
import android.content.Intent
import android.graphics.PixelFormat
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
import androidx.appcompat.widget.AppCompatImageView
import com.example.paypalhackathon.R
import kotlin.math.abs

class ChatHeadService : Service() {

    private lateinit var windowManager: WindowManager
    private lateinit var chatHead: AppCompatImageView

    private var chatWindow: View? = null
    private var chatWindowParams: WindowManager.LayoutParams? = null

    private var initialX = 0
    private var initialY = 0
    private var initialTouchX = 0f
    private var initialTouchY = 0f

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

        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager

        createChatHead()
    }

    private fun createChatHead() {

        chatHead = AppCompatImageView(this).apply {
            setImageResource(R.drawable.chat_head_placeholder)
            scaleType = ImageView.ScaleType.CENTER_CROP
            setBackgroundColor(0xFFFF0000.toInt())
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

        @Suppress("ClickableViewAccessibility")
        chatHead.setOnTouchListener { _, event ->

            when (event.action) {

                MotionEvent.ACTION_DOWN -> {
                    initialX = params.x
                    initialY = params.y
                    initialTouchX = event.rawX
                    initialTouchY = event.rawY
                    true
                }

                MotionEvent.ACTION_MOVE -> {
                    params.x = initialX +
                            (event.rawX - initialTouchX).toInt()

                    params.y = initialY +
                            (event.rawY - initialTouchY).toInt()

                    windowManager.updateViewLayout(chatHead, params)
                    true
                }

                MotionEvent.ACTION_UP -> {
                    val moved =
                        abs(event.rawX - initialTouchX) > dp(10f) ||
                                abs(event.rawY - initialTouchY) > dp(10f)

                    if (!moved) {
                        toggleChatWindow()
                    }
                    true
                }

                else -> false
            }
        }

        windowManager.addView(chatHead, params)
    }

    private fun toggleChatWindow() {
        if (chatWindow == null) {
            showChatWindow()
        } else {
            hideChatWindow()
        }
    }

    private fun showChatWindow() {

        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(0xFF202020.toInt())
            setPadding(dp(16f), dp(12f), dp(16f), dp(16f))
        }

        val header = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }

        val title = TextView(this).apply {
            text = getString(R.string.floating_window_title)
            textSize = 18f
            setTextColor(0xFFFFFFFF.toInt())
        }

        val close = TextView(this).apply {
            text = "✕"
            textSize = 20f
            setTextColor(0xFFFFFFFF.toInt())
            gravity = Gravity.CENTER
            setPadding(dp(16f), dp(4f), dp(4f), dp(4f))
            setOnClickListener {
                hideChatWindow()
            }
        }

        header.addView(
            title,
            LinearLayout.LayoutParams(0, dp(40f), 1f)
        )

        header.addView(
            close,
            LinearLayout.LayoutParams(
                dp(40f),
                dp(40f)
            )
        )

        val message = TextView(this).apply {
            text = getString(R.string.floating_window_message)
            textSize = 15f
            setTextColor(0xFFFFFFFF.toInt())
            setPadding(0, dp(12f), 0, dp(12f))
        }

        container.addView(header)
        container.addView(message)

        val params = WindowManager.LayoutParams(
            dp(300f),
            dp(220f),
            overlayType(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.CENTER
        }

        chatWindow = container
        chatWindowParams = params

        windowManager.addView(container, params)
    }

    private fun hideChatWindow() {
        chatWindow?.let {
            windowManager.removeView(it)
        }

        chatWindow = null
        chatWindowParams = null
    }

    override fun onDestroy() {
        hideChatWindow()

        if (::chatHead.isInitialized) {
            windowManager.removeView(chatHead)
        }

        super.onDestroy()
    }
}
