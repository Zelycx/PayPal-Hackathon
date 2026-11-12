from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services import shopping_service as service_module
from app.services.session_service import SESSIONS, create_session
from app.schemas.shopping import (
    CheckoutBreakdownStatus,
    ShoppingExtraction,
    extraction_json_schema,
)
from app.services.shopping_service import (
    DEFAULT_VISION_MODEL,
    MAX_UPLOAD_BYTES,
    ShoppingService,
    ShoppingServiceError,
    ShoppingSettings,
    GroqVisionProvider,
    build_public_response,
    get_shopping_service,
    parse_shopping_response,
    sanitize_image,
)


def image_bytes(image_format: str = "PNG", size: tuple[int, int] = (24, 12)) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", size, color=(245, 245, 245))
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def confidence(**overrides) -> dict:
    values = {
        "name": 0.99,
        "item_context": 0.99,
        "unit_price": 0.99,
        "original_unit_price": 0.99,
        "quantity": 0.99,
        "line_total": 0.99,
        "currency": 0.99,
    }
    values.update(overrides)
    return values


def product(
    *,
    name="Mouse",
    context="cart_item",
    price="10.00",
    original=None,
    quantity="1",
    line_total=None,
    currency="PHP",
    symbol="₱",
    confidence_values=None,
    uncertain_fields=None,
) -> dict:
    return {
        "name": name,
        "item_context": context,
        "unit_price": price,
        "original_unit_price": original,
        "quantity": quantity,
        "quantity_unit": "piece",
        "displayed_line_total": line_total,
        "currency": currency,
        "currency_symbol": symbol,
        "confidence": confidence(**(confidence_values or {})),
        "uncertain_fields": uncertain_fields or [],
    }


def extraction(**overrides) -> dict:
    values = {
        "screen_type": "cart",
        "products": [product()],
        "charges": [],
        "discounts": [],
        "visible_totals": [],
        "checkout_breakdown_status": "not_shown",
        "warnings": [],
    }
    values.update(overrides)
    return values


class FakeProvider:
    def __init__(self, response: str | None = None, error: Exception | None = None):
        self.response = response if response is not None else json.dumps(extraction())
        self.error = error
        self.calls = []

    async def analyze_image(self, image, mime_type, model, timeout_seconds, max_output_tokens, structured_output_mode):
        self.calls.append((image, mime_type, model, timeout_seconds, max_output_tokens, structured_output_mode))
        if self.error:
            raise self.error
        return self.response


def service_for(provider: FakeProvider) -> ShoppingService:
    return ShoppingService(
        vision_provider=provider,
        settings=ShoppingSettings(
            api_key=None,
            vision_model=DEFAULT_VISION_MODEL,
            timeout_seconds=45,
            max_output_tokens=2500,
            max_concurrent_requests=2,
        ),
    )


def run_image_sanitization_inline(monkeypatch):
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(service_module.asyncio, "to_thread", inline)


@pytest.fixture
def client():
    provider = FakeProvider()
    service = service_for(provider)
    app.dependency_overrides[get_shopping_service] = lambda: service
    try:
        with TestClient(app) as test_client:
            yield test_client, provider
    finally:
        app.dependency_overrides.pop(get_shopping_service, None)


def valid_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/session/start", json={"display_name": "Shopping test"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.parametrize(
    ("fmt", "mime"),
    [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")],
)
def test_image_formats_are_decoded_and_reencoded(fmt, mime):
    cleaned, actual_mime = sanitize_image(image_bytes(fmt), mime)
    assert actual_mime == mime
    with Image.open(io.BytesIO(cleaned)) as decoded:
        assert decoded.format == fmt
        assert decoded.size == (24, 12)


def test_image_validation_rejects_empty_malformed_unsupported_mismatch_and_oversize():
    cases = [
        (b"", "image/png", 10_000, 400),
        (b"not an image", "image/png", 10_000, 400),
        (image_bytes(), "image/gif", 10_000, 415),
        (image_bytes("JPEG"), "image/png", 10_000, 400),
        (image_bytes(), "image/png", 1, 413),
    ]
    for data, mime, maximum, status in cases:
        with pytest.raises(ShoppingServiceError) as error:
            sanitize_image(data, mime, maximum)
        assert error.value.status_code == status


def test_image_validation_rejects_excessive_dimensions(monkeypatch):
    monkeypatch.setattr(service_module, "MAX_IMAGE_WIDTH", 10)
    with pytest.raises(ShoppingServiceError) as error:
        sanitize_image(image_bytes(size=(11, 2)), "image/png")
    assert error.value.status_code == 413


