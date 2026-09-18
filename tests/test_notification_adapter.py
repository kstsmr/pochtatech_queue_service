import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.notification_adapter import (  # noqa: E402
    DemoNotificationAdapter,
    deliver_with_timeout,
    retry_delay_seconds,
)


class NotificationAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_log_mode_delivers(self):
        await deliver_with_timeout(
            DemoNotificationAdapter("log"),
            {"kind": "queue_approaching", "ticket_id": "ticket-1"},
            0.1,
        )

    async def test_unavailable_mode_is_reported(self):
        with self.assertRaises(ConnectionError):
            await deliver_with_timeout(
                DemoNotificationAdapter("unavailable"),
                {"kind": "window_called"},
                0.1,
            )

    async def test_timeout_mode_is_bounded(self):
        with self.assertRaises(TimeoutError):
            await deliver_with_timeout(
                DemoNotificationAdapter("timeout", timeout_delay_seconds=0.1),
                {"kind": "window_called"},
                0.01,
            )

    async def test_unknown_mode_fails_closed(self):
        with self.assertRaises(ValueError):
            await deliver_with_timeout(
                DemoNotificationAdapter("unknown"),
                {"kind": "window_called"},
                0.1,
            )

    def test_retry_backoff_is_bounded(self):
        self.assertEqual(retry_delay_seconds(1), 1)
        self.assertEqual(retry_delay_seconds(4), 8)
        self.assertEqual(retry_delay_seconds(100), 60)
