"""Evidence gate for the two-scope Linux disk primitive, not product acceptance."""
import argparse
import json
from pathlib import Path

EXPECTED = {"db-filesystem", "artifact-filesystem", "db-enospc", "artifact-enospc",
            "scope-isolation", "postgres-restart", "guest-remount", "vm-restart"}
CAPACITY = 256 * 1024 * 1024


def validate(result):
    checks = result["checks"]
    if len(checks) != len(EXPECTED) or {c["name"] for c in checks} != EXPECTED:
        raise ValueError("Linux quota identities incomplete")
    if result["error"] is not None or any(c["passed"] is not True for c in checks):
        raise ValueError("Linux quota check failed")
    indexed = {c["name"]: c["evidence"] for c in checks}
    for scope in ("db", "artifact"):
        fs = indexed[f"{scope}-filesystem"]
        if (fs["configured_bytes"] != CAPACITY or fs["fstype"] != "ext4"
                or not CAPACITY // 2 < fs["capacity_bytes"] <= CAPACITY
                or not fs["uuid"] or not fs["source"].startswith("/dev/")):
            raise ValueError("Linux quota capacity or filesystem identity invalid")
        write = indexed[f"{scope}-enospc"]
        if write["errno"] != 28 or not 0 < write["written"] < fs["capacity_bytes"]:
            raise ValueError("Linux quota ENOSPC evidence invalid")
    if indexed["db-filesystem"]["uuid"] == indexed["artifact-filesystem"]["uuid"]:
        raise ValueError("Linux quota scopes share filesystem")
    if indexed["scope-isolation"].get("independent_write") is not True:
        raise ValueError("Linux quota independent scope write missing")
    if indexed["postgres-restart"].get("marker") != "42":
        raise ValueError("Linux quota PostgreSQL restart evidence missing")
    for step in ("guest-remount", "vm-restart"):
        proof = indexed[step]
        if proof["marker"] != "42" or proof["db_uuid"] != indexed["db-filesystem"]["uuid"]:
            raise ValueError("Linux quota persistence identity invalid")
    cleanup = result["cleanup"]
    if cleanup["errors"] or not all(cleanup[k] is True for k in ("vm", "disks", "temporary_files")):
        raise ValueError("Linux quota cleanup incomplete")
    return {"linux_quota_checks": len(EXPECTED), "status": "primitive passed; product profile pending"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, default=Path(__file__).with_name("p0-linux-quota-results.json"))
    print(json.dumps(validate(json.loads(parser.parse_args().result.read_text()))))