def test_upload_over_ten_megabytes_is_rejected_by_route(client):
    test_client, _ = client
    headers = valid_headers(test_client)
    response = test_client.post(
        "/shopping/analyze",
        headers=headers,
        files={"image": ("large.png", b"x" * (MAX_UPLOAD_BYTES + 1), "image/png")},
    )
    assert response.status_code == 413


def test_shopping_endpoint_requires_valid_guest_session(client):
    test_client, _ = client
    valid_image = image_bytes()
    assert test_client.post(
        "/shopping/analyze", files={"image": ("cart.png", valid_image, "image/png")}
    ).status_code == 401
    assert test_client.post(
        "/shopping/analyze",
        headers={"Authorization": "Bearer invalid-token"},
        files={"image": ("cart.png", valid_image, "image/png")},
    ).status_code == 401


def test_expired_guest_session_is_rejected(client):
    test_client, _ = client
    headers = valid_headers(test_client)
    token = headers["Authorization"].removeprefix("Bearer ")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    SESSIONS[token_hash]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    response = test_client.post(
        "/shopping/analyze",
        headers=headers,
        files={"image": ("cart.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 401


def test_valid_guest_session_uses_shared_dependency_and_provider_never_receives_token(client):
    test_client, provider = client
    headers = valid_headers(test_client)
    token = headers["Authorization"].removeprefix("Bearer ")
    response = test_client.post(
        "/shopping/analyze",
        headers=headers,
        files={"image": ("cart.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert provider.calls
    assert token not in repr(provider.calls)
    assert provider.calls[0][1:] == ("image/png", DEFAULT_VISION_MODEL, 45, 2500, "json_schema")


def test_openapi_registers_one_multipart_endpoint_with_bearer_security():
    schema = app.openapi()
    route = schema["paths"]["/shopping/analyze"]["post"]
    assert route["requestBody"]["content"].get("multipart/form-data")
    assert route.get("security")
    assert "ShoppingResponse" in json.dumps(route["responses"]["200"])


@pytest.mark.parametrize("output_mode", ["json_schema", "json_object"])
def test_groq_adapter_sends_cropped_image_and_selected_output_mode(monkeypatch, output_mode):
    captured = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(content=json.dumps(extraction()))
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeGroq:
        def __init__(self, **kwargs):
            captured["client_config"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def close(self):
            captured["closed"] = True

    monkeypatch.setattr("groq.AsyncGroq", FakeGroq)
    result = asyncio.run(GroqVisionProvider("fake-provider-key").analyze_image(
        image_bytes(), "image/png", DEFAULT_VISION_MODEL, 45, 2500, output_mode
    ))
    assert json.loads(result)["screen_type"] == "cart"
    assert captured["client_config"]["max_retries"] == 0
    assert captured["max_completion_tokens"] == 2500
    assert captured["model"] == DEFAULT_VISION_MODEL
    assert captured["closed"] is True
    assert captured.get("reasoning_effort") == "none"
    assert "Return only one JSON object" in captured["messages"][0]["content"]
    assert "null for unknown scalar values and [] for empty arrays" in captured["messages"][0]["content"]
    assert "plain non-negative decimal strings" in captured["messages"][0]["content"]
    image_url = captured["messages"][1]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")
    assert base64.b64decode(image_url.split(",", 1)[1]) == image_bytes()
    if output_mode == "json_schema":
        assert captured["response_format"]["json_schema"]["strict"] is True
    else:
        assert captured["response_format"] == {"type": "json_object"}
        assert "JSON Schema to follow exactly" in captured["messages"][0]["content"]


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("The requested model is not available.", "model_not_found"),
        ("Invalid image format in image_url.", "invalid_request_error"),
        ("Image payload exceeds the provider limit.", "invalid_request_error"),
        ("The requested response_format is unsupported.", "invalid_request_error"),
    ],
)
def test_groq_bad_requests_log_safe_provider_diagnostics(message, category, caplog, monkeypatch):
    import httpx
    from groq import BadRequestError

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    provider_error = BadRequestError(
        message,
        response=httpx.Response(400, request=request),
        body={"error": {"type": category, "message": message}},
    )
    service = service_for(FakeProvider(error=provider_error))
    run_image_sanitization_inline(monkeypatch)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ShoppingServiceError) as error:
            asyncio.run(service.analyze(image_bytes(), "image/png"))
    assert error.value.code == "provider_request_rejected"
    assert error.value.status_code == 502
    assert "http_status=400" in caplog.text
    assert f"category={category}" in caplog.text
    assert f"message={message}" in caplog.text
    assert f"model={DEFAULT_VISION_MODEL}" in caplog.text
    assert "image_mime=image/png" in caplog.text
    assert "image_width=24" in caplog.text
    assert "image_height=12" in caplog.text
    assert "image_bytes=" in caplog.text
    assert "structured_output=json_schema" in caplog.text


def test_groq_adapter_logs_actual_api_status_without_request_payload(monkeypatch, caplog):
    import httpx
    from groq import BadRequestError

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    provider_error = BadRequestError(
        "Invalid response format.",
        response=httpx.Response(400, request=request),
        body={"error": {"type": "invalid_request_error", "message": "Invalid response format."}},
    )

    class FakeCompletions:
        async def create(self, **kwargs):
            raise provider_error

    class FakeGroq:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def close(self):
            pass

    monkeypatch.setattr("groq.AsyncGroq", FakeGroq)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ShoppingServiceError) as error:
            asyncio.run(GroqVisionProvider("fake-provider-key").analyze_image(
                image_bytes(), "image/png", DEFAULT_VISION_MODEL, 10, 2500, "json_schema"
            ))
    assert error.value.code == "provider_request_rejected"
    assert "http_status=400" in caplog.text
    assert "Invalid response format." in caplog.text
    assert "base64" not in caplog.text
    assert "fake-provider-key" not in caplog.text


def test_exact_groq_json_generation_error_falls_back_to_json_object_and_parses(monkeypatch, caplog):
    import httpx
    from groq import BadRequestError

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    sensitive_generation = json.dumps({
        "screen_type": "cart",
        "products": [{"name": "Private Person", "unit_price": "1500.50", "email": "person@example.com"}],
    })
    provider_error = BadRequestError(
        "Failed to generate JSON. Please adjust your prompt. See 'failed_generation' for more details.",
        response=httpx.Response(400, request=request),
        body={"error": {
            "type": "invalid_request_error",
            "message": "Failed to generate JSON. Please adjust your prompt. See 'failed_generation' for more details.",
            "failed_generation": sensitive_generation,
            "schema_path": "products.items.properties.unit_price",
            "schema_code": "invalid_type",
        }},
    )
    captured = {"requests": []}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured["requests"].append(kwargs)
            if len(captured["requests"]) == 1:
                raise provider_error
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(extraction())))])

    class FakeGroq:
        def __init__(self, **kwargs):
            captured["client_config"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def close(self):
            captured["closed"] = True

    monkeypatch.setattr("groq.AsyncGroq", FakeGroq)
    run_image_sanitization_inline(monkeypatch)
    service = ShoppingService(settings=ShoppingSettings(
        api_key="fake-provider-key",
        vision_model=DEFAULT_VISION_MODEL,
        timeout_seconds=10,
        max_output_tokens=2500,
        structured_output_mode="json_schema",
    ))
    with caplog.at_level(logging.WARNING):
        response = asyncio.run(service.analyze(image_bytes(), "image/png"))

    first_request, fallback_request = captured["requests"]
    assert first_request["response_format"]["type"] == "json_schema"
    assert first_request["response_format"]["json_schema"]["strict"] is True
    assert fallback_request["response_format"] == {"type": "json_object"}
    assert fallback_request["reasoning_effort"] == "none"
    assert captured["closed"] is True
    assert response.success is True
    assert response.items[0].name == "Mouse"
    assert "schema_path=products.items.properties.unit_price" in caplog.text
    assert '"field":"unit_price"' in caplog.text
    assert "Private Person" not in caplog.text
    assert "person@example.com" not in caplog.text
    assert "1500.50" not in caplog.text
    assert "fake-provider-key" not in caplog.text


def test_failed_generation_and_malformed_fallback_never_reach_api_error_message(monkeypatch, caplog):
    import httpx
    from groq import BadRequestError

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    provider_error = BadRequestError(
        "Failed to generate JSON. Please adjust your prompt. See 'failed_generation' for more details.",
        response=httpx.Response(400, request=request),
        body={"error": {
            "type": "invalid_request_error",
            "message": "Failed to generate JSON. Please adjust your prompt. See 'failed_generation' for more details.",
            "failed_generation": "Private Person person@example.com ₱1,500.50",
        }},
    )

    class FakeCompletions:
        async def create(self, **kwargs):
            if kwargs["response_format"]["type"] == "json_schema":
                raise provider_error
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not JSON: person@example.com"))])

    class FakeGroq:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def close(self):
            pass

    monkeypatch.setattr("groq.AsyncGroq", FakeGroq)
    with caplog.at_level(logging.WARNING):
        raw = asyncio.run(GroqVisionProvider("fake-provider-key").analyze_image(
            image_bytes(), "image/png", DEFAULT_VISION_MODEL, 10, 2500, "json_schema"
        ))
    with pytest.raises(ShoppingServiceError) as error:
        parse_shopping_response(raw)
    assert error.value.code == "invalid_ai_json"
    assert "person@example.com" not in error.value.message
    assert "person@example.com" not in caplog.text
    assert "Private Person" not in caplog.text
    assert "1,500.50" not in caplog.text


def test_provider_internals_are_not_returned_from_shopping_api():
    from app.api.shopping import _http_error

    mapped = _http_error(ShoppingServiceError(
        "provider_request_rejected",
        "Vision service could not process this image or model request.",
        502,
    ))
    response_body = json.dumps(mapped.detail)
    assert mapped.status_code == 502
    assert mapped.detail["code"] == "provider_request_rejected"
    assert "failed_generation" not in response_body
    assert "Private Person" not in response_body
    assert "person@example.com" not in response_body
    assert "1,500.50" not in response_body


def test_provider_diagnostics_redact_credentials_and_image_data(caplog):
    from app.services.shopping_service import _safe_provider_error

    class FakeStatusError(Exception):
        status_code = 400
        body = {
            "error": {
                "type": "invalid_request_error",
                "message": "Rejected data:image/png;base64," + ("A" * 150) + " gsk_sensitivevalue",
            }
        }

    _, _, message = _safe_provider_error(FakeStatusError())
    assert "data:image" not in message
    assert "A" * 120 not in message
    assert "gsk_sensitivevalue" not in message


def test_unsupported_image_format_and_oversize_are_rejected_before_provider_call(monkeypatch):
    provider = FakeProvider()
    service = service_for(provider)
    run_image_sanitization_inline(monkeypatch)
    with pytest.raises(ShoppingServiceError) as unsupported:
        asyncio.run(service.analyze(image_bytes(), "image/gif"))
    assert unsupported.value.code == "unsupported_image"
    assert unsupported.value.status_code == 415

    with pytest.raises(ShoppingServiceError) as oversized:
        asyncio.run(service.analyze(b"x" * (MAX_UPLOAD_BYTES + 1), "image/png"))
    assert oversized.value.code == "image_too_large"
    assert oversized.value.status_code == 413
    assert provider.calls == []


def test_single_and_multiple_product_decimal_calculations():
    data = extraction(products=[
        product(name="Mouse", price="599.99", quantity="2", original="799.99"),
        product(name="Cable", price="120.25", quantity="1.5"),
    ])
    response = build_public_response(ShoppingExtraction.model_validate(data))
    totals = response.totals_by_currency[0]
    assert [item.line_total for item in response.items] == ["1199.98", "180.375"]
    assert totals.items_subtotal == "1380.355"
    assert totals.items_subtotal_complete is True
    assert response.items[0].original_unit_price == "799.99"


def test_fractional_quantity_product_and_subtotal_preserve_decimal_precision():
    price = "123456789012345678.123456789012"
    quantity = "123456789012.123456"
    data = extraction(products=[
        product(price=price, quantity=quantity),
        product(name="Small fraction", price="0.000000000001", quantity="1"),
    ])
    with localcontext() as context:
        context.prec = 80
        expected_line = format(Decimal(price) * Decimal(quantity), "f")
        expected_subtotal = format(Decimal(expected_line) + Decimal("0.000000000001"), "f")

    response = build_public_response(ShoppingExtraction.model_validate(data))
    assert response.items[0].line_total == expected_line
    assert response.totals_by_currency[0].items_subtotal == expected_subtotal


def test_listing_and_recommendation_items_are_not_counted_as_purchases():
    response = build_public_response(ShoppingExtraction.model_validate(extraction(products=[
        product(name="Listing item", context="listing_product"),
        product(name="Suggested item", context="recommendation"),
    ], screen_type="product_listing")))
    assert len(response.items) == 2
    assert response.totals_by_currency == []


def test_same_product_in_listing_and_cart_is_counted_once_but_both_contexts_are_preserved():
    response = build_public_response(ShoppingExtraction.model_validate(extraction(products=[
        product(name="Mouse", context="cart_item", price="10.00", quantity="1"),
        product(name="Mouse", context="selected_product", price="10.00", quantity="1"),
    ])))
    assert len(response.items) == 2
    assert response.totals_by_currency[0].items_subtotal == "10.00"
    assert any("only the cart item is counted" in warning for warning in response.warnings)
    assert response.requires_review is True


def test_unknown_quantity_and_currency_are_not_guessed_or_counted():
    response = build_public_response(ShoppingExtraction.model_validate(extraction(products=[
        product(name="Unknown quantity", quantity=None),
        product(name="Unknown currency", currency=None, symbol="$"),
    ])))
    assert response.items[0].quantity is None
    assert response.items[0].line_total is None
    assert response.items[1].currency is None
    assert response.items[1].currency_symbol == "$"
    assert response.totals_by_currency[0].items_subtotal_complete is False
    assert response.requires_review is True


def test_low_confidence_price_is_returned_as_unknown_and_requires_review():
    response = build_public_response(ShoppingExtraction.model_validate(extraction(products=[
        product(confidence_values={"unit_price": 0.2}),
    ])))
    assert response.items[0].unit_price is None
    assert response.items[0].line_total is None
    assert "unit_price" in response.items[0].uncertain_fields
    assert response.requires_review is True


def test_displayed_line_total_mismatch_is_preserved_and_flagged():
    response = build_public_response(ShoppingExtraction.model_validate(extraction(products=[
        product(price="100.00", quantity="2", line_total="199.99"),
    ])))
    item = response.items[0]
    assert item.line_total == "200.00"
    assert item.displayed_line_total == "199.99"
    assert response.requires_review is True
    assert any("differs" in warning for warning in response.warnings)


def test_mixed_currencies_are_kept_in_separate_groups():
    response = build_public_response(ShoppingExtraction.model_validate(extraction(products=[
        product(name="Peso", price="10.00", currency="PHP"),
        product(name="Dollar", price="2.00", currency="USD", symbol="$"),
    ])))
    assert {item.currency: item.items_subtotal for item in response.totals_by_currency} == {
        "PHP": "10.00", "USD": "2.00"
    }


def test_checkout_payable_total_uses_only_explicit_components_and_decimal_math():
    high = 0.99
    data = extraction(
        screen_type="checkout",
        checkout_breakdown_status="complete",
        products=[product(price="100.00", quantity="1", line_total="100.00")],
        charges=[
            {"kind": "shipping", "amount": "10.00", "currency": "PHP", "currency_symbol": "₱", "description": "Shipping", "already_in_unit_prices": False, "confidence": high},
            {"kind": "tax", "amount": "5.00", "currency": "PHP", "currency_symbol": "₱", "description": "Tax", "already_in_unit_prices": False, "confidence": high},
            {"kind": "service_fee", "amount": "2.00", "currency": "PHP", "currency_symbol": "₱", "description": "Service fee", "already_in_unit_prices": False, "confidence": high},
        ],
        discounts=[{
            "kind": "voucher", "scope": "cart", "amount": "10.00", "currency": "PHP",
            "currency_symbol": "₱", "description": "Voucher",
            "already_reflected_in_current_prices": False,
            "applies_to_checkout_total": True, "confidence": high,
        }],
        visible_totals=[{
            "kind": "payable_total", "amount": "107.00", "currency": "PHP",
            "currency_symbol": "₱", "confidence": high,
        }],
    )
    result = build_public_response(ShoppingExtraction.model_validate(data))
    total = result.totals_by_currency[0]
    assert total.items_subtotal == "100.00"
    assert total.shipping_total == "10.00"
    assert total.tax_total == "5.00"
    assert total.other_charges_total == "2.00"
    assert total.discount_total == "10.00"
    assert total.calculated_payable_total == "107.00"
    assert total.payable_total_complete is True


def test_missing_checkout_component_is_not_assumed_zero():
    data = extraction(
        screen_type="checkout",
        checkout_breakdown_status="complete",
        products=[product()],
        charges=[{"kind": "shipping", "amount": "5.00", "currency": "PHP", "already_in_unit_prices": False, "confidence": 0.99}],
        discounts=[{"kind": "cart", "scope": "cart", "amount": "0", "currency": "PHP", "already_reflected_in_current_prices": False, "applies_to_checkout_total": True, "confidence": 0.99}],
    )
    result = build_public_response(ShoppingExtraction.model_validate(data))
    assert result.totals_by_currency[0].calculated_payable_total is None
    assert result.totals_by_currency[0].payable_total_complete is False


def test_discount_already_in_current_price_is_not_subtracted_twice():
    data = extraction(
        screen_type="checkout",
        checkout_breakdown_status="complete",
        products=[product(price="80.00", quantity="1")],
        charges=[
            {"kind": "shipping", "amount": "0", "currency": "PHP", "already_in_unit_prices": False, "confidence": 0.99},
            {"kind": "tax", "amount": "0", "currency": "PHP", "already_in_unit_prices": False, "confidence": 0.99},
            {"kind": "other", "amount": "0", "currency": "PHP", "already_in_unit_prices": False, "confidence": 0.99},
        ],
        discounts=[{
            "kind": "sale", "scope": "item", "amount": "20.00", "currency": "PHP",
            "already_reflected_in_current_prices": True, "applies_to_checkout_total": True,
            "confidence": 0.99,
        }],
    )
    result = build_public_response(ShoppingExtraction.model_validate(data))
    assert result.totals_by_currency[0].discount_total == "0"
    assert result.totals_by_currency[0].calculated_payable_total == "80.00"


def test_duplicate_charge_is_counted_once_and_reported():
    charge = {"kind": "shipping", "amount": "5.00", "currency": "PHP", "description": "Shipping", "already_in_unit_prices": False, "confidence": 0.99}
    data = extraction(charges=[charge, charge])
    result = build_public_response(ShoppingExtraction.model_validate(data))
    assert len(result.charges) == 1
    assert any("repeated charge" in warning for warning in result.warnings)


def test_non_shopping_screen_returns_success_with_empty_result():
    provider = FakeProvider(json.dumps(extraction(
        screen_type="unknown", products=[], charges=[], discounts=[], visible_totals=[]
    )))
    response = asyncio.run(service_for(provider).analyze(image_bytes(), "image/png"))
    assert response.success is True
    assert response.items == []
    assert response.totals_by_currency == []
    assert response.warnings


def test_malformed_ai_json_and_schema_are_controlled_errors():
    bad_json = service_for(FakeProvider("not json"))
    with pytest.raises(ShoppingServiceError) as error:
        asyncio.run(bad_json.analyze(image_bytes(), "image/png"))
    assert error.value.status_code == 502

    bad_schema = service_for(FakeProvider(json.dumps({"screen_type": "checkout", "unexpected": "value"})))
    with pytest.raises(ShoppingServiceError) as error:
        asyncio.run(bad_schema.analyze(image_bytes(), "image/png"))
    assert error.value.status_code == 502


def test_provider_timeout_is_bounded(monkeypatch):
    run_image_sanitization_inline(monkeypatch)
    provider = FakeProvider(error=asyncio.TimeoutError())
    service = ShoppingService(
        provider,
        ShoppingSettings(None, DEFAULT_VISION_MODEL, timeout_seconds=0.01, max_output_tokens=2500),
    )
    with pytest.raises(ShoppingServiceError) as error:
        asyncio.run(service.analyze(image_bytes(), "image/png"))
    assert error.value.status_code == 504


def test_missing_key_or_model_is_reported_without_provider_call():
    image = image_bytes()
    missing_key = ShoppingService(settings=ShoppingSettings(None, DEFAULT_VISION_MODEL))
    with pytest.raises(ShoppingServiceError) as error:
        asyncio.run(missing_key.analyze(image, "image/png"))
    assert error.value.status_code == 503

    provider = FakeProvider()
    missing_model = ShoppingService(provider, ShoppingSettings(None, ""))
    with pytest.raises(ShoppingServiceError) as error:
        asyncio.run(missing_model.analyze(image, "image/png"))
    assert error.value.status_code == 503
    assert not provider.calls


def test_provider_exception_text_and_session_token_are_not_logged(caplog, monkeypatch):
    run_image_sanitization_inline(monkeypatch)
    secret_like = "credential-must-not-appear"
    provider = FakeProvider(error=RuntimeError(secret_like))
    service = service_for(provider)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ShoppingServiceError):
            asyncio.run(service.analyze(image_bytes(), "image/png"))
    assert secret_like not in caplog.text


