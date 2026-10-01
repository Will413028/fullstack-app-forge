import copy
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("loop_gate", Path(__file__).with_name("verify_loop_quota.py"))
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class LoopQuotaGateTests(unittest.TestCase):
    def setUp(self):
        items = {}
        for scope, minor in (("db", 1), ("artifact", 2)):
            items[scope + "-filesystem"] = {"configured_bytes": GATE.CAPACITY,
                "capacity_bytes": GATE.CAPACITY - 1048576, "fstype": "ext4", "uuid": scope,
                "source": f"/dev/loop{minor}", "device_number": f"7:{minor}"}
            items[scope + "-enospc"] = {"errno": 28, "written": 200000000}
        items["scope-isolation"] = {"independent_write": True}
        items["postgres-restart"] = {"marker": "42"}
        for name in ("volume-remount", "controller-remap"):
            items[name] = {"marker": "42", "db_uuid": "db"}
        self.result = {"checks": [{"name": k, "passed": True, "evidence": v} for k, v in items.items()],
                       "error": None, "remaining_loops": {}, "pending_attach": [],
                       "cleanup": {"containers": True, "volumes": True, "loop_devices": True,
                                   "backing_volume": True, "errors": []}}

    def item(self, name):
        return next(x for x in self.result["checks"] if x["name"] == name)["evidence"]

    def test_baseline(self):
        self.assertEqual(GATE.validate(self.result)["loop_quota_checks"], 8)

    def test_missing_scope(self):
        self.result["checks"][0] = copy.deepcopy(self.result["checks"][1])
        with self.assertRaisesRegex(ValueError, "identities"):
            GATE.validate(self.result)

    def test_wrong_capacity(self):
        self.item("db-filesystem")["configured_bytes"] *= 2
        with self.assertRaisesRegex(ValueError, "capacity"):
            GATE.validate(self.result)

    def test_wrong_mount_device(self):
        self.item("db-filesystem")["device_number"] = "0:41"
        with self.assertRaisesRegex(ValueError, "mount identity"):
            GATE.validate(self.result)

    def test_no_enospc(self):
        self.item("artifact-enospc")["errno"] = 0
        with self.assertRaisesRegex(ValueError, "ENOSPC"):
            GATE.validate(self.result)

    def test_shared_filesystem(self):
        self.item("artifact-filesystem")["uuid"] = "db"
        with self.assertRaisesRegex(ValueError, "not isolated"):
            GATE.validate(self.result)

    def test_remap_lost_identity(self):
        self.item("controller-remap")["db_uuid"] = "empty-new-image"
        with self.assertRaisesRegex(ValueError, "retained identity"):
            GATE.validate(self.result)

    def test_deferred_loop_detach(self):
        self.result["remaining_loops"] = {"db": {"device": "/dev/loop1"}}
        with self.assertRaisesRegex(ValueError, "cleanup"):
            GATE.validate(self.result)

    def test_failed_backing_cleanup(self):
        self.result["cleanup"]["backing_volume"] = False
        with self.assertRaisesRegex(ValueError, "cleanup"):
            GATE.validate(self.result)

    def test_unknown_daemon_mutation_even_with_clean_flags(self):
        self.result["uncertain_mutations"] = [{"operation": "exec", "reason": "timeout"}]
        with self.assertRaisesRegex(ValueError, "cleanup"):
            GATE.validate(self.result)


if __name__ == "__main__":
    unittest.main()
