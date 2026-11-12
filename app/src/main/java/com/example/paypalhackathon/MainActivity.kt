
package com.example.paypalhackathon

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.media.projection.MediaProjectionManager
import android.graphics.Color
import android.content.res.ColorStateList
import android.widget.Button
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.example.paypalhackaton.ChatHeadService
import android.content.BroadcastReceiver
import android.content.Context
import android.content.IntentFilter
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {

    private lateinit var bubbleButton: Button

    // Register before the activity is started so Android can restore the
    // result callback correctly if the activity is recreated during consent.
    private val screenCaptureConsentLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK && result.data != null) {
            startBubbleMode(result.resultCode, result.data)
        } else {
            startBubbleMode()
        }
    }

    private val serviceStateReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == ChatHeadService.ACTION_STATE_CHANGED) {
                updateButton()
            }
        }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        enableEdgeToEdge()
        setContentView(R.layout.activity_main)

        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main)) { view, insets ->
            val systemBars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars()
            )

            view.setPadding(
                systemBars.left,
                systemBars.top,
                systemBars.right,
                systemBars.bottom
            )

            insets
        }

        bubbleButton = findViewById(R.id.bubble_button)

        updateButton()


        bubbleButton.setOnClickListener {

            if (!Settings.canDrawOverlays(this)) {

                val intent = Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:$packageName")
                )

                startActivity(intent)

                Toast.makeText(
                    this,
                    "Please allow Display over other apps.",
                    Toast.LENGTH_LONG
                ).show()

                return@setOnClickListener
            }

            if (ChatHeadService.isRunning) {

                ScreenReader.stop(this)

                stopService(
                    Intent(this, ChatHeadService::class.java)
                )

                Toast.makeText(
                    this,
                    "Bubble Mode deactivated",
                    Toast.LENGTH_SHORT
                ).show()

                // Do not call updateButton() here.
                // The service will notify the activity when it stops.

            } else {

                try {
                    val projectionManager = getSystemService(
                        MEDIA_PROJECTION_SERVICE
                    ) as MediaProjectionManager
                    screenCaptureConsentLauncher.launch(
                        projectionManager.createScreenCaptureIntent()
                    )

                } catch (e: Exception) {

                    Toast.makeText(
                        this,
                        "Service error: ${e.message}",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }

    }

    /** Starts Bubble Mode; capture starts only when the consent data is present. */
    private fun startBubbleMode(resultCode: Int? = null, resultData: Intent? = null) {
        try {
            startService(Intent(this, ChatHeadService::class.java))
        } catch (e: Exception) {
            Toast.makeText(
                this,
                "Service error: ${e.message}",
                Toast.LENGTH_LONG
            ).show()
            return
        }

        if (resultCode != null && resultData != null) {
            try {
                ScreenReader.start(this, resultCode, resultData)
                Toast.makeText(this, "Bubble Mode activated", Toast.LENGTH_SHORT).show()
            } catch (_: Exception) {
                // Bubble Mode remains useful even if the capture service cannot start.
                ScreenReader.stop(this)
                Toast.makeText(
                    this,
                    "Bubble Mode activated. Screen Read is unavailable.",
                    Toast.LENGTH_LONG
                ).show()
            }
        } else {
            Toast.makeText(
                this,
                "Bubble Mode activated. Screen Read is unavailable.",
                Toast.LENGTH_LONG
            ).show()
        }
        finish()
    }

    override fun onStart() {
        super.onStart()

        ContextCompat.registerReceiver(
            this,
            serviceStateReceiver,
            IntentFilter(ChatHeadService.ACTION_STATE_CHANGED),
            ContextCompat.RECEIVER_NOT_EXPORTED
        )

        ChatHeadService.appInForeground = true

        if (ChatHeadService.isRunning) {
            startService(
                Intent(this, ChatHeadService::class.java)
                    .setAction(ChatHeadService.ACTION_APP_FOREGROUND)
            )
        }

        updateButton()
    }

    override fun onStop() {
        ChatHeadService.appInForeground = false

        if (ChatHeadService.isRunning) {
            startService(
                Intent(this, ChatHeadService::class.java)
                    .setAction(ChatHeadService.ACTION_APP_BACKGROUND)
            )
        }

        unregisterReceiver(serviceStateReceiver)

        super.onStop()
    }

    override fun onResume() {
        super.onResume()

        if (::bubbleButton.isInitialized) {
            updateButton()
        }
    }


    private fun updateButton() {

        val active = ChatHeadService.isRunning

        bubbleButton.backgroundTintList = ColorStateList.valueOf(
            Color.parseColor(
                if (active) "#777777" else "#FF9800"
            )
        )

        bubbleButton.setTextColor(Color.WHITE)

        bubbleButton.text = if (active) {
            "Bubble Mode: ON"
        } else {
            "Bubble Mode: OFF"
        }
    }

}
