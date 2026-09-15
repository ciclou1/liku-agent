from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ImMessage:
    message_type: str
    title: str
    content: str
    facts: dict[str, str | int | float] = field(default_factory=dict)


class ImProvider(ABC):
    platform: str

    @abstractmethod
    async def send_text(self, recipient: str, message: ImMessage) -> dict[str, str]:
        raise NotImplementedError

    async def send_card(self, recipient: str, message: ImMessage) -> dict[str, str]:
        return await self.send_text(recipient, message)


