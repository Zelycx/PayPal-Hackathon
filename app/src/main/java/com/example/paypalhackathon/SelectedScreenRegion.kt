package com.example.paypalhackathon

import android.graphics.Bitmap

/**
 * In-process handoff for the last confirmed live screen crop.
 *
 * The store owns the bitmap until [takeConfirmedBitmap] transfers ownership to
 * its caller. A receiving component must recycle the returned bitmap when its
 * own processing and preview work is complete. The image is never persisted.
 */
object SelectedScreenRegion {
    private val lock = Any()
    private var confirmedBitmap: Bitmap? = null

    /** Takes ownership of [bitmap], replacing and releasing any prior result. */
    fun replace(bitmap: Bitmap) {
        val previous = synchronized(lock) {
            val old = confirmedBitmap
            confirmedBitmap = bitmap
            old
        }
        if (previous !== bitmap && previous != null && !previous.isRecycled) {
            previous.recycle()
        }
    }

    /** Returns the confirmed crop and transfers its ownership to the caller. */
    fun takeConfirmedBitmap(): Bitmap? = synchronized(lock) {
        confirmedBitmap.also { confirmedBitmap = null }
    }

    /** Releases an unclaimed result when Bubble Mode ends. */
    fun clear() {
        val previous = synchronized(lock) {
            confirmedBitmap.also { confirmedBitmap = null }
        }
        if (previous != null && !previous.isRecycled) previous.recycle()
    }
}