def test_provider_rate_limit_auth_and_connection_errors_map_safely(monkeypatch):
    run_image_sanitization_inline(monkeypatch)
    import httpx
    from groq import APIConnectionError, AuthenticationError, RateLimitError

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    rate = RateLimitError("sensitive provider message", response=httpx.Response(429, request=request), body={"secret": "x"})
    auth = AuthenticationError("sensitive provider message", response=httpx.Response(401, request=request), body={"secret": "x"})
    unavailable = APIConnectionError(request=request)
    for error, expected in ((rate, 429), (auth, 503), (unavailable, 503)):
        with pytest.raises(ShoppingServiceError) as mapped:
            asyncio.run(service_for(FakeProvider(error=error)).analyze(image_bytes(), "image/png"))
        assert mapped.value.status_code == expected
        assert "sensitive provider message" not in mapped.value.message


def test_ai_free_text_warnings_are_not_echoed_to_api():
    private_text = "unrelated-private-number-12345"
    result = build_public_response(ShoppingExtraction.model_validate(extraction(warnings=[private_text])))
    assert private_text not in json.dumps(result.model_dump(mode="json"))


def test_service_processes_image_without_writing_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_image_sanitization_inline(monkeypatch)
    response = asyncio.run(service_for(FakeProvider()).analyze(image_bytes(), "image/png"))
    assert response.success is True
    assert list(tmp_path.iterdir()) == []


