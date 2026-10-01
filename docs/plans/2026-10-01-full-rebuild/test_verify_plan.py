"""Mutation checks for missing coverage, inventory dispositions and P1 blockers."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("verify_plan", ROOT / "verify_plan.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PLAN = (ROOT.parent / (ROOT.name + ".md")).read_text()


class CoverageGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mutation-", dir=ROOT)
        self.root = Path(self.temp.name)
        for name in ("requirements.md", "p0-inventory.json", "p0-runtime-results.json"):
            shutil.copyfile(ROOT / name, self.root / name)

    def tearDown(self):
        self.temp.cleanup()

    def test_baseline(self):
        self.assertEqual(MODULE.validate(self.root, PLAN)["requirements"], 18)

    def test_missing_r15_fails(self):
        path = self.root / "requirements.md"
        path.write_text("\n".join(line for line in path.read_text().splitlines() if not line.startswith("| R15 |")))
        with self.assertRaisesRegex(ValueError, "coverage"):
            MODULE.validate(self.root, PLAN)

    def test_empty_disposition_fails(self):
        path = self.root / "p0-inventory.json"
        data = json.loads(path.read_text())
        data["controllers"][0]["disposition"] = ""
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "disposition"):
            MODULE.validate(self.root, PLAN)

    def test_missing_direct_stream_fails(self):
        path = self.root / "p0-inventory.json"
        data = json.loads(path.read_text())
        data["consumers"] = [x for x in data["consumers"] if x["interface"] != "direct-eventsource"]
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "consumers"):
            MODULE.validate(self.root, PLAN)

    def test_failed_cleanup_fails(self):
        path = self.root / "p0-runtime-results.json"
        data = json.loads(path.read_text())
        data["cleanup"][0]["removed"] = False
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "cleanup"):
            MODULE.validate(self.root, PLAN)

    def test_missing_p1_disk_blocker_fails(self):
        start, rest = PLAN.split("**P1.", 1)
        p1, tail = rest.split("**P2.", 1)
        with self.assertRaisesRegex(ValueError, "blockers"):
            MODULE.validate(self.root, start + "**P1." + p1.replace("disk", "storage") + "**P2." + tail)

    def test_duplicate_check_cannot_replace_oom(self):
        path = self.root / "p0-runtime-results.json"
        data = json.loads(path.read_text())
        index = next(i for i, check in enumerate(data["checks"]) if check["name"] == "memory-limit-kills-workload")
        data["checks"][index] = data["checks"][0].copy()
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "runtime evidence"):
            MODULE.validate(self.root, PLAN)


if __name__ == "__main__":
    unittest.main()
