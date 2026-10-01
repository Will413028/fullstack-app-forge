"""Validate P0a evidence and requirement dispositions; do not claim P0 completion."""
import argparse
import json
from pathlib import Path
import re

PIN = "893918c808ce7828cd4b9372967e064ed119bbaa"
EXPECTED_CHECKS = {
    "idempotent-insert", "payload-conflict-detectable", "concurrent-distinct-claims",
    "busy-run-not-reclaimed", "expired-lease-recovered", "stale-worker-fenced",
    "cancel-blocks-late-success", "event-replay-cursor", "event-unique-sequence",
    "crash-rolls-back-result-and-event", "database-restart-preserves-runs", "cgroup-limits",
    "scratch-disk-hard-limit", "memory-limit-kills-workload", "rootfs-write-denied",
    "controller-timeout-stops-workload",
}


def validate(root, plan_text=None):
    requirements = (root / "requirements.md").read_text()
    rows = re.findall(r"^\| (R\d+) \|(.+)\|$", requirements, re.M)
    expected = {f"R{i:02}" for i in range(1, 19)}
    if {rid for rid, _ in rows} != expected or len(rows) != 18:
        raise ValueError("requirement coverage must contain R01–R18 exactly once")
    for rid, row in rows:
        columns = [x.strip() for x in row.split("|")]
        if len(columns) != 4 or not all(columns) or not re.search(r"P[0-7]", columns[3]):
            raise ValueError("missing requirement disposition/stage: " + rid)
    inventory = json.loads((root / "p0-inventory.json").read_text())
    if inventory["revision"] != PIN or inventory["tracked_file_count"] != 386:
        raise ValueError("reference snapshot mismatch")
    for group, count in {"controllers": 56, "routes": 8, "entities": 6, "tools": 16,
                         "frontend_api": 27}.items():
        if len(inventory[group]) != count:
            raise ValueError("inventory count mismatch: " + group)
        for item in inventory[group]:
            if not item.get("source") or not item.get("disposition", "").strip() or item.get("requirement") not in expected:
                raise ValueError("missing source/disposition/requirement: " + group)
    if len({(x["method"], x["path"]) for x in inventory["controllers"]}) != 30:
        raise ValueError("endpoint union mismatch")
    interfaces = {x["interface"] for x in inventory["consumers"]}
    if not {"direct-eventsource", "direct-fetch"} <= interfaces:
        raise ValueError("direct stream/download consumers missing")
    if any(not x.get("disposition", "").strip() for x in inventory["consumers"]):
        raise ValueError("consumer disposition missing")
    results = json.loads((root / "p0-runtime-results.json").read_text())
    if (len(results["checks"]) != len(EXPECTED_CHECKS)
            or {x["name"] for x in results["checks"]} != EXPECTED_CHECKS
            or not all(x["passed"] is True for x in results["checks"])):
        raise ValueError("runtime evidence incomplete")
    if not results["cleanup"] or not all(x["removed"] for x in results["cleanup"]):
        raise ValueError("spike cleanup incomplete")
    plan = plan_text if plan_text is not None else (root.parent / (root.name + ".md")).read_text()
    p1 = plan.split("**P1.", 1)[1].split("**P2.", 1)[0]
    if not all(x in p1 for x in ("P0", "D4", "disk")):
        raise ValueError("P1 persistence/disk blockers missing")
    return {"requirements": 18, "endpoints": 30, "spike_checks": 16,
            "status": "P0a evidence valid; P0b and P1 remain pending"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    print(json.dumps(validate(parser.parse_args().root), ensure_ascii=False))
