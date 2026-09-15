import copy
import json
from pathlib import Path
import unittest

from tools.check_priority import validate


class PriorityConfigTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "config" / "priority.yaml"
        self.config = json.loads(path.read_text(encoding="utf-8"))

    def test_default_is_valid(self):
        validate(self.config)

    def test_missing_and_unknown_fields_are_rejected(self):
        for field in self.config:
            with self.subTest(field=field):
                value = copy.deepcopy(self.config)
                del value[field]
                with self.assertRaises(ValueError):
                    validate(value)
        self.config["typo"] = 1
        with self.assertRaises(ValueError):
            validate(self.config)

    def test_bad_wait_values_are_rejected(self):
        for value in (0, -1, 241, True, 1.5, "20", None):
            with self.subTest(value=value):
                self.config["max_wait_minutes"]["walk_in"] = value
                with self.assertRaises(ValueError):
                    validate(self.config)

    def test_starvation_configuration_is_rejected(self):
        self.config["levels"]["overdue"] = self.config["levels"]["appointment"]
        with self.assertRaises(ValueError):
            validate(self.config)

    def test_inverted_appointment_priority_is_rejected(self):
        self.config["levels"]["appointment"] = 3
        with self.assertRaises(ValueError):
            validate(self.config)

    def test_zero_early_and_grace_are_supported(self):
        self.config["early_minutes"] = 0
        self.config["grace_minutes"] = 0
        validate(self.config)

    def test_unknown_version_is_rejected(self):
        self.config["schema_version"] = 2
        with self.assertRaises(ValueError):
            validate(self.config)

    def test_non_object_is_rejected(self):
        for value in (None, [], "config"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate(value)
