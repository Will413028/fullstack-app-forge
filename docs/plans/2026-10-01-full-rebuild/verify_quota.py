"""Check the bounded-volume probe evidence; not a production DB recovery gate."""
import argparse
import json
from pathlib import Path

EXPECTED = {"fixed-filesystem-mounted", "docker-write-hard-limit",
            "postgres-restart-after-full", "postgres-image-remount-persistence"}


def validate(result):
    checks = result["checks"]
    if len(checks) != 4 or {item["name"] for item in checks} != EXPECTED:
        raise ValueError("quota check identities incomplete")
    if result["error"] is not None or not all(item["passed"] is True for item in checks):
        raise ValueError("quota probe failed")
    cleanup = result["cleanup"]
    if cleanup.get("errors") or not all(cleanup.get(key) is True
                                        for key in ("containers", "detached", "temporary_files")):
        raise ValueError("quota cleanup incomplete")
    evidence = next(item["evidence"] for item in checks if item["name"] == "docker-write-hard-limit")
    if evidence["errno"] != 28 or not 0 < evidence["written"] < 256 * 1024 * 1024:
        raise ValueError("hard-limit ENOSPC evidence invalid")
    return {"quota_checks": 4, "status": "256MiB isolated probe passed; product validation pending"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, default=Path(__file__).resolve().parent / "p0-quota-results.json")
    print(json.dumps(validate(json.loads(parser.parse_args().result.read_text()))))
