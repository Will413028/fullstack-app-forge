import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("linux_gate", ROOT / "verify_linux_quota.py")
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class LinuxQuotaGateTests(unittest.TestCase):
    def setUp(self):
        items = {name: {} for name in GATE.EXPECTED}
        for scope in ("db", "artifact"):
            items[f"{scope}-filesystem"] = {"configured_bytes": GATE.CAPACITY,
                "capacity_bytes": GATE.CAPACITY - 1048576, "fstype": "ext4",
                "uuid": scope, "source": "/dev/vd" + scope}
            items[f"{scope}-enospc"] = {"errno": 28, "written": 104857600}
        for step in ("guest-remount", "vm-restart"):
            items[step] = {"marker": "42", "db_uuid": "db"}
        items["scope-isolation"] = {"independent_write": True}
        items["postgres-restart"] = {"marker": "42"}
        self.result = {"checks": [{"name": k, "passed": True, "evidence": v}
                                  for k, v in items.items()], "error": None,
                       "cleanup": {"vm": True, "disks": True, "temporary_files": True, "errors": []}}

    def item(self, name):
        return next(c for c in self.result["checks"] if c["name"] == name)

    def test_baseline(self):
        self.assertEqual(GATE.validate(self.result)["linux_quota_checks"], 8)

    def test_wrong_capacity(self):
        self.item("db-filesystem")["evidence"]["configured_bytes"] *= 2
        with self.assertRaisesRegex(ValueError, "capacity"):
            GATE.validate(self.result)

    def test_mount_escape(self):
        self.item("db-filesystem")["evidence"]["source"] = "overlay"
        with self.assertRaisesRegex(ValueError, "identity"):
            GATE.validate(self.result)

    def test_missing_check(self):
        self.item("vm-restart")["name"] = "guest-remount"
        with self.assertRaisesRegex(ValueError, "identities"):
            GATE.validate(self.result)

    def test_no_enforcement(self):
        self.item("artifact-enospc")["evidence"]["errno"] = 0
        with self.assertRaisesRegex(ValueError, "ENOSPC"):
            GATE.validate(self.result)

    def test_restart_uuid_changed(self):
        self.item("vm-restart")["evidence"]["db_uuid"] = "new-empty-disk"
        with self.assertRaisesRegex(ValueError, "persistence"):
            GATE.validate(self.result)

    def test_cleanup_failed(self):
        self.result["cleanup"]["vm"] = False
        with self.assertRaisesRegex(ValueError, "cleanup"):
            GATE.validate(self.result)

    def test_scope_isolation_requires_write_evidence(self):
        self.item("scope-isolation")["evidence"] = {}
        with self.assertRaisesRegex(ValueError, "independent"):
            GATE.validate(self.result)

    def test_postgres_restart_requires_marker(self):
        self.item("postgres-restart")["evidence"] = {}
        with self.assertRaisesRegex(ValueError, "PostgreSQL"):
            GATE.validate(self.result)


if __name__ == "__main__":
    unittest.main()
