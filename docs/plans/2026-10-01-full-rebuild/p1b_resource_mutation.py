"""Break only the live run epoch predicate in this process; the PG regression must reject it."""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from forge.resources import ResourceStore  # noqa: E402


def unsafe_live(app, run, now, epoch):
    return (
        app["deleted_at"] is None and run["status"] == "running"
        and run["lease_until"] > now and run["deadline"] > now
    )


ResourceStore._live = staticmethod(unsafe_live)
result = pytest.main([
    "-q", str(ROOT / "backend/tests/test_run_store.py"),
    "-k", "reserved_resource_never_created_after_old_epoch",
])
if result != pytest.ExitCode.TESTS_FAILED:
    raise SystemExit("mutation was not rejected by the epoch regression")
print("PASS: removing run epoch fencing makes the resource create regression fail")