def test_service_valid_ai_response_is_returned():
    # Exercise the same provider response string that ShoppingService validates.
    response = build_public_response(parse_shopping_response(FakeProvider().response))
    assert response.success is True
    assert response.items[0].name == "Mouse"


def test_service_accepts_missing_optional_ai_fields():
    minimal = {"screen_type": "product_detail", "products": [{"name": "Cable", "item_context": "selected_product"}]}
    parsed = parse_shopping_response(FakeProvider(json.dumps(minimal)).response)
    assert parsed.products[0].name == "Cable"
    assert parsed.products[0].unit_price is None
    assert parsed.products[0].confidence.name is None


def monetary_extraction(value):
    data = extraction(products=[product(currency=None, symbol=None)])
    data["products"][0].update({
        "unit_price": value,
        "original_unit_price": value,
        "displayed_line_total": value,
    })
    data["charges"] = [{"kind": "shipping", "amount": value, "currency": None, "confidence": 0.99}]
    data["discounts"] = [{"kind": "sale", "scope": "item", "amount": value, "currency": None, "confidence": 0.99}]
    data["visible_totals"] = [{"kind": "items_subtotal", "amount": value, "currency": None, "confidence": 0.99}]
    return data


def parsed_monetary_values(value):
    parsed = parse_shopping_response(FakeProvider(json.dumps(monetary_extraction(value))).response)
    return [
        parsed.products[0].unit_price,
        parsed.products[0].original_unit_price,
        parsed.products[0].displayed_line_total,
        parsed.charges[0].amount,
        parsed.discounts[0].amount,
        parsed.visible_totals[0].amount,
    ], parsed


