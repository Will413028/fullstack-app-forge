import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import p0_loop_quota_spike as spike


class LoopOwnershipTests(unittest.TestCase):
    def identity(self, backing="8:1"):
        return spike.check_backing_identity(2049, 2049, "8:1", 42, spike.CAPACITY, "/dev/loop0",
            {"name": "/dev/loop0", "back-maj:min": backing, "back-ino": 42, "sizelimit": 0})

    def test_owned_filesystem_and_inode(self):
        self.assertEqual(self.identity()["backing_device"], "8:1")

    def test_same_inode_in_foreign_filesystem_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
            self.identity("8:2")

    def test_file_outside_backing_mount_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
            spike.check_backing_identity(2050, 2049, "8:1", 42, spike.CAPACITY, "/dev/loop0",
                {"name": "/dev/loop0", "back-maj:min": "8:1", "back-ino": 42, "sizelimit": 0})


class DockerUncertaintyTests(unittest.TestCase):
    def run_probe(self, mode):
        calls, volumes = [], set()

        def fake_run(argv, **kwargs):
            args = argv[1:]
            calls.append(args)
            output = b""
            if args[:2] == ["image", "inspect"]:
                if mode == "readonly-timeout":
                    raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
                output = b"sha256:fixture"
            elif args[:2] == ["volume", "create"]:
                volumes.add(args[-1])
            elif args[0] == "run" and mode == "run-nonzero":
                return subprocess.CompletedProcess(argv, 125, b"", b"daemon mutation unconfirmed")
            elif args[:2] == ["volume", "rm"]:
                volumes.discard(args[-1])
            elif args[0] == "exec":
                executable = args[2]
                if executable == "losetup" and "--find" in args:
                    if mode == "attach-timeout":
                        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
                    output = b"/dev/loop0"
                elif executable == "stat":
                    output = f"2049:42:{spike.CAPACITY}\n2049:1:4096".encode()
                elif executable == "cat":
                    output = b"1 0 8:1 / /images rw - ext4 /dev/root rw"
                elif executable == "losetup" and "--json" in args:
                    output = json.dumps({"loopdevices": [{"name": "/dev/loop0", "back-ino": 42,
                        "back-maj:min": "8:2", "sizelimit": 0}]}).encode()
                elif executable == "losetup" and "-j" in args and mode == "foreign-device":
                    output = b"/dev/loop0: []:42 (/images/db.raw)"
            return subprocess.CompletedProcess(argv, 0, output, b"")

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = Path(directory) / "result.json"
            with patch.object(spike.subprocess, "run", fake_run), patch.object(sys, "argv",
                    ["probe", "--execute", "--output", str(output)]), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    spike.main()
            result = json.loads(output.read_text())
        return result, calls, volumes

    def test_late_attach_cannot_follow_empty_query_and_delete_backing(self):
        result, calls, volumes = self.run_probe("attach-timeout")
        # A daemon can finish attach after the CLI timeout. The backing must still exist.
        self.assertIn(result["backing_volume"], volumes)
        self.assertFalse(result["cleanup"]["backing_volume"])
        self.assertTrue(result["uncertain_mutations"])
        self.assertFalse(any(call[0] == "rm" or call[:2] == ["volume", "rm"] for call in calls))
        self.assertFalse(any("-j" in call for call in calls))

    def test_nonzero_unconfirmed_run_retains_backing(self):
        result, _, volumes = self.run_probe("run-nonzero")
        self.assertIn(result["backing_volume"], volumes)
        self.assertFalse(result["cleanup"]["backing_volume"])
        self.assertTrue(result["uncertain_mutations"])

    def test_foreign_device_collision_refuses_detach_and_backing_deletion(self):
        result, calls, volumes = self.run_probe("foreign-device")
        self.assertIn(result["backing_volume"], volumes)
        self.assertFalse(result["cleanup"]["backing_volume"])
        self.assertFalse(any("--detach" in call for call in calls))
        self.assertIn("identity mismatch", result["error"])

    def test_readonly_timeout_has_no_daemon_mutation_to_reconcile(self):
        result, _, volumes = self.run_probe("readonly-timeout")
        self.assertEqual(result["uncertain_mutations"], [])
        self.assertTrue(result["cleanup"]["backing_volume"])
        self.assertFalse(volumes)


if __name__ == "__main__":
    unittest.main()
