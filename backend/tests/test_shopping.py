from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
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
    image_url = captured["messages"][1]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")
    if output_mode == "json_schema":
        assert captured["response_format"]["json_schema"]["strict"] is True
    else:
        assert captured["response_format"] == {"type": "json_object"}
        assert "JSON Schema to follow exactly" in captured["messages"][0]["content"]


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


def test_provider_timeout_is_bounded():
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


def test_provider_exception_text_and_session_token_are_not_logged(caplog):
    secret_like = "credential-must-not-appear"
    provider = FakeProvider(error=RuntimeError(secret_like))
    service = service_for(provider)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ShoppingServiceError):
            asyncio.run(service.analyze(image_bytes(), "image/png"))
    assert secret_like not in caplog.text


def test_provider_rate_limit_auth_and_connection_errors_map_safely():
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
    response = asyncio.run(service_for(FakeProvider()).analyze(image_bytes(), "image/png"))
    assert response.success is True
    assert list(tmp_path.iterdir()) == []


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