@pytest.mark.parametrize(
    ("value", "expected", "expected_currency", "expected_symbol"),
    [
        (1234, "1234", None, None),
        (1234.5, "1234.5", None, None),
        ("1234.500", "1234.500", None, None),
        ("0", "0", None, None),
        ("1,234.50", "1234.50", None, None),
        ("₱1,234.50", "1234.50", None, "₱"),
        ("$1,234.50", "1234.50", None, "$"),
        ("USD 1,234.50", "1234.50", "USD", None),
        ("PHP 2,000", "2000", "PHP", None),
        ("0.123456789012345678", "0.123456789012345678", None, None),
    ],
)
def test_all_six_monetary_fields_normalize_valid_values(value, expected, expected_currency, expected_symbol):
    values, parsed = parsed_monetary_values(value)
    assert values == [expected] * 6
    assert parsed.products[0].currency == expected_currency
    assert parsed.products[0].currency_symbol == expected_symbol
    assert parsed.charges[0].currency == expected_currency
    assert parsed.discounts[0].currency == expected_currency
    assert parsed.visible_totals[0].currency == expected_currency


def test_all_six_monetary_fields_preserve_null_values():
    values, parsed = parsed_monetary_values(None)
    assert values == [None] * 6
    assert parsed.products[0].currency is None
    assert parsed.charges[0].currency is None


