import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class LlmProvider(ABC):
    @abstractmethod
    async def complete(self, messages: list[dict[str, str]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        raise NotImplementedError


class StubLlmProvider(LlmProvider):
    async def complete(self, messages: list[dict[str, str]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {"content": "已调用确定性业务工具，请查看返回的数据依据。", "tool_calls": []}


class AnthropicCompatibleProvider(LlmProvider):
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, token: str | None = None) -> None:
        settings = get_settings()
        self.base_url = settings.anthropic_base_url.rstrip("/")
        self.token = token or settings.anthropic_auth_token
        self.model = settings.anthropic_model
        self.timeout = settings.llm_timeout_seconds
        self.transport = transport

    async def complete(self, messages: list[dict[str, str]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError("LLM token is not configured")
        system = "\n".join(item["content"] for item in messages if item.get("role") == "system")
        user_messages = [item for item in messages if item.get("role") != "system"]
        payload: dict[str, Any] = {"model": self.model, "max_tokens": 1200, "messages": user_messages}
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = tools
        headers = {"x-api-key": self.token, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.post(f"{self.base_url}/v1/messages", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        content = "".join(item.get("text", "") for item in data.get("content", []) if item.get("type") == "text")
        return {"content": content, "tool_calls": [item for item in data.get("content", []) if item.get("type") == "tool_use"]}


class LlmGateway:
    def __init__(self, primary: LlmProvider | None = None, fallback: LlmProvider | None = None, private: LlmProvider | None = None) -> None:
        settings = get_settings()
        self.primary = primary or (AnthropicCompatibleProvider() if settings.llm_provider == "anthropic_compatible" and settings.anthropic_auth_token else StubLlmProvider())
        self.fallback = fallback or StubLlmProvider()
        self.private = private or StubLlmProvider()

    async def complete(self, messages: list[dict[str, str]], tools: list[dict[str, Any]] | None = None, sensitive: bool = False) -> dict[str, Any]:
        provider = self.private if sensitive else self.primary
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return await provider.complete(messages, tools)
            except (httpx.HTTPError, RuntimeError, TimeoutError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(1 + attempt)   # 递增间隔重试，抵御网关偶发失败
                    continue
        logger.warning("llm provider fallback after 3 attempts: %s", type(last_error).__name__ if last_error else "unknown")
        return await self.fallback.complete(messages, tools)
