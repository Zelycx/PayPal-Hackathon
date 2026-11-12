package com.example.paypalhackathon

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Rect
import androidx.core.content.ContextCompat
import java.util.concurrent.CopyOnWriteArraySet

/**
 * Public entry point for the screen capture component.
 *
 * Bitmaps returned by [getLatestFrame] and [cropLatestFrame] are caller-owned
 * copies. Frame listeners also receive a fresh caller-owned copy for each
 * callback. Callers may retain, change, or recycle their copies without
 * affecting ScreenReader's latest frame or another listener.
 */
object ScreenReader {
    fun interface FrameListener {
        /** Receives a caller-owned Bitmap copy. */
        fun onFrame(bitmap: Bitmap)
    }

    private val lock = Any()
    private val listeners = CopyOnWriteArraySet<FrameListener>()
    private var latestFrame: Bitmap? = null

    /** Starts the foreground capture service with a successful activity result. */
    fun start(context: Context, resultCode: Int, resultData: Intent) {
        val intent = Intent(context, ScreenCaptureService::class.java).apply {
            action = ScreenCaptureService.ACTION_START
            putExtra(ScreenCaptureService.EXTRA_RESULT_CODE, resultCode)
            putExtra(ScreenCaptureService.EXTRA_RESULT_DATA, resultData)
        }
        ContextCompat.startForegroundService(context.applicationContext, intent)
    }

    /** Stops capture and releases the active projection session. */
    fun stop(context: Context) {
        val intent = Intent(context, ScreenCaptureService::class.java)
        context.applicationContext.stopService(intent)
    }

    /** Returns a caller-owned copy of the latest frame, or null before the first frame. */
    fun getLatestFrame(): Bitmap? = synchronized(lock) {
        latestFrame?.copy(Bitmap.Config.ARGB_8888, false)
    }

    fun addFrameListener(listener: FrameListener) {
        listeners.add(listener)
    }

    fun removeFrameListener(listener: FrameListener) {
        listeners.remove(listener)
    }

    /**
     * Crops a rectangle expressed in the supplied coordinate space, scaling it
     * to the latest frame. Invalid dimensions, empty rectangles, or a missing
     * frame return null. Returned Bitmap is a caller-owned copy.
     */
    fun cropLatestFrame(
        rectangle: Rect,
        coordinateWidth: Int,
        coordinateHeight: Int
    ): Bitmap? {
        if (coordinateWidth <= 0 || coordinateHeight <= 0) return null

        val source = synchronized(lock) {
            latestFrame?.copy(Bitmap.Config.ARGB_8888, false)
        } ?: return null

        try {
            val requested = Rect(rectangle)
            if (requested.width() <= 0 || requested.height() <= 0) return null

            val left = (requested.left.toDouble() * source.width / coordinateWidth)
                .toInt().coerceIn(0, source.width)
            val top = (requested.top.toDouble() * source.height / coordinateHeight)
                .toInt().coerceIn(0, source.height)
            val right = (requested.right.toDouble() * source.width / coordinateWidth)
                .toInt().coerceIn(0, source.width)
            val bottom = (requested.bottom.toDouble() * source.height / coordinateHeight)
                .toInt().coerceIn(0, source.height)

            if (right <= left || bottom <= top) return null
            val crop = Bitmap.createBitmap(source, left, top, right - left, bottom - top)
            // Android may return source for a full-frame crop. Preserve the
            // ownership contract by returning a distinct bitmap before cleanup.
            return if (crop === source) {
                crop.copy(Bitmap.Config.ARGB_8888, true)
            } else {
                crop
            }
        } finally {
            // This is a private snapshot created for cropping, never exposed.
            source.recycle()
        }
    }

    /** Internal service entry point. Stored frames are immutable by convention. */
    internal fun publishFrame(frame: Bitmap) {
        synchronized(lock) {
            latestFrame = frame
        }

        // Invoke listeners away from the ImageReader callback thread. Each gets
        // its own copy so one listener cannot affect the stored frame or others.
        listeners.forEach { listener ->
            val copy = synchronized(lock) {
                latestFrame?.copy(Bitmap.Config.ARGB_8888, false)
            } ?: return@forEach
            android.os.Handler(android.os.Looper.getMainLooper()).post {
                try {
                    listener.onFrame(copy)
                } catch (_: RuntimeException) {
                    // A client callback must not crash the capture service.
                    if (!copy.isRecycled) copy.recycle()
                }
            }
        }
    }

    /** Clears the current frame when the capture session ends. */
    internal fun clearLatestFrame() {
        synchronized(lock) {
            // Do not recycle: a concurrent copy operation may still be reading it.
            latestFrame = null
        }
    }
}