def test_full_shopping_service_normalizes_groq_monetary_response(monkeypatch):
    run_image_sanitization_inline(monkeypatch)
    provider = FakeProvider(json.dumps(monetary_extraction("₱1,500.50")))
    response = asyncio.run(service_for(provider).analyze(image_bytes(), "image/png"))
    assert response.success is True
    assert response.items[0].unit_price == "1500.50"
    assert response.items[0].original_unit_price == "1500.50"
    assert response.items[0].displayed_line_total == "1500.50"
    assert response.items[0].currency is None
    assert response.items[0].currency_symbol == "₱"
    assert response.charges[0].amount == "1500.50"
    assert response.charges[0].currency is None


@pytest.mark.parametrize("value", [-12, -12.5, "-12.50", "", "1,23.45", "12.34.56", "$", "(12.00)"])
def test_all_six_monetary_fields_reject_negative_or_malformed_values(value):
    with pytest.raises(ShoppingServiceError) as error:
        parse_shopping_response(FakeProvider(json.dumps(monetary_extraction(value))).response)
    assert error.value.code == "invalid_ai_schema"


def test_currency_formatted_amount_conflicting_with_currency_metadata_is_rejected():
    data = monetary_extraction("$10.00")
    data["products"][0]["currency_symbol"] = "€"
    with pytest.raises(ShoppingServiceError) as error:
        parse_shopping_response(FakeProvider(json.dumps(data)).response)
    assert error.value.code == "invalid_ai_schema"


