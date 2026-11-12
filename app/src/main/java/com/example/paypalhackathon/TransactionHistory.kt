
package com.example.paypalhackathon

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.graphics.Color
import android.content.res.ColorStateList
import android.widget.Button
import android.widget.LinearLayout
import android.widget.Toast
import android.view.View
import android.content.BroadcastReceiver
import android.content.Context
import android.content.IntentFilter
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat

class TransactionHistory : AppCompatActivity() {

    private lateinit var menuButton: Button
    private lateinit var menuPanel: LinearLayout
    private lateinit var chatbotButton: Button
    private lateinit var bubbleButton: Button

    private var receiverRegistered = false

    private val serviceStateReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == ChatHeadService.ACTION_STATE_CHANGED) {
                updateButton()
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContentView(R.layout.transaction_history)

        // SYSTEM BAR PADDING
        ViewCompat.setOnApplyWindowInsetsListener(
            findViewById(R.id.main)
        ) { view, insets ->

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

        // CONNECT BUTTONS
        menuButton = findViewById(R.id.menu_button)
        menuPanel = findViewById(R.id.balance_box)
        chatbotButton = findViewById(R.id.page_switch_button_chatbot)
        bubbleButton = findViewById(R.id.bubble_button)

        // MENU OPEN / CLOSE
        menuButton.setOnClickListener {
            menuPanel.visibility =
                if (menuPanel.visibility == View.VISIBLE) {
                    View.GONE
                } else {
                    View.VISIBLE
                }
        }

        // RETURN TO CHATBOT
        chatbotButton.setOnClickListener {
            val intent = Intent(
                this,
                MainActivity::class.java
            ).apply {
                flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or
                        Intent.FLAG_ACTIVITY_SINGLE_TOP
            }

            startActivity(intent)
            finish()
        }

        // INITIAL BUBBLE BUTTON STATE
        updateButton()

        // BUBBLE MODE
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

                updateButton()

            } else {

                try {

                    // IMPORTANT: USE THE SAME ACTIVATION ACTION
                    // AS THE CHATBOT SCREEN.
                    val serviceIntent = Intent(
                        this,
                        ChatHeadService::class.java
                    ).apply {
                        action = ChatHeadService.ACTION_ACTIVATE
                    }

                    startService(serviceIntent)

                    Toast.makeText(
                        this,
                        "Bubble Mode activated",
                        Toast.LENGTH_SHORT
                    ).show()

                    // CLOSE THE APP TASK AFTER ACTIVATING
                    finishAffinity()

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

    // APP FOREGROUND: HIDE BUBBLE
    override fun onStart() {
        super.onStart()

        if (!receiverRegistered) {
            ContextCompat.registerReceiver(
                this,
                serviceStateReceiver,
                IntentFilter(ChatHeadService.ACTION_STATE_CHANGED),
                ContextCompat.RECEIVER_NOT_EXPORTED
            )

            receiverRegistered = true
        }

        updateButton()
    }

    override fun onStop() {
        if (receiverRegistered) {
            unregisterReceiver(serviceStateReceiver)
            receiverRegistered = false
        }

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

        bubbleButton.backgroundTintList =
            ColorStateList.valueOf(
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
