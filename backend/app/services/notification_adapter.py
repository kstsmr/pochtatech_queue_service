import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class NotificationAdapter(Protocol):
    async def send(self, payload: dict[str, Any]) -> None: ...


@dataclass(frozen=True)
class DemoNotificationAdapter:
    mode: str = "log"
    timeout_delay_seconds: float = 4.0

    async def send(self, payload: dict[str, Any]) -> None:
        if self.mode == "unavailable":
            raise ConnectionError("demo notification service is unavailable")
        if self.mode == "timeout":
            await asyncio.sleep(self.timeout_delay_seconds)
            return
        if self.mode != "log":
            raise ValueError(f"unsupported demo notification mode: {self.mode}")
        logger.info(
            "demo_notification_delivered",
            extra={
                "notification_kind": payload.get("kind"),
                "ticket_id": payload.get("ticket_id"),
            },
        )


async def deliver_with_timeout(
    adapter: NotificationAdapter,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> None:
    await asyncio.wait_for(adapter.send(payload), timeout=timeout_seconds)


def retry_delay_seconds(attempts: int) -> int:
    return min(2 ** max(attempts - 1, 0), 60)
