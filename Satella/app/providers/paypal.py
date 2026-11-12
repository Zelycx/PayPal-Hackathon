from app.core.exceptions import ServiceError


class PayPalXS2AProvider:
    """Placeholder boundary for an authorized PayPal XS2A AIS provider."""

    source_name = "paypal_xs2a"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    async def connect(self) -> None:
        raise ServiceError("integration_unavailable", "PayPal personal-account access is not configured or authorized.", 503)

    async def disconnect(self, user_id: str | None = None) -> None:
        raise ServiceError("integration_unavailable", "No PayPal personal-account connection exists.", 503)

    def get_accounts(self, db, user_id: str):
        raise ServiceError("integration_unavailable", "PayPal personal-account access is not configured or authorized.", 503)

    def get_transactions(self, db, user_id: str):
        raise ServiceError("integration_unavailable", "PayPal personal-account access is not configured or authorized.", 503)

    def get_sync_info(self, db, user_id: str):
        raise ServiceError("integration_unavailable", "PayPal personal-account access is not configured or authorized.", 503)
