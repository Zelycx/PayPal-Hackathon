
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
import android.widget.TextView
import androidx.appcompat.widget.AppCompatImageView
import com.example.paypalhackathon.R
import kotlin.math.abs

class ChatHeadService : Service() {

    companion object {
        @Volatile
        var isRunning = false
            private set
    }

    private lateinit var windowManager: WindowManager
    private lateinit var chatHead: AppCompatImageView

    private var chatHeadParams: WindowManager.LayoutParams? = null
    private var chatWindow: View? = null

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
        isRunning = true
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
            chatHead.setImageResource(R.drawable.chat_foot_placeholder)
            showChatWindow()
        } else {
            hideChatWindow()
        }
    }

    private fun showChatWindow() {

        val container = android.view.LayoutInflater.from(this)
            .inflate(R.layout.float_window, null)

        container.findViewById<TextView>(R.id.close_window)
            .setOnClickListener {
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

        windowManager.addView(container, params)

        // Put the chat head above the full-screen floating window.
        chatHeadParams?.let {
            windowManager.removeView(chatHead)
            windowManager.addView(chatHead, it)
        }
    }

    private fun hideChatWindow() {

        chatWindow?.let {
            windowManager.removeView(it)
        }

        chatWindow = null

        if (::chatHead.isInitialized) {
            chatHead.setImageResource(R.drawable.chat_head_placeholder)
        }
    }

    override fun onDestroy() {

        hideChatWindow()

        if (::chatHead.isInitialized) {
            windowManager.removeView(chatHead)
        }

        isRunning = false

        super.onDestroy()
    }
}
