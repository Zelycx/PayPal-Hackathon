package com.example.paypalhackathon

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.util.DisplayMetrics
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import java.nio.ByteBuffer

/** Owns one consented MediaProjection session and all of its capture resources. */
class ScreenCaptureService : Service() {
    companion object {
        const val ACTION_START = "com.example.paypalhackathon.screenread.START"
        const val ACTION_STOP = "com.example.paypalhackathon.screenread.STOP"
        const val EXTRA_RESULT_CODE = "screenread.result_code"
        const val EXTRA_RESULT_DATA = "screenread.result_data"

        private const val CHANNEL_ID = "screen_read_capture"
        private const val NOTIFICATION_ID = 4201
        private const val FRAME_INTERVAL_MS = 500L
        private const val VIRTUAL_DISPLAY_NAME = "ScreenReadVirtualDisplay"
    }

    private val captureLock = Any()
    private lateinit var captureThread: HandlerThread
    private lateinit var captureHandler: Handler
    private lateinit var mainHandler: Handler
    private lateinit var displayManager: DisplayManager

    // Projection and VirtualDisplay are controlled on the service main thread.
    // ImageReader access is protected by captureLock because sampling happens
    // on captureHandler while resize/stop requests arrive on mainHandler.
    private var projection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null
    private var projectionCallback: MediaProjection.Callback? = null
    private var projectionCallbackRegistered = false
    private var displayListener: DisplayManager.DisplayListener? = null
    private var captureWidth = 0
    private var captureHeight = 0
    private var densityDpi = 0

    @Volatile
    private var shuttingDown = false

