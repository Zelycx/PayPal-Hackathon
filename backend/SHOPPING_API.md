# Ellie Shopping AI API

## Endpoint

`POST /shopping/analyze`

The endpoint analyzes one user-selected, cropped shopping screenshot. It requires the existing guest session and sends the image to the configured Groq vision model. The application does not create persistent image records. Starlette may temporarily spool multipart uploads to its temporary upload storage before the route applies the 10 MB file limit; the upload is closed after processing. Cloud vision analysis is not local processing.

## Authentication

Send the guest token returned by `POST /session/start`:

```http
Authorization: Bearer <guest_session_token>
```

The guest token is unrelated to PayPal OAuth. Do not send PayPal credentials or the Groq API key from Android.

## Request

Use `multipart/form-data` with the required file field `image`.

Supported content: JPEG, PNG, or WebP. Maximum image size: 10 MB. The backend verifies decoded image format, rejects animated and malformed images, applies orientation, removes metadata through re-encoding, and rejects images over 8,000 pixels on either side or 40 megapixels total. It re-encodes at high quality and does not downscale text. An encoded result over 10 MB is rejected.

## Successful response

All money and quantity values are decimal strings. `items_subtotal` is calculated from known selected/cart line items, grouped by currency. `displayed_*` and `visible_checkout_total` values are observations from the screenshot. `calculated_payable_total` is populated only when all required components are explicit and complete. An absent fee or discount is not treated as zero.

```json
{
  "success": true,
  "screen_type": "cart",
  "items": [
    {
      "name": "Wireless Mouse",
      "item_context": "cart_item",
      "unit_price": "599.00",
      "original_unit_price": null,
      "quantity": "1",
      "quantity_unit": "piece",
      "line_total": "599.00",
      "displayed_line_total": null,
      "line_total_source": "calculated",
      "currency": "PHP",
      "currency_symbol": "₱",
      "confidence": {
        "name": 0.98,
        "item_context": 0.98,
        "unit_price": 0.99,
        "original_unit_price": null,
        "quantity": 0.95,
        "line_total": null,
        "currency": 0.99
      },
      "uncertain_fields": []
    }
  ],
  "charges": [],
  "discounts": [],
  "totals_by_currency": [
    {
      "currency": "PHP",
      "items_subtotal": "599.00",
      "items_subtotal_complete": true,
      "shipping_total": null,
      "tax_total": null,
      "other_charges_total": null,
      "discount_total": null,
      "calculated_payable_total": null,
      "payable_total_complete": false,
      "displayed_items_subtotal": null,
      "displayed_shipping_total": null,
      "displayed_tax_total": null,
      "displayed_other_charges_total": null,
      "displayed_discount_total": null,
      "visible_checkout_total": null,
      "visible_checkout_total_confidence": null
    }
  ],
  "unassigned_visible_totals": [],
  "checkout_breakdown_status": "not_shown",
  "requires_review": false,
  "warnings": []
}
```

`item_context` can be `cart_item`, `selected_product`, `listing_product`, `recommendation`, or `unknown`. Listing and recommendation products are returned for context but excluded from purchase subtotals. Unknown quantity or currency prevents line-total calculation. A bare `$` is preserved as a symbol and does not imply USD. Confidence scores describe rough visual certainty; they are not calibrated probabilities.

`line_total` contains only a Python-calculated value. `displayed_line_total` preserves the value visible in the screenshot. If both exist and differ, the response includes a warning and sets `requires_review`.

`shipping_total`, `tax_total`, and `other_charges_total` contain identified component amounts. Discounts already reflected in current item prices are not subtracted again. `discount_total` is the additional amount eligible to subtract from current item prices when the screenshot clearly establishes its scope.

A valid non-shopping screenshot returns HTTP 200, `screen_type: "unknown"`, an empty item list, and a warning.

## Errors

Error bodies have the form `{"detail":{"code":"...","message":"..."}}`.

| Status | Meaning |
|---|---|
| 400 | Empty, malformed, or content/MIME-mismatched image |
| 401 | Missing, invalid, or expired guest session |
| 413 | Upload too large or decoded dimensions exceed limits |
| 415 | Unsupported image format |
| 422 | Missing/invalid multipart request |
| 429 | Groq provider rate limit; retry manually after a delay |
| 500 | Unexpected internal error |
| 502 | Provider failure or invalid structured response |
| 503 | Groq key/model missing or provider unavailable |
| 504 | Provider timeout |

Provider retries are disabled to avoid repeated usage and latency. The service limits concurrent analysis calls per backend process. The existing guest session store is also process-local; multi-worker deployments need shared session storage and shared rate limiting.

## Configuration

Copy the placeholders in `.env.example` into the ignored `backend/.env` file and set `GROQ_API_KEY`. The default vision model is `qwen/qwen3.8-27b`; it can be changed with `GROQ_VISION_MODEL` only to a model verified to support image input and the selected output mode. `GROQ_STRUCTURED_OUTPUT_MODE` defaults to `json_schema`; use `json_object` only for a verified vision model without JSON Schema mode, since local Pydantic validation still applies. `GROQ_TIMEOUT_SECONDS` defaults to 45 and `GROQ_MAX_OUTPUT_TOKENS` defaults to 2500. Do not put provider credentials in Android.

Screenshots are sent to the selected cloud provider for analysis. Avoid capturing unrelated personal or payment information. Review the provider organization's data-control settings before deployment.

## Local development URLs

- Backend on the development computer: `http://127.0.0.1:8000`
- Android emulator: `http://10.0.2.2:8000`
- Physical device: use the computer's reachable local network IP and allow the backend port through the local firewall.

Run Uvicorn from `backend/` with `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000` for emulator/device access. Add Android's normal `INTERNET` permission and implement capture/permission/selection/cropping in the Android app; those features are outside this backend change.

## Kotlin OkHttp example

The Android side supplies a cropped image as a `ByteArray` and the guest session token. This example contains no provider credentials:

```kotlin
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.Response
import org.json.JSONObject
import java.io.File
import java.io.IOException

fun analyzeShoppingScreenshot(
    client: OkHttpClient,
    baseUrl: String,
    guestSessionToken: String,
    croppedImageFile: File,
    onSuccess: (JSONObject) -> Unit,
    onError: (Int, String) -> Unit,
) {
    val body = MultipartBody.Builder()
        .setType(MultipartBody.FORM)
        .addFormDataPart(
            "image",
            croppedImageFile.name,
            croppedImageFile.asRequestBody("image/png".toMediaType()),
        )
        .build()

    val request = Request.Builder()
        .url("${baseUrl.trimEnd('/')}/shopping/analyze")
        .header("Authorization", "Bearer $guestSessionToken")
        .post(body)
        .build()

    client.newCall(request).enqueue(object : Callback {
        override fun onFailure(call: Call, e: IOException) {
            onError(-1, "Could not reach the backend.")
        }

        override fun onResponse(call: Call, response: Response) {
            response.use {
                val text = it.body?.string().orEmpty()
                if (it.isSuccessful) {
                    onSuccess(JSONObject(text))
                } else {
                    val message = runCatching {
                        JSONObject(text).getJSONObject("detail").optString("message")
                    }.getOrDefault("Shopping analysis failed.")
                    onError(it.code, message)
                }
            }
        }
    })
}
```

Set the media type to the actual cropped file format (`image/jpeg`, `image/png`, or `image/webp`). Use a temporary file only as needed by the Android networking stack and remove it after the request completes.

## Tests

From `backend/`, run `python -m pytest -q`. Tests use in-memory images and mocked provider responses; they do not require a Groq key. A live provider check requires valid Groq credentials and model access.
