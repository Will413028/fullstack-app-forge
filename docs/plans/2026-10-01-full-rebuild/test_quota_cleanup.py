"""Mock host attachment errors: never remove an image when state is unsafe."""
import importlib.util
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("quota", ROOT / "p0_quota_spike.py")
QUOTA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUOTA)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mutation-quota-", dir=ROOT)
        self.work = Path(self.temp.name) / "work"
        self.work.mkdir()
        self.mount = self.work / "mount"
        self.mount.mkdir()
        self.image = self.work / "image.dmg"
        self.image.write_bytes(b"mock image; never mounted")

    def tearDown(self):
        self.temp.cleanup()

    def test_attach_timeout_still_mounted_preserves_image(self):
        calls = []
        def fake(argv, **kwargs):
            calls.append(argv)
            if argv[1] == "detach":
                raise subprocess.TimeoutExpired(argv, 1)
            info = {"images": [{"image-path": str(self.image), "system-entities": [{"mount-point": str(self.mount)}]}]}
            return subprocess.CompletedProcess(argv, 0, plistlib.dumps(info), b"")
        with patch.object(QUOTA, "cmd", side_effect=fake):
            result = QUOTA.cleanup_probe([], self.mount, self.image, self.work, True)
        self.assertTrue(any(x[1] == "detach" for x in calls))
        self.assertFalse(result["detached"])
        self.assertFalse(result["temporary_files"])
        self.assertTrue(self.image.exists())

    def test_unknown_mount_state_preserves_image(self):
        with patch.object(QUOTA, "cmd", side_effect=RuntimeError("info failed")):
            result = QUOTA.cleanup_probe([], self.mount, self.image, self.work, False)
        self.assertFalse(result["detached"])
        self.assertTrue(self.image.exists())

    def test_confirmed_unmounted_cleans_only_owned_files(self):
        value = subprocess.CompletedProcess([], 0, plistlib.dumps({"images": []}), b"")
        with patch.object(QUOTA, "cmd", return_value=value):
            result = QUOTA.cleanup_probe([], self.mount, self.image, self.work, False)
        self.assertTrue(result["temporary_files"])
        self.assertFalse(self.work.exists())


if __name__ == "__main__":
    unittest.main()
