import json
import time

from app.ai.tool_registry import build_registry
from app.providers.demo import DemoFinancialProvider


def test_registered_tools_use_demo_data_and_validated_args(db_factory):
    provider = DemoFinancialProvider()
    registry = build_registry(db_factory, provider.ensure_seeded)
    raw, metadata = __import__("asyncio").run(registry.execute("get_budget_status", '{"currency":"PHP"}', "alice"))
    result = json.loads(raw)
    assert metadata["ok"] is True
    assert result["source"] == "simulated"
    assert result["budgets"]
    assert all(b["currency"] == "PHP" for b in result["budgets"])


def test_tool_args_and_unregistered_tools_fail_closed(db_factory):
    registry = build_registry(db_factory, DemoFinancialProvider().ensure_seeded)
    import asyncio
    bad, bad_meta = asyncio.run(registry.execute("get_transactions", '{"limit":999}', "alice"))
    unknown, unknown_meta = asyncio.run(registry.execute("run_shell", '{"cmd":"whoami"}', "alice"))
    assert json.loads(bad)["error"] == "Tool arguments were invalid."
    assert bad_meta["reason"] == "invalid_arguments"
    assert json.loads(unknown)["error"] == "Tool is not available."
    assert unknown_meta["ok"] is False


def test_tool_purchase_and_currency_are_deterministic(db_factory):
    import asyncio
    registry = build_registry(db_factory, DemoFinancialProvider().ensure_seeded)
    raw, _ = asyncio.run(registry.execute("evaluate_purchase", '{"price":"3500.00","currency":"PHP","category":"Shopping"}', "alice"))
    result = json.loads(raw)
    assert result["source"] == "simulated"
    assert result["simulated"] is True
    assert result["verdict"] == "within_recorded_budget"
    assert result["currency"] == "PHP"


def test_tool_execution_timeout_is_bounded(db_factory):
    from app.ai.tool_registry import EmptyArgs
    import asyncio
    registry = build_registry(db_factory, DemoFinancialProvider().ensure_seeded, timeout_seconds=0.01)

    def slow_handler(db, user_id, args):
        time.sleep(0.1)
        return {"value": 1}

    registry.register("slow_read", "test timeout", EmptyArgs, slow_handler)
    raw, metadata = asyncio.run(registry.execute("slow_read", "{}", "alice"))
    assert json.loads(raw)["error"] == "The financial data tool timed out."
    assert metadata["reason"] == "timeout"


def test_demo_provider_never_mixes_fiction_into_existing_manual_records(db_factory):
    from datetime import datetime, timezone
    from decimal import Decimal
    from app.database.models import Transaction
    db = db_factory()
    try:
        db.add(Transaction(user_id="manual-user", description="Imported item", amount=Decimal("10.00"), currency="PHP", kind="expense", category="Other", status="posted", occurred_at=datetime.now(timezone.utc), source="manual"))
        db.commit()
        DemoFinancialProvider().ensure_seeded(db, "manual-user")
        assert db.query(Transaction).filter(Transaction.user_id == "manual-user", Transaction.source == "simulated").count() == 0
    finally:
        db.close()
