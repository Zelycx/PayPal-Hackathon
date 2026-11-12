package com.example.paypalhackathon.data

import android.content.Context
import android.database.Cursor
import android.graphics.Bitmap
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.OpenableColumns
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import com.example.paypalhackathon.BuildConfig
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import java.util.concurrent.Executors
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class BackendApiException(
    val statusCode: Int?,
    override val message: String,
) : IOException(message)

/** A single asynchronous client for the guest-session, shopping, and Sandbox APIs. */
class BackendApiClient private constructor(context: Context) {
    private val appContext = context.applicationContext
    private val sessionStore = EncryptedSessionStore(appContext)
    private val executor = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private val baseUrl = BuildConfig.BACKEND_BASE_URL.trimEnd('/')
    private val purchaseCancellationLock = Any()

    @Volatile
    private var purchaseCancellationRequested = false

    private var purchaseRequestInProgress = false

    @Volatile
    private var activePurchaseConnection: HttpURLConnection? = null

    @Volatile
    private var cachedShoppingResponse: ShoppingResponse? = null

    fun cachedShoppingResponse(): ShoppingResponse? = cachedShoppingResponse

    fun ensureGuestSession(callback: (Result<Unit>) -> Unit) {
        submit(callback) {
            if (sessionStore.readToken() == null) startGuestSession()
        }
    }

    fun analyzeShoppingImage(uri: Uri, callback: (Result<ShoppingResponse>) -> Unit) {
        submit(callback) {
            val (bytes, mimeType) = readSelectedImage(uri)
            val response = protectedRequest { token -> uploadShoppingImage(bytes, mimeType, token) }
            val parsed = ShoppingResponse.parse(response)
            cachedShoppingResponse = parsed
            parsed
        }
    }

    /** Encodes and uploads the explicitly confirmed crop on the API executor. The caller retains bitmap ownership. */
    fun analyzePurchase(
        bitmap: Bitmap,
        budget: PurchaseBudgetInput?,
        callback: (Result<ShoppingResponse>) -> Unit,
    ) {
        val accepted = synchronized(purchaseCancellationLock) {
            if (purchaseRequestInProgress) {
                false
            } else {
                purchaseRequestInProgress = true
                purchaseCancellationRequested = false
                true
            }
        }
        if (!accepted) {
            mainHandler.post {
                callback(Result.failure(BackendApiException(null, "A purchase analysis is already running.")))
            }
            return
        }
        submit(callback) {
            try {
                checkPurchaseNotCancelled()
                if (bitmap.isRecycled || bitmap.width <= 0 || bitmap.height <= 0) {
                    throw BackendApiException(null, "The selected screen region is no longer available. Select it again.")
                }
                val output = ByteArrayOutputStream()
                val encoded = try {
                    bitmap.compress(Bitmap.CompressFormat.JPEG, 90, output)
                } catch (_: Exception) {
                    false
                }
                if (!encoded || output.size() == 0) {
                    throw BackendApiException(null, "The selected screen region could not be encoded. Select it again.")
                }
                if (output.size() > MAX_UPLOAD_BYTES) {
                    throw BackendApiException(413, "The selected screen region is larger than the 10 MB upload limit.")
                }
                checkPurchaseNotCancelled()
                val response = protectedRequest(purchaseAnalysis = true) { token ->
                    uploadShoppingImage(output.toByteArray(), "image/jpeg", token, budget, includePurchaseEvaluation = true)
                }
                val parsed = ShoppingResponse.parse(response)
                cachedShoppingResponse = parsed
                parsed
            } finally {
                synchronized(purchaseCancellationLock) {
                    purchaseRequestInProgress = false
                    purchaseCancellationRequested = false
                    activePurchaseConnection = null
                }
            }
        }
    }

    /** Best-effort cancellation for the active selected-crop request; the crop remains caller-owned for retry. */
    fun cancelPurchaseAnalysis() {
        val connection = synchronized(purchaseCancellationLock) {
            purchaseCancellationRequested = true
            activePurchaseConnection
        }
        connection?.disconnect()
    }

