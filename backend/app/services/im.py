from app.core.config import get_settings
from app.im import DingTalkProvider, DingTalkWebhookProvider, FeishuProvider, FeishuWebhookProvider, ImMessage, ImProvider, WeComProvider, WeComWebhookProvider
from app.services.inventory import InventoryService
from app.services.warning import WarningService


class ImService:
    def __init__(self, warning_service: WarningService, inventory_service: InventoryService) -> None:
        self.warning_service = warning_service
        self.inventory_service = inventory_service

    def provider(self, platform: str) -> ImProvider:
        settings = get_settings()
        providers: dict[str, ImProvider] = {
            "wecom": WeComWebhookProvider(settings.wecom_webhook_url) if settings.wecom_webhook_url else WeComProvider(),
            "dingtalk": DingTalkWebhookProvider(settings.dingtalk_webhook_url) if settings.dingtalk_webhook_url else DingTalkProvider(),
            "feishu": FeishuWebhookProvider(settings.feishu_webhook_url) if settings.feishu_webhook_url else FeishuProvider(),
        }
        if platform not in providers:
            raise ValueError("不支持的 IM 平台")
        return providers[platform]

    async def daily_report(self, platform: str, recipient: str = "demo-user") -> dict[str, int | str]:
        provider = self.provider(platform)
        health = self.inventory_service.health()
        warning_count = len(self.warning_service.list())
        message = ImMessage("card", "库存健康度日报", f"库存资金占用 {health['inventory_value']}；呆滞金额 {health['stagnant_value']}；预警 {warning_count} 条")
        await provider.send_card(recipient, message)
        return {"platform": platform, "warnings": warning_count, "status": "sent"}
