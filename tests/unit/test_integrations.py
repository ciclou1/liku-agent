import time

import pytest

from app.api.rate_limit import SimpleRateLimiter
from app.auth.sso import CasProvider, LdapProvider, OidcProvider
from app.im import DingTalkProvider, FeishuProvider, ImMessage, LocalProvider, WeComProvider
from app.models.operations import RecommendationStatus, PurchaseRecommendationRecord
from app.services.chatbot import ControlledSql
from app.celery_app import run_batch_forecast
from app.algorithms.price import price_direction_backtest
from app.services.warning import WarningService
from app.services.price import PriceService


@pytest.mark.asyncio
async def test_im_providers_share_message_contract() -> None:
    for provider in (LocalProvider(), WeComProvider(), DingTalkProvider(), FeishuProvider()):
        result = await provider.send_text("user-1", ImMessage("text", "预警", "库存需要处理"))
        assert result["status"] == "sent"
        assert provider.sent[0]["content"] == "库存需要处理"


@pytest.mark.asyncio
async def test_sso_adapters_require_configuration(monkeypatch) -> None:
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "oidc_issuer_url", "")
    monkeypatch.setattr(settings, "oidc_jwks_url", "")
    monkeypatch.setattr(settings, "ldap_url", "")
    monkeypatch.setattr(settings, "cas_validate_url", "")
    for provider in (OidcProvider(), LdapProvider(), CasProvider()):
        with pytest.raises(ValueError, match="not configured"):
            await provider.authenticate("user-1")


def test_rate_limiter_blocks_after_limit() -> None:
    limiter = SimpleRateLimiter(limit=1, window_seconds=60)
    assert limiter.allow("client")
    assert not limiter.allow("client")


def test_recommendation_state_machine_requires_review_before_export() -> None:
    recommendation = PurchaseRecommendationRecord(status=RecommendationStatus.GENERATED)
    with pytest.raises(ValueError):
        recommendation.transition(RecommendationStatus.EXPORTED)
    recommendation.transition(RecommendationStatus.REVIEWED)
    recommendation.transition(RecommendationStatus.EXPORTED)
    with pytest.raises(ValueError):
        recommendation.transition(RecommendationStatus.REVIEWED)


def test_controlled_sql_limits_result_rows() -> None:
    rows = [{"sku": str(index)} for index in range(120)]
    assert len(ControlledSql().execute("SELECT * FROM inventory_snapshots", rows)) == 100


def test_batch_forecast_task_returns_structured_results() -> None:
    result = run_batch_forecast.run([{"sku": "A", "warehouse_id": "W1", "values": [1, 2, 3]}])
    assert result["status"] == "completed"
    assert result["results"][0]["sku"] == "A"


def test_price_direction_backtest() -> None:
    assert 0 <= price_direction_backtest([10, 11, 12, 13]) <= 1


@pytest.mark.asyncio
async def test_warning_push_uses_im_provider() -> None:
    provider = LocalProvider()
    result = await WarningService().push(provider)
    assert result["status"] == "sent"
    assert result["count"] == len(provider.sent)


def test_price_service_exposes_supplier_history() -> None:
    history = PriceService().history("M12-BOLT")
    assert len(history) == 4
    assert {item["supplier"] for item in history} == {"供应商-1", "供应商-2"}