def test_validation_diagnostics_report_all_money_paths_without_echoing_values(caplog):
    data = monetary_extraction("not-a-price-secret")
    with pytest.raises(ShoppingServiceError):
        parse_shopping_response(FakeProvider(json.dumps(data)).response)
    logged = caplog.text
    for field in (
        "products.0.unit_price",
        "products.0.original_unit_price",
        "products.0.displayed_line_total",
        "charges.0.amount",
        "discounts.0.amount",
        "visible_totals.0.amount",
    ):
        assert field in logged
    assert "plain decimal string" in logged
    assert "non-negative decimal amount" in logged
    assert "not-a-price-secret" not in logged


def test_service_accepts_markdown_wrapped_json():
    wrapped = "```json\n" + json.dumps(extraction()) + "\n```"
    response = build_public_response(parse_shopping_response(FakeProvider(wrapped).response))
    assert response.success is True


def test_service_distinguishes_invalid_json_from_schema_validation_errors():
    with pytest.raises(ShoppingServiceError) as json_error:
        parse_shopping_response(FakeProvider("not json").response)
    assert json_error.value.code == "invalid_ai_json"
    assert json_error.value.status_code == 502

    invalid_schema = extraction()
    invalid_schema["products"][0]["confidence"]["unit_price"] = "high"
    with pytest.raises(ShoppingServiceError) as schema_error:
        parse_shopping_response(FakeProvider(json.dumps(invalid_schema)).response)
    assert schema_error.value.code == "invalid_ai_schema"
    assert schema_error.value.status_code == 502


