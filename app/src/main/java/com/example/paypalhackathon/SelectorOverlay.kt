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
import kotlin.math.max
import kotlin.math.min

/** Full-screen dimmer and draggable/resizable screen-region marquee. */
class SelectorOverlay(context: Context) : View(context) {

    data class ResizeEdges(
        val left: Boolean = false,
        val top: Boolean = false,
        val right: Boolean = false,
        val bottom: Boolean = false
    )

    private enum class Gesture { NONE, CREATE, MOVE, RESIZE }

    private val dimPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(160, 0, 0, 0)
    }
    private val clearPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        xfermode = PorterDuffXfermode(PorterDuff.Mode.CLEAR)
    }
    private val borderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        style = Paint.Style.STROKE
        strokeWidth = 2f * resources.displayMetrics.density
    }
    private val handlePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        style = Paint.Style.FILL
    }
    private val selectionPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(36, 255, 255, 255)
    }

    private val density = resources.displayMetrics.density
    private val handleRadius = 5f * density
    private val handleTouchRadius = 22f * density
    private val minimumSize = 48f * density

    private var selection: RectF? = null
    private var gesture = Gesture.NONE
    private var resizeEdges = ResizeEdges()
    private var downX = 0f
    private var downY = 0f

    /** Called when a gesture or reset changes whether a valid region exists. */
    var onSelectionValidityChanged: ((Boolean) -> Unit)? = null

    init {
        setLayerType(View.LAYER_TYPE_SOFTWARE, null)
        setBackgroundColor(Color.TRANSPARENT)
        isClickable = true
    }

    fun selectedRect(): RectF? {
        val rect = selection ?: return null
        if (!isSelectionValid(rect)) return null
        return RectF(rect)
    }

    fun resetSelection() {
        selection = null
        gesture = Gesture.NONE
        invalidate()
        onSelectionValidityChanged?.invoke(false)
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val save = canvas.saveLayer(0f, 0f, width.toFloat(), height.toFloat(), null)
        canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), dimPaint)

        selection?.takeIf(::isSelectionValidForDisplay)?.let { rect ->
            canvas.drawRect(rect, clearPaint)
            canvas.drawRect(rect, selectionPaint)
            canvas.drawRect(rect, borderPaint)
            handleCenters(rect).forEach { (x, y) ->
                canvas.drawCircle(x, y, handleRadius, handlePaint)
            }
        }

        canvas.restoreToCount(save)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (width <= 0 || height <= 0) return true

        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downX = event.x.coerceIn(0f, width.toFloat())
                downY = event.y.coerceIn(0f, height.toFloat())
                val rect = selection
                val hitEdges = rect?.let { hitResizeHandle(it, downX, downY) }

                if (hitEdges != null) {
                    gesture = Gesture.RESIZE
                    resizeEdges = hitEdges
                } else if (rect != null && rect.contains(downX, downY)) {
                    gesture = Gesture.MOVE
                } else {
                    gesture = Gesture.CREATE
                    resizeEdges = ResizeEdges()
                    selection = RectF(downX, downY, downX, downY)
                }
                invalidate()
                return true
            }

            MotionEvent.ACTION_MOVE -> {
                val x = event.x.coerceIn(0f, width.toFloat())
                val y = event.y.coerceIn(0f, height.toFloat())
                when (gesture) {
                    Gesture.CREATE -> selection = RectF(
                        min(downX, x), min(downY, y), max(downX, x), max(downY, y)
                    )
                    Gesture.MOVE -> moveSelection(x - downX, y - downY)
                    Gesture.RESIZE -> resizeSelection(x, y)
                    Gesture.NONE -> Unit
                }
                invalidate()
                onSelectionValidityChanged?.invoke(selectedRect() != null)
                return true
            }

            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                gesture = Gesture.NONE
                invalidate()
                onSelectionValidityChanged?.invoke(selectedRect() != null)
                return true
            }
        }
        return true
    }

    private fun moveSelection(dx: Float, dy: Float) {
        val rect = selection ?: return
        val oldLeft = rect.left
        val oldTop = rect.top
        val maxLeft = (width - rect.width()).coerceAtLeast(0f)
        val maxTop = (height - rect.height()).coerceAtLeast(0f)
        val left = (rect.left + dx).coerceIn(0f, maxLeft)
        val top = (rect.top + dy).coerceIn(0f, maxTop)
        rect.offsetTo(left, top)
        downX += left - oldLeft
        downY += top - oldTop
    }

    private fun resizeSelection(x: Float, y: Float) {
        val rect = selection ?: return
        val minWidth = min(minimumSize, width.toFloat())
        val minHeight = min(minimumSize, height.toFloat())

        if (resizeEdges.left) {
            rect.left = x.coerceIn(0f, (rect.right - minWidth).coerceAtLeast(0f))
        }
        if (resizeEdges.right) {
            rect.right = x.coerceIn((rect.left + minWidth).coerceAtMost(width.toFloat()), width.toFloat())
        }
        if (resizeEdges.top) {
            rect.top = y.coerceIn(0f, (rect.bottom - minHeight).coerceAtLeast(0f))
        }
        if (resizeEdges.bottom) {
            rect.bottom = y.coerceIn((rect.top + minHeight).coerceAtMost(height.toFloat()), height.toFloat())
        }
    }

    private fun hitResizeHandle(rect: RectF, x: Float, y: Float): ResizeEdges? {
        return handleCenters(rect).firstOrNull { (centerX, centerY) ->
            abs(x - centerX) <= handleTouchRadius && abs(y - centerY) <= handleTouchRadius
        }?.let { (centerX, centerY) ->
            val horizontal = when {
                centerX == rect.left -> ResizeEdges(left = true)
                centerX == rect.right -> ResizeEdges(right = true)
                else -> ResizeEdges()
            }
            val vertical = when {
                centerY == rect.top -> ResizeEdges(top = true)
                centerY == rect.bottom -> ResizeEdges(bottom = true)
                else -> ResizeEdges()
            }
            ResizeEdges(
                left = horizontal.left,
                top = vertical.top,
                right = horizontal.right,
                bottom = vertical.bottom
            )
        }
    }

    private fun handleCenters(rect: RectF): List<Pair<Float, Float>> = listOf(
        rect.left to rect.top,
        rect.centerX() to rect.top,
        rect.right to rect.top,
        rect.right to rect.centerY(),
        rect.right to rect.bottom,
        rect.centerX() to rect.bottom,
        rect.left to rect.bottom,
        rect.left to rect.centerY()
    )

    private fun isSelectionValidForDisplay(rect: RectF): Boolean =
        rect.width() > 0f && rect.height() > 0f

    private fun isSelectionValid(rect: RectF): Boolean =
        isSelectionValidForDisplay(rect) &&
                rect.width() >= minimumSize && rect.height() >= minimumSize &&
                rect.left >= 0f && rect.top >= 0f &&
                rect.right <= width.toFloat() && rect.bottom <= height.toFloat()
}