    fun loadPayPalSandbox(callback: (Result<WalletDashboard>) -> Unit) {
        submit(callback) {
            val connection = protectedRequest { token -> requestJson("/paypal/connection", "GET", token) }
            val balances = protectedRequest { token -> requestJson("/paypal/balances", "GET", token) }
            val transactions = protectedRequest { token ->
                requestJson("/paypal/transactions?days=30&page=1&page_size=100", "GET", token)
            }
            WalletDashboard(connection, balances, transactions)
        }
    }

    fun sendShoppingChat(
        message: String,
        context: JSONObject,
        history: List<ShoppingChatTurn>,
        callback: (Result<String>) -> Unit,
    ) {
        val payload = try {
            createShoppingChatPayload(message, context, history)
        } catch (error: Exception) {
            mainHandler.post { callback(Result.failure(toApiException(error))) }
            return
        }
        submit(callback) {
            val response = protectedRequest { token ->
                requestJson("/shopping/chat", "POST", token, payload.toString())
            }
            parseShoppingChatAnswer(response)
        }
    }

    private fun <T> submit(callback: (Result<T>) -> Unit, work: () -> T) {
        executor.execute {
            val result = try {
                Result.success(work())
            } catch (error: Exception) {
                Result.failure(toApiException(error))
            }
            mainHandler.post { callback(result) }
        }
    }

    private fun protectedRequest(
        purchaseAnalysis: Boolean = false,
        request: (String) -> JSONObject,
    ): JSONObject {
        checkPurchaseNotCancelled(purchaseAnalysis)
        var token = sessionStore.readToken() ?: startGuestSession(purchaseAnalysis)
        try {
            return request(token)
        } catch (error: BackendApiException) {
            if (error.statusCode != 401) throw error
        }

        // The backend session store expires tokens. Discard a rejected token,
        // create a fresh guest session, and retry a protected request once.
        sessionStore.clear()
        token = startGuestSession(purchaseAnalysis)
        checkPurchaseNotCancelled(purchaseAnalysis)
        return try {
            request(token)
        } catch (error: BackendApiException) {
            if (error.statusCode == 401) {
                sessionStore.clear()
                throw BackendApiException(401, "The guest session expired. Try the request again.")
            }
            throw error
        }
    }

    private fun startGuestSession(purchaseAnalysis: Boolean = false): String {
        val payload = JSONObject().put("display_name", "Guest")
        val response = requestJson(
            "/session/start",
            "POST",
            body = payload.toString(),
            purchaseAnalysis = purchaseAnalysis,
        )
        val token = response.optString("access_token").takeIf { it.isNotBlank() }
            ?: throw BackendApiException(null, "The backend did not return a guest session token.")
        sessionStore.writeToken(token)
        return token
    }

    private fun requestJson(
        path: String,
        method: String,
        token: String? = null,
        body: String? = null,
        purchaseAnalysis: Boolean = false,
    ): JSONObject {
        val bodyBytes = body?.toByteArray(StandardCharsets.UTF_8)
        val result = executeRequest(
            path,
            method,
            token,
            bodyBytes,
            "application/json; charset=utf-8",
            purchaseAnalysis = purchaseAnalysis,
        )
        return result
    }

    private fun uploadShoppingImage(
        bytes: ByteArray,
        mimeType: String,
        token: String,
        budget: PurchaseBudgetInput? = null,
        includePurchaseEvaluation: Boolean = false,
    ): JSONObject {
        val boundary = "PayPalHackathon-${System.nanoTime()}"
        val result = executeRequest(
            path = "/shopping/analyze",
            method = "POST",
            token = token,
            contentType = "multipart/form-data; boundary=$boundary",
            readTimeoutMs = if (includePurchaseEvaluation) PURCHASE_EVALUATION_TIMEOUT_MS else READ_TIMEOUT_MS,
            purchaseAnalysis = includePurchaseEvaluation,
        ) { output ->
            writeShoppingMultipart(output, boundary, bytes, mimeType, includePurchaseEvaluation, budget)
        }
        return result
    }

