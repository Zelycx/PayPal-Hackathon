
package com.example.paypalhackathon

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PorterDuff
import android.graphics.PorterDuffXfermode
import android.graphics.RectF
import android.view.MotionEvent
import android.view.View
import kotlin.math.abs

class SelectorOverlay(context: Context) : View(context) {

    var selectorEnabled = false
        set(value) {
            field = value
            invalidate()
        }

    private val dimPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(150, 0, 0, 0)
    }

    private val clearPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        xfermode = PorterDuffXfermode(PorterDuff.Mode.CLEAR)
    }

    private val borderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        style = Paint.Style.STROKE
        strokeWidth = 2f
    }

    private val handlePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        style = Paint.Style.FILL
    }

    private val rect = RectF()
    private val density = resources.displayMetrics.density
    private val handleRadius = 9f * density

    private var dragging = false
    private var resizing = false
    private var lastX = 0f
    private var lastY = 0f

    init {
        setLayerType(View.LAYER_TYPE_SOFTWARE, null)
        setBackgroundColor(Color.TRANSPARENT)

        val width = 220f * density
        val height = 140f * density

        rect.set(
            80f * density,
            200f * density,
            80f * density + width,
            200f * density + height
        )
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        val save = canvas.saveLayer(
            0f,
            0f,
            width.toFloat(),
            height.toFloat(),
            null
        )

        // Translucent background, always visible.
        canvas.drawColor(Color.TRANSPARENT)
        canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), dimPaint)

        if (selectorEnabled) {
            // Reveal the phone screen inside the selection.
            canvas.drawRect(rect, clearPaint)

            // Draw selection border and resize handle.
            canvas.drawRect(rect, borderPaint)
            canvas.drawCircle(
                rect.right,
                rect.bottom,
                handleRadius,
                handlePaint
            )
        }

        canvas.restoreToCount(save)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (!selectorEnabled) {
            return false
        }

        when (event.action) {
            MotionEvent.ACTION_DOWN -> {
                lastX = event.x
                lastY = event.y

                resizing = abs(event.x - rect.right) < handleRadius * 2 &&
                        abs(event.y - rect.bottom) < handleRadius * 2

                dragging = !resizing && rect.contains(event.x, event.y)

                if (!dragging && !resizing) {
                    val halfWidth = rect.width() / 2f
                    val halfHeight = rect.height() / 2f

                    rect.set(
                        event.x - halfWidth,
                        event.y - halfHeight,
                        event.x + halfWidth,
                        event.y + halfHeight
                    )
                    keepInsideScreen()
                    dragging = true
                }

                invalidate()
                return true
            }

            MotionEvent.ACTION_MOVE -> {
                val dx = event.x - lastX
                val dy = event.y - lastY

                if (dragging) {
                    rect.offset(dx, dy)
                } else if (resizing) {
                    rect.right = (rect.right + dx).coerceAtLeast(rect.left + 50f * density)
                    rect.bottom = (rect.bottom + dy).coerceAtLeast(rect.top + 50f * density)
                }

                keepInsideScreen()

                lastX = event.x
                lastY = event.y

                invalidate()
                return true
            }

            MotionEvent.ACTION_UP,
            MotionEvent.ACTION_CANCEL -> {
                dragging = false
                resizing = false
                invalidate()
                return true
            }
        }

        return true
    }

    private fun keepInsideScreen() {
        val dx = when {
            rect.left < 0f -> -rect.left
            rect.right > width -> width - rect.right
            else -> 0f
        }

        val dy = when {
            rect.top < 0f -> -rect.top
            rect.bottom > height -> height - rect.bottom
            else -> 0f
        }

        rect.offset(dx, dy)
    }
}
