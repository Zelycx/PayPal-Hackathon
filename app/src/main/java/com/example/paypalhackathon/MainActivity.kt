
package com.example.paypalhackathon

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.graphics.Color
import android.content.res.ColorStateList
import android.widget.Button
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.example.paypalhackaton.ChatHeadService

class MainActivity : AppCompatActivity() {

    private lateinit var bubbleButton: Button

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

        bubbleButton.text = getString(R.string.bubble_button)

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

                stopService(
                    Intent(this, ChatHeadService::class.java)
                )

                Toast.makeText(
                    this,
                    "Bubble Mode deactivated",
                    Toast.LENGTH_SHORT
                ).show()

            } else {

                try {
                    startService(
                        Intent(this, ChatHeadService::class.java)
                    )

                    Toast.makeText(
                        this,
                        "Bubble Mode activated",
                        Toast.LENGTH_SHORT
                    ).show()

                } catch (e: Exception) {

                    Toast.makeText(
                        this,
                        "Service error: ${e.message}",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }

            updateButton()
        }
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
                if (active) "#0070BA" else "#444444"
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