    private fun executeRequest(
        path: String,
        method: String,
        token: String? = null,
        body: ByteArray? = null,
        contentType: String? = null,
        readTimeoutMs: Int = READ_TIMEOUT_MS,
        purchaseAnalysis: Boolean = false,
        writeBody: ((OutputStream) -> Unit)? = null,
    ): JSONObject {
        val connection = try {
            URL("$baseUrl$path").openConnection() as HttpURLConnection
        } catch (error: Exception) {
            throw BackendApiException(null, "The configured backend URL is invalid.")
        }

        if (purchaseAnalysis) {
            synchronized(purchaseCancellationLock) {
                if (purchaseCancellationRequested) {
                    connection.disconnect()
                    throw BackendApiException(null, "Purchase analysis was cancelled.")
                }
                activePurchaseConnection = connection
            }
        }

        try {
            checkPurchaseNotCancelled(purchaseAnalysis)
            connection.requestMethod = method
            connection.connectTimeout = CONNECT_TIMEOUT_MS
            connection.readTimeout = readTimeoutMs
            connection.useCaches = false
            connection.setRequestProperty("Accept", "application/json")
            if (token != null) connection.setRequestProperty("Authorization", "Bearer $token")
            if (contentType != null) connection.setRequestProperty("Content-Type", contentType)
            if (body != null || writeBody != null) {
                connection.doOutput = true
                if (writeBody != null) connection.setChunkedStreamingMode(8 * 1024)
                connection.outputStream.use { output ->
                    body?.let(output::write)
                    writeBody?.invoke(output)
                }
            }

            val status = connection.responseCode
            val responseText = (if (status in 200..299) connection.inputStream else connection.errorStream)
                ?.bufferedReader(StandardCharsets.UTF_8)
                ?.use { it.readText() }
                .orEmpty()
            val responseJson = try {
                JSONObject(responseText)
            } catch (_: Exception) {
                JSONObject()
            }
            if (status !in 200..299) {
                throw BackendApiException(status, errorMessage(status, responseJson))
            }
            if (responseText.isBlank()) {
                throw BackendApiException(status, "The backend returned an empty response.")
            }
            return responseJson
        } catch (error: BackendApiException) {
            throw error
        } catch (_: SocketTimeoutException) {
            throw BackendApiException(null, "The backend request timed out. Try again.")
        } catch (error: IOException) {
            throw BackendApiException(null, "Could not reach the backend. Check that it is running and the configured device URL is reachable.")
        } catch (error: Exception) {
            throw BackendApiException(null, "The backend response could not be read.")
        } finally {
            if (purchaseAnalysis) {
                synchronized(purchaseCancellationLock) {
                    if (activePurchaseConnection === connection) activePurchaseConnection = null
                }
            }
            connection.disconnect()
        }
    }

    private fun checkPurchaseNotCancelled(purchaseAnalysis: Boolean = true) {
        if (purchaseAnalysis && purchaseCancellationRequested) {
            throw BackendApiException(null, "Purchase analysis was cancelled.")
        }
    }

    private fun errorMessage(status: Int, response: JSONObject): String {
        if (status == 401) return "The guest session is invalid or expired. Renewing it once."
        val detail = response.opt("detail")
        val message = when (detail) {
            is JSONObject -> detail.optString("message").takeIf { it.isNotBlank() }
            is String -> detail.takeIf { it.isNotBlank() }
            else -> null
        }
        return message ?: "Backend request failed (HTTP $status)."
    }

    private fun toApiException(error: Exception): BackendApiException = when (error) {
        is BackendApiException -> error
        is SocketTimeoutException -> BackendApiException(null, "The backend request timed out. Try again.")
        else -> BackendApiException(null, error.message ?: "The backend request failed.")
    }

