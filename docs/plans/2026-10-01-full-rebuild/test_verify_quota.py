"""Mutations reject missing enforcement and incomplete detach evidence."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("quota_gate", ROOT / "verify_quota.py")
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class QuotaGateTests(unittest.TestCase):
    def setUp(self):
        self.result = {"checks": [{"name": name, "passed": True, "evidence":
                         {"errno": 28, "written": 100 * 1024 * 1024}} for name in sorted(GATE.EXPECTED)],
                       "error": None, "cleanup": {"containers": True, "detached": True,
                                                     "temporary_files": True, "errors": []}}

    def test_baseline(self):
        self.assertEqual(GATE.validate(self.result)["quota_checks"], 4)

    def test_missing_enforcement_cannot_be_replaced(self):
        index = next(i for i, item in enumerate(self.result["checks"]) if item["name"] == "docker-write-hard-limit")
        self.result["checks"][index]["name"] = "fixed-filesystem-mounted"
        with self.assertRaisesRegex(ValueError, "identities"):
            GATE.validate(self.result)

    def test_still_attached_rejected(self):
        self.result["cleanup"]["detached"] = False
        with self.assertRaisesRegex(ValueError, "cleanup"):
            GATE.validate(self.result)

    def test_write_reached_full_request_is_not_enforcement(self):
        item = next(x for x in self.result["checks"] if x["name"] == "docker-write-hard-limit")
        item["evidence"]["written"] = 512 * 1024 * 1024
        with self.assertRaisesRegex(ValueError, "ENOSPC"):
            GATE.validate(self.result)


if __name__ == "__main__":
    unittest.main()
