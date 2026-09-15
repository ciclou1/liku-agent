from app.im.base import ImMessage, ImProvider
import httpx


class LocalProvider(ImProvider):
    platform = "local"

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send_text(self, recipient: str, message: ImMessage) -> dict[str, str]:
        record = {"platform": self.platform, "recipient": recipient, "title": message.title, "content": message.content}
        self.sent.append(record)
        return {"status": "sent", "platform": self.platform}


class WeComProvider(LocalProvider):
    platform = "wecom"


class DingTalkProvider(LocalProvider):
    platform = "dingtalk"


class FeishuProvider(LocalProvider):
    platform = "feishu"


class WebhookProvider(LocalProvider):
    def __init__(self, platform: str, endpoint: str | None = None, token: str | None = None) -> None:
        super().__init__()
        self.platform = platform
        self.endpoint = endpoint
        self.token = token

    async def send_text(self, recipient: str, message: ImMessage) -> dict[str, str]:
        if not self.endpoint:
            return await super().send_text(recipient, message)
        payload = {"recipient": recipient, "msg_type": message.message_type, "title": message.title, "content": message.content}
        headers = {"content-type": "application/json"}
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(self.endpoint, json=payload, headers=headers)
            response.raise_for_status()
        self.sent.append({"platform": self.platform, "recipient": recipient, "title": message.title, "content": message.content})
        return {"status": "sent", "platform": self.platform}


class WeComWebhookProvider(WebhookProvider):
    def __init__(self, endpoint: str | None = None, token: str | None = None) -> None:
        super().__init__("wecom", endpoint, token)


class DingTalkWebhookProvider(WebhookProvider):
    def __init__(self, endpoint: str | None = None, token: str | None = None) -> None:
        super().__init__("dingtalk", endpoint, token)


class FeishuWebhookProvider(WebhookProvider):
    def __init__(self, endpoint: str | None = None, token: str | None = None) -> None:
        super().__init__("feishu", endpoint, token)

