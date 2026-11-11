
package com.example.paypalhackathon

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PorterDuff
import android.graphics.PorterDuffXfermode
import android.view.MotionEvent
import android.view.View
import kotlin.math.max
import kotlin.math.min

class SelectorOverlay(context: Context) : View(context) {

    private val dimPaint = Paint().apply {
        color = Color.argb(150, 0, 0, 0)
    }

    private val clearPaint = Paint().apply {
        xfermode = PorterDuffXfermode(PorterDuff.Mode.CLEAR)
    }

    private val borderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        style = Paint.Style.STROKE
        strokeWidth = dp(2f)
    }

    private val handlePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        style = Paint.Style.FILL
    }

    private var left = 0f
    private var top = 0f
    private var right = 0f
    private var bottom = 0f

    private var initialized = false
    private var dragging = false
    private var resizing = false

    private var lastX = 0f
    private var lastY = 0f

    private val minWidth = dp(80f)
    private val minHeight = dp(60f)
    private val handleRadius = dp(12f)

    init {
        setLayerType(View.LAYER_TYPE_SOFTWARE, null)
        setBackgroundColor(Color.TRANSPARENT)
    }

    private fun dp(value: Float): Float {
        return value * resources.displayMetrics.density
    }

    private fun initializeRectangle() {
        if (initialized || width == 0 || height == 0) return

        val rectWidth = min(dp(220f), width.toFloat() - dp(32f))
        val rectHeight = min(dp(140f), height.toFloat() - dp(32f))

        left = (width - rectWidth) / 2f
        top = (height - rectHeight) / 2f
        right = left + rectWidth
        bottom = top + rectHeight

        initialized = true
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        initializeRectangle()

        val save = canvas.saveLayer(
            0f,
            0f,
            width.toFloat(),
            height.toFloat(),
            null
        )

        // Dim everything.
        canvas.drawRect(
            0f, 0f,
            width.toFloat(), height.toFloat(),
            dimPaint
        )

        // Clear the selected rectangle.
        canvas.drawRect(left, top, right, bottom, clearPaint)

        // Rectangle border.
        canvas.drawRect(left, top, right, bottom, borderPaint)

        // Resize handle.
        canvas.drawCircle(right, bottom, handleRadius, handlePaint)

        canvas.restoreToCount(save)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        initializeRectangle()

        when (event.action) {

            MotionEvent.ACTION_DOWN -> {
                lastX = event.x
                lastY = event.y

                val nearHandle =
                    event.x >= right - handleRadius * 2 &&
                            event.x <= right + handleRadius * 2 &&
                            event.y >= bottom - handleRadius * 2 &&
                            event.y <= bottom + handleRadius * 2

                if (nearHandle) {
                    resizing = true
                    dragging = false
                } else {
                    dragging = true
                    resizing = false

                    // If touched outside, reposition the rectangle.
                    if (event.x < left || event.x > right ||
                        event.y < top || event.y > bottom) {

                        val rectWidth = right - left
                        val rectHeight = bottom - top

                        left = event.x - rectWidth / 2f
                        top = event.y - rectHeight / 2f
                        right = left + rectWidth
                        bottom = top + rectHeight

                        keepInsideScreen()
                    }
                }

                invalidate()
                return true
            }

            MotionEvent.ACTION_MOVE -> {
                val dx = event.x - lastX
                val dy = event.y - lastY

                if (resizing) {
                    right = max(left + minWidth, right + dx)
                    bottom = max(top + minHeight, bottom + dy)
                    keepInsideScreen()
                } else if (dragging) {
                    left += dx
                    right += dx
                    top += dy
                    bottom += dy
                    keepInsideScreen()
                }

                lastX = event.x
                lastY = event.y

                invalidate()
                return true
            }

            MotionEvent.ACTION_UP,
            MotionEvent.ACTION_CANCEL -> {
                dragging = false
                resizing = false
                performClick()
                return true
            }
        }

        return true
    }

    private fun keepInsideScreen() {
        val rectWidth = right - left
        val rectHeight = bottom - top

        left = left.coerceIn(0f, max(0f, width - rectWidth))
        top = top.coerceIn(0f, max(0f, height - rectHeight))

        right = left + rectWidth
        bottom = top + rectHeight
    }

    override fun performClick(): Boolean {
        super.performClick()
        return true
    }
}
