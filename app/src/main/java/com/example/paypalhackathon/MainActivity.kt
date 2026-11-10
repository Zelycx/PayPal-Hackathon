
package com.example.paypalhackathon

import android.os.Bundle
import android.provider.Settings
import android.content.Intent
import android.net.Uri
import android.widget.Button
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.example.paypalhackaton.ChatHeadService

class MainActivity : AppCompatActivity() {

    private var bubbleActive = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        enableEdgeToEdge()
        setContentView(R.layout.activity_main)

        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main)) { v, insets ->
            val systemBars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars()
            )

            v.setPadding(
                systemBars.left,
                systemBars.top,
                systemBars.right,
                systemBars.bottom
            )

            insets
        }

        val bubbleButton = findViewById<Button>(
            R.id.bubble_button
        )

        bubbleButton.text = getString(R.string.bubble_mode)

        bubbleButton.setOnClickListener {

            if (!Settings.canDrawOverlays(this)) {

                val intent = Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:$packageName")
                )

                startActivity(intent)

            } else if (!bubbleActive) {

                try {
                    startService(
                        Intent(this, ChatHeadService::class.java)
                    )

                    bubbleActive = true

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

            } else {

                stopService(
                    Intent(this, ChatHeadService::class.java)
                )

                bubbleActive = false

                Toast.makeText(
                    this,
                    "Bubble Mode deactivated",
                    Toast.LENGTH_SHORT
                ).show()
            }
        }
    }
}
