import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.priority import bind_priority_sql, effective_priority, queue_order_key  # noqa: E402


class PriorityOrderTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "config" / "priority.yaml").read_text(encoding="utf-8"))
        self.now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)

    def ticket(self, ticket_id, source, minutes_waiting, sequence, **extra):
        return {
            "id": ticket_id,
            "source": source,
            "eligible_at": self.now - timedelta(minutes=minutes_waiting),
            "scheduled_time": extra.get("scheduled_time"),
            "target_window_id": extra.get("target_window_id"),
            "queue_sequence": sequence,
        }

    def test_appointment_outranks_ordinary_ticket(self):
        qr = self.ticket("qr", "qr", 5, 1)
        appointment = self.ticket(
            "appointment", "prebooking", 5, 2,
            scheduled_time=self.now + timedelta(minutes=5),
        )
        ordered = sorted(
            [qr, appointment],
            key=lambda item: queue_order_key(item, now=self.now, config=self.config),
        )
        self.assertEqual([item["id"] for item in ordered], ["appointment", "qr"])

    def test_overdue_walk_in_outranks_appointment_and_directed_ticket(self):
        overdue = self.ticket("walk", "walk_in", 20, 1)
        appointment = self.ticket(
            "appointment", "prebooking", 3, 2,
            scheduled_time=self.now,
        )
        directed = self.ticket("directed", "qr", 2, 3, target_window_id="w1")
        ordered = sorted(
            [directed, appointment, overdue],
            key=lambda item: queue_order_key(item, now=self.now, config=self.config),
        )
        self.assertEqual([item["id"] for item in ordered], ["walk", "appointment", "directed"])

    def test_qr_and_walk_in_share_fifo_at_equal_level(self):
        first = self.ticket("first", "walk_in", 8, 1)
        second = self.ticket("second", "qr", 4, 2)
        ordered = sorted(
            [second, first],
            key=lambda item: queue_order_key(item, now=self.now, config=self.config),
        )
        self.assertEqual([item["id"] for item in ordered], ["first", "second"])

    def test_max_wait_boundary_is_overdue(self):
        level = effective_priority(
            source="walk_in",
            eligible_at=self.now - timedelta(minutes=self.config["max_wait_minutes"]["walk_in"]),
            scheduled_time=None,
            now=self.now,
            config=self.config,
        )
        self.assertEqual(level, self.config["levels"]["overdue"])

    def test_direction_does_not_break_fifo(self):
        general = self.ticket("general", "qr", 5, 1)
        directed = self.ticket("directed", "qr", 5, 2, target_window_id="w1")
        ordered = sorted(
            [general, directed],
            key=lambda item: queue_order_key(item, now=self.now, config=self.config),
        )
        self.assertEqual([item["id"] for item in ordered], ["general", "directed"])

    def test_priority_sql_accepts_only_fixed_alias_and_one_marker(self):
        statement = bind_priority_sql("ORDER BY /* PRIORITY_EXPRESSION */", "t")
        self.assertIn("t.source", statement)
        self.assertNotIn("PRIORITY_EXPRESSION", statement)
        with self.assertRaises(ValueError):
            bind_priority_sql("ORDER BY /* PRIORITY_EXPRESSION */", "untrusted")
        with self.assertRaises(ValueError):
            bind_priority_sql("SELECT 1", "t")


if __name__ == "__main__":
    unittest.main()