    private val frameRunnable: Runnable = object : Runnable {
        override fun run() {
            if (shuttingDown) return

            val frame = try {
                synchronized(captureLock) {
                    val reader = imageReader ?: return
                    val image = reader.acquireLatestImage() ?: return@synchronized null
                    try {
                        imageToBitmap(image)
                    } finally {
                        image.close()
                    }
                }
            } catch (_: Exception) {
                // Do cleanup on the service thread after the lock is released.
                mainHandler.post { failCapture() }
                return
            }

            // Serialize publication with shutdown too: otherwise a frame that
            // finished converting just before stop could repopulate the latest
            // frame after stopCapture() had cleared it.
            synchronized(captureLock) {
                if (!shuttingDown) frame?.let(ScreenReader::publishFrame)
            }
            if (!shuttingDown) captureHandler.postDelayed(this, FRAME_INTERVAL_MS)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        mainHandler = Handler(mainLooper)
        captureThread = HandlerThread("ScreenReadCapture").apply { start() }
        captureHandler = Handler(captureThread.looper)
        displayManager = getSystemService(Context.DISPLAY_SERVICE) as DisplayManager
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopCapture()
                stopSelf(startId)
            }
            ACTION_START -> startCapture(intent)
            else -> stopSelf(startId)
        }
        // A projection token is one-use. Never ask Android to recreate this
        // service with a possibly consumed result after process death.
        return START_NOT_STICKY
    }

    private fun startCapture(intent: Intent) {
        if (projection != null || shuttingDown) return

        try {
            val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, 0)
            val resultData = getResultData(intent)
                ?: throw IllegalArgumentException("Missing screen-capture consent data")

            // Consent was completed by the activity. Promote the service before
            // obtaining MediaProjection, as required for a projection FGS.
            startCaptureForeground()

            val manager = getSystemService(Context.MEDIA_PROJECTION_SERVICE)
                    as MediaProjectionManager
            val activeProjection = manager.getMediaProjection(resultCode, resultData)
                ?: throw SecurityException("MediaProjection could not be created")
            projection = activeProjection

            val (width, height) = currentCaptureSize()
            captureWidth = width
            captureHeight = height
            densityDpi = resources.displayMetrics.densityDpi

            val callback = object : MediaProjection.Callback() {
                override fun onStop() {
                    mainHandler.post {
                        stopCapture(projectionAlreadyStopped = true)
                        stopSelf()
                    }
                }

                // Android 14+ reports the actual selected display or app-window
                // dimensions here. Older versions use the display listener.
                override fun onCapturedContentResize(width: Int, height: Int) {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                        mainHandler.post { resizeCapture(width, height) }
                    }
                }
            }
            projectionCallback = callback
            activeProjection.registerCallback(callback, mainHandler)
            projectionCallbackRegistered = true

            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                registerDisplayListener()
            }
            createImageReaderAndDisplay(activeProjection, width, height)
        } catch (_: Exception) {
            // Includes consent/token errors and expected display creation errors.
            failCapture()
        }
    }

    @Suppress("DEPRECATION")
    private fun getResultData(intent: Intent): Intent? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
        } else {
            intent.getParcelableExtra(EXTRA_RESULT_DATA)
        }

    private fun startCaptureForeground() {
        val notification = buildNotification()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Screen Read",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Shown while Screen Read is capturing the display"
            }
            (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                .createNotificationChannel(channel)
        }
    }

    private fun buildNotification(): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle("Screen Read is active")
            .setContentText("The latest screen frame is available to the app")
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setOngoing(true)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .build()

    private fun createImageReaderAndDisplay(
        activeProjection: MediaProjection,
        width: Int,
        height: Int
    ) {
        require(width > 0 && height > 0) { "Invalid capture dimensions" }
        val reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        try {
            val display = activeProjection.createVirtualDisplay(
                VIRTUAL_DISPLAY_NAME,
                width,
                height,
                densityDpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                reader.surface,
                null,
                captureHandler
            ) ?: throw IllegalStateException("VirtualDisplay could not be created")

            synchronized(captureLock) {
                imageReader = reader
                virtualDisplay = display
            }
            captureHandler.post(frameRunnable)
        } catch (exception: Exception) {
            reader.close()
            throw exception
        }
    }

    private fun imageToBitmap(image: Image): Bitmap? {
        val plane = image.planes.firstOrNull() ?: return null
        val buffer: ByteBuffer = plane.buffer
        val pixelStride = plane.pixelStride
        val rowStride = plane.rowStride
        if (pixelStride <= 0 || rowStride <= 0) return null

        val paddedWidth = rowStride / pixelStride
        if (paddedWidth < image.width) return null

        val padded = Bitmap.createBitmap(
            paddedWidth,
            image.height,
            Bitmap.Config.ARGB_8888
        )
        var isReturnedBitmap = false
        try {
            buffer.rewind()
            padded.copyPixelsFromBuffer(buffer)
            val result = Bitmap.createBitmap(padded, 0, 0, image.width, image.height)
            isReturnedBitmap = result === padded
            return result
        } finally {
            // createBitmap may return padded itself when no crop is needed.
            // Keep that bitmap alive as the frame; release only temporary data.
            if (!isReturnedBitmap && !padded.isRecycled) padded.recycle()
        }
    }

    private fun registerDisplayListener() {
        val listener = object : DisplayManager.DisplayListener {
            override fun onDisplayAdded(displayId: Int) = Unit
            override fun onDisplayRemoved(displayId: Int) = Unit
            override fun onDisplayChanged(displayId: Int) {
                val display = (getSystemService(Context.WINDOW_SERVICE) as WindowManager)
                    .defaultDisplay
                if (displayId == display.displayId) {
                    val (width, height) = currentCaptureSize()
                    resizeCapture(width, height)
                }
            }
        }
        displayListener = listener
        displayManager.registerDisplayListener(listener, mainHandler)
    }

    private fun resizeCapture(width: Int, height: Int) {
        if (width <= 0 || height <= 0 || projection == null || shuttingDown) return

        val resized = try {
            synchronized(captureLock) {
                val display = virtualDisplay ?: return
                if (width == captureWidth && height == captureHeight) return

                val newReader = ImageReader.newInstance(
                    width,
                    height,
                    PixelFormat.RGBA_8888,
                    2
                )
                val oldReader = imageReader
                try {
                    // Keep the single display associated with this consent token.
                    display.resize(width, height, densityDpi)
                    display.setSurface(newReader.surface)
                    imageReader = newReader
                    captureWidth = width
                    captureHeight = height
                    oldReader?.close()
                    true
                } catch (exception: Exception) {
                    newReader.close()
                    throw exception
                }
            }
        } catch (_: Exception) {
            false
        }

        if (!resized) failCapture()
    }

    @Suppress("DEPRECATION")
    private fun currentCaptureSize(): Pair<Int, Int> {
        val metrics = DisplayMetrics()
        val display = (getSystemService(Context.WINDOW_SERVICE) as WindowManager).defaultDisplay
        display.getRealMetrics(metrics)
        return metrics.widthPixels to metrics.heightPixels
    }

    private fun failCapture() {
        stopCapture()
        stopSelf()
    }

    private fun stopCapture(projectionAlreadyStopped: Boolean = false) {
        if (shuttingDown) return
        shuttingDown = true

        displayListener?.let { listener ->
            try {
                displayManager.unregisterDisplayListener(listener)
            } catch (_: Exception) {
                // Continue releasing projection and image resources.
            }
        }
        displayListener = null
        if (::captureHandler.isInitialized) captureHandler.removeCallbacksAndMessages(null)

        synchronized(captureLock) {
            // Stop the producer before closing its ImageReader-owned Surface.
            virtualDisplay?.let { display ->
                try {
                    display.setSurface(null)
                } catch (_: Exception) {
                    // release() below still tears down the display.
                }
                try {
                    display.release()
                } catch (_: Exception) {
                    // Continue releasing the reader and projection as well.
                }
            }
            virtualDisplay = null

            try {
                imageReader?.close()
            } catch (_: Exception) {
                // Continue releasing the projection even if reader cleanup fails.
            }
            imageReader = null
        }

        if (projectionCallbackRegistered) {
            try {
                projectionCallback?.let { callback -> projection?.unregisterCallback(callback) }
            } catch (_: Exception) {
                // The projection may already have ended and cleared its callbacks.
            }
        }
        projectionCallback = null
        projectionCallbackRegistered = false
        if (!projectionAlreadyStopped) {
            try {
                projection?.stop()
            } catch (_: Exception) {
                // Continue clearing local state if Android already stopped it.
            }
        }
        projection = null

        ScreenReader.clearLatestFrame()
        if (::captureThread.isInitialized) captureThread.quitSafely()
        try {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } catch (_: Exception) {
            // The service might not have reached foreground mode yet.
        }
    }

    override fun onDestroy() {
        stopCapture()
        super.onDestroy()
    }
}
