import pytest
import httpx

from app.core.llm import AnthropicCompatibleProvider, LlmGateway, LlmProvider, StubLlmProvider
from app.services.chatbot import ChatbotService
from app.services.im import ImService
from app.services.inventory import InventoryService
from app.services.warning import WarningService


class BrokenProvider(LlmProvider):
    async def complete(self, messages: list[dict[str, str]], tools: list[dict] | None = None) -> dict:
        raise RuntimeError("provider unavailable")


@pytest.mark.asyncio
async def test_llm_gateway_falls_back_without_exposing_secrets() -> None:
    gateway = LlmGateway(primary=BrokenProvider(), fallback=StubLlmProvider())
    result = await gateway.complete([{ "role": "user", "content": "库存" }])
    assert result["content"]
    assert "sk-" not in result["content"]


@pytest.mark.asyncio
async def test_chatbot_audits_tool_use_and_sources() -> None:
    service = ChatbotService(LlmGateway(primary=StubLlmProvider(), fallback=StubLlmProvider()))
    result = await service.chat("M12 螺栓哪个仓库有现货？")
    assert result["tool_name"] == "query_inventory"
    assert result["sources"]
    assert service.audit_events[0]["action"] == "chat_tool"


@pytest.mark.asyncio
async def test_llm_sensitive_route_and_daily_report() -> None:
    private = StubLlmProvider()
    gateway = LlmGateway(primary=BrokenProvider(), fallback=StubLlmProvider(), private=private)
    assert (await gateway.complete([], sensitive=True))["content"]
    report = await ImService(WarningService(), InventoryService()).daily_report("feishu")
    assert report["status"] == "sent"


@pytest.mark.asyncio
async def test_anthropic_compatible_provider_uses_messages_contract() -> None:
    observed: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["payload"] = request.content
        observed["headers"] = request.headers
        return httpx.Response(200, json={"content": [{"type": "text", "text": "已完成"}]})

    provider = AnthropicCompatibleProvider(transport=httpx.MockTransport(handler), token="test-token")
    result = await provider.complete([{"role": "system", "content": "约束"}, {"role": "user", "content": "查询"}])
    assert result["content"] == "已完成"
    assert observed["url"].endswith("/v1/messages")
    assert b"system" in observed["payload"]