def test_service_rejects_unexpected_ai_response_structure():
    with pytest.raises(ShoppingServiceError) as error:
        parse_shopping_response(FakeProvider(json.dumps({"result": {"products": []}})).response)
    assert error.value.code == "invalid_ai_schema"


def test_different_screenshot_responses_validate_independently():
    first_data = extraction(products=[product(name="Mouse", price="10.00")])
    second_data = extraction(products=[product(name="Keyboard", price="25.50")])
    first = FakeProvider(json.dumps(first_data))
    second = FakeProvider(json.dumps(second_data))
    first_response = build_public_response(parse_shopping_response(first.response))
    second_response = build_public_response(parse_shopping_response(second.response))
    assert first_response.items[0].name == "Mouse"
    assert second_response.items[0].name == "Keyboard"


def test_extraction_schema_is_strict_at_every_object_level():
    schema = extraction_json_schema()

    def assert_strict(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node.get("required", [])) == set(node.get("properties", {}))
            for value in node.values():
                assert_strict(value)
        elif isinstance(node, list):
            for value in node:
                assert_strict(value)

    assert_strict(schema)


def test_public_schema_rejects_nan_confidence_and_non_decimal_money():
    invalid = extraction(products=[product(confidence_values={"unit_price": float("nan")})])
    with pytest.raises(ValueError):
        ShoppingExtraction.model_validate(invalid)
    invalid = extraction(products=[product(price="NaN")])
    with pytest.raises(ValueError):
        ShoppingExtraction.model_validate(invalid)
