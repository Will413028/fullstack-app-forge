"""Gate only for the loop/local-driver primitive; not product or host reboot."""
import argparse
import json
from pathlib import Path
import re

EXPECTED = {"db-filesystem", "artifact-filesystem", "db-enospc", "artifact-enospc", "scope-isolation",
            "postgres-restart", "volume-remount", "controller-remap"}
CAPACITY = 256 * 1024 * 1024


def validate(result):
    checks = result["checks"]
    if len(checks) != 8 or {c["name"] for c in checks} != EXPECTED:
        raise ValueError("loop quota identities incomplete")
    if result["error"] is not None or any(c["passed"] is not True for c in checks):
        raise ValueError("loop quota check failed")
    evidence = {c["name"]: c["evidence"] for c in checks}
    sources, uuids = [], []
    for scope in ("db", "artifact"):
        fs = evidence[scope + "-filesystem"]
        if (fs["configured_bytes"] != CAPACITY or fs["fstype"] != "ext4" or not fs["uuid"]
                or not CAPACITY // 2 < fs["capacity_bytes"] <= CAPACITY
                or not re.fullmatch(r"/dev/loop(?:[0-9]|[12][0-9]|3[01])", fs["source"])):
            raise ValueError("loop quota capacity or filesystem invalid")
        expected_minor = int(fs["source"].removeprefix("/dev/loop"))
        if fs["device_number"] != f"7:{expected_minor}":
            raise ValueError("loop quota mount identity mismatch")
        sources.append(fs["source"])
        uuids.append(fs["uuid"])
        write = evidence[scope + "-enospc"]
        if write["errno"] != 28 or not 0 < write["written"] < fs["capacity_bytes"]:
            raise ValueError("loop quota ENOSPC invalid")
    if len(set(sources)) != 2 or len(set(uuids)) != 2:
        raise ValueError("loop quota scopes not isolated")
    if evidence["scope-isolation"].get("independent_write") is not True:
        raise ValueError("loop quota independent write missing")
    if evidence["postgres-restart"].get("marker") != "42":
        raise ValueError("loop quota PostgreSQL marker missing")
    for step in ("volume-remount", "controller-remap"):
        if evidence[step]["marker"] != "42" or evidence[step]["db_uuid"] != uuids[0]:
            raise ValueError("loop quota retained identity invalid")
    cleanup = result["cleanup"]
    if (cleanup["errors"] or not all(cleanup[k] is True for k in
            ("containers", "volumes", "loop_devices", "backing_volume"))
            or result["remaining_loops"] or result["pending_attach"] or result.get("uncertain_mutations")):
        raise ValueError("loop quota cleanup incomplete")
    return {"loop_quota_checks": 8, "status": "primitive passed; product/host reboot acceptance pending"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, default=Path(__file__).with_name("p0-loop-quota-results.json"))
    print(json.dumps(validate(json.loads(parser.parse_args().result.read_text()))))
