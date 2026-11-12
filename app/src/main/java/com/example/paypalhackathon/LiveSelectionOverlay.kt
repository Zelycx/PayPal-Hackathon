package com.example.paypalhackathon

import android.content.Context
import android.graphics.RectF
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView

/** A touchable full-screen wrapper around [SelectorOverlay] and its controls. */
class LiveSelectionOverlay(
    context: Context,
    private val onConfirm: (Selection) -> Unit,
    private val onCancel: () -> Unit
) : FrameLayout(context) {

    data class Selection(
        val rectangle: RectF,
        val surfaceWidth: Int,
        val surfaceHeight: Int,
        val screenLeft: Int,
        val screenTop: Int
    )

    private val selector = SelectorOverlay(context)
    private lateinit var confirmButton: Button

    init {
        setBackgroundColor(android.graphics.Color.TRANSPARENT)
        selector.onSelectionValidityChanged = { confirmButton.isEnabled = it }
        addView(
            selector,
            LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT)
        )

        val hint = TextView(context).apply {
            text = "Drag to select a screen region. Move it or use the edge handles to adjust."
            textSize = 14f
            setTextColor(android.graphics.Color.WHITE)
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(14), dp(9), dp(14), dp(9))
            background = panelBackground()
        }
        addView(
            hint,
            LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT).apply {
                gravity = Gravity.TOP
                setMargins(dp(12), dp(36), dp(12), 0)
            }
        )

        val controls = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(8), dp(6), dp(8), dp(6))
            background = panelBackground()
        }

        val resetButton = makeButton("Reset")
        resetButton.setOnClickListener {
            selector.resetSelection()
            confirmButton.isEnabled = false
        }
        controls.addView(resetButton, weightedButtonParams())

        val cancelButton = makeButton("Cancel").apply {
            setOnClickListener { onCancel() }
        }
        controls.addView(cancelButton, weightedButtonParams())

        confirmButton = makeButton("Use region").apply {
            isEnabled = false
            setOnClickListener {
                val rect = selector.selectedRect() ?: return@setOnClickListener
                val location = IntArray(2)
                selector.getLocationOnScreen(location)
                onConfirm(
                    Selection(rect, selector.width, selector.height, location[0], location[1])
                )
            }
        }
        controls.addView(confirmButton, weightedButtonParams())

        addView(
            controls,
            LayoutParams(LayoutParams.MATCH_PARENT, dp(72)).apply {
                gravity = Gravity.BOTTOM
                setMargins(dp(12), 0, dp(12), dp(20))
            }
        )
        controls.bringToFront()
    }

    fun selectedRect(): RectF? = selector.selectedRect()

    fun setConfirmEnabled(enabled: Boolean) {
        confirmButton.isEnabled = enabled
    }

    private fun makeButton(label: String): Button = Button(context).apply {
        text = label
        isAllCaps = false
        textSize = 13f
        minWidth = 0
        setPadding(dp(4), 0, dp(4), 0)
        contentDescription = label
    }

    private fun weightedButtonParams(): LinearLayout.LayoutParams =
        LinearLayout.LayoutParams(0, LayoutParams.MATCH_PARENT, 1f).apply {
            setMargins(dp(3), 0, dp(3), 0)
        }

    private fun panelBackground() = GradientDrawable().apply {
        setColor(android.graphics.Color.argb(235, 30, 30, 30))
        cornerRadius = dp(12).toFloat()
    }

    private fun dp(value: Int): Int =
        (value * resources.displayMetrics.density + 0.5f).toInt()
}