    private fun readSelectedImage(uri: Uri): Pair<ByteArray, String> {
        val resolver = appContext.contentResolver
        val name = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null).use { cursor: Cursor? ->
            if (cursor != null && cursor.moveToFirst()) {
                cursor.getString(cursor.getColumnIndexOrThrow(OpenableColumns.DISPLAY_NAME))
            } else null
        }
        val mimeType = resolver.getType(uri)?.substringBefore(';')?.lowercase()
            ?: mimeFromName(name)
            ?: throw BackendApiException(null, "Choose a JPEG, PNG, or WebP screenshot.")
        if (mimeType !in SUPPORTED_IMAGE_TYPES) {
            throw BackendApiException(null, "Choose a JPEG, PNG, or WebP screenshot.")
        }

        val output = ByteArrayOutputStream()
        val input = resolver.openInputStream(uri)
            ?: throw BackendApiException(null, "The selected screenshot could not be opened.")
        input.use { stream ->
            val buffer = ByteArray(8 * 1024)
            var total = 0
            while (true) {
                val read = stream.read(buffer)
                if (read < 0) break
                total += read
                if (total > MAX_UPLOAD_BYTES) {
                    throw BackendApiException(413, "The selected screenshot is larger than the 10 MB upload limit.")
                }
                output.write(buffer, 0, read)
            }
        }
        if (output.size() == 0) throw BackendApiException(null, "The selected screenshot is empty.")
        return output.toByteArray() to mimeType
    }

    private fun mimeFromName(name: String?): String? = when (name?.substringAfterLast('.', "")?.lowercase()) {
        "jpg", "jpeg" -> "image/jpeg"
        "png" -> "image/png"
        "webp" -> "image/webp"
        else -> null
    }

    private class EncryptedSessionStore(context: Context) {
        private val preferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

        @Synchronized
        fun readToken(): String? {
            val encoded = preferences.getString(TOKEN_KEY, null) ?: return null
            return try {
                val combined = Base64.decode(encoded, Base64.NO_WRAP)
                val iv = combined.copyOfRange(0, GCM_IV_LENGTH)
                val encrypted = combined.copyOfRange(GCM_IV_LENGTH, combined.size)
                val cipher = Cipher.getInstance(TRANSFORMATION)
                cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(GCM_TAG_BITS, iv))
                String(cipher.doFinal(encrypted), StandardCharsets.UTF_8)
            } catch (_: Exception) {
                clear()
                null
            }
        }

        @Synchronized
        fun writeToken(token: String) {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.ENCRYPT_MODE, secretKey())
            val encrypted = cipher.doFinal(token.toByteArray(StandardCharsets.UTF_8))
            val combined = cipher.iv + encrypted
            if (!preferences.edit().putString(TOKEN_KEY, Base64.encodeToString(combined, Base64.NO_WRAP)).commit()) {
                throw BackendApiException(null, "The guest session could not be stored securely.")
            }
        }

        @Synchronized
        fun clear() {
            preferences.edit().remove(TOKEN_KEY).commit()
        }

        private fun secretKey(): SecretKey {
            val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
            (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
            val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
            generator.init(
                KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true)
                    .build(),
            )
            return generator.generateKey()
        }

        companion object {
            private const val PREFERENCES_NAME = "guest_session"
            private const val TOKEN_KEY = "encrypted_access_token"
            private const val KEY_ALIAS = "paypal_hackathon_guest_session"
            private const val ANDROID_KEYSTORE = "AndroidKeyStore"
            private const val TRANSFORMATION = "AES/GCM/NoPadding"
            private const val GCM_IV_LENGTH = 12
            private const val GCM_TAG_BITS = 128
        }
    }

    companion object {
        private const val CONNECT_TIMEOUT_MS = 10_000
        private const val READ_TIMEOUT_MS = 120_000
        private const val PURCHASE_EVALUATION_TIMEOUT_MS = 130_000
        private const val MAX_UPLOAD_BYTES = 10 * 1024 * 1024
        private val SUPPORTED_IMAGE_TYPES = setOf("image/jpeg", "image/png", "image/webp")

        @Volatile
        private var instance: BackendApiClient? = null

        fun get(context: Context): BackendApiClient = instance ?: synchronized(this) {
            instance ?: BackendApiClient(context).also { instance = it }
        }
    }
}
