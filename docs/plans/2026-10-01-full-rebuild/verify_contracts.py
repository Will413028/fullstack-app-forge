"""Draft topology/security/evidence checks, not full OpenAPI/JSON Schema validation."""
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
EXPECTED_OPS = {"register", "login", "me", "logout", "createApp", "getApp", "createRun",
                "getRun", "cancelRun", "streamEvents"}
EXPECTED_DB = {"own-app-crud", "other-app-connect-denied", "platform-connect-denied",
               "ddl-denied-runtime-role", "server-file-read-denied", "role-escalation-denied",
               "expired-unreclaimed-lease-cannot-complete", "stale-base-cannot-complete",
               "stale-epoch-cannot-complete", "fresh-lease-base-epoch-completes"}


def validate(document, db):
    if document["openapi"] != "3.1.0" or document["info"]["version"] != "0.1.0-draft":
        raise ValueError("draft metadata mismatch")
    operations = [(path, method, operation) for path, methods in document["paths"].items()
                  for method, operation in methods.items()]
    if len(operations) != 10 or {op["operationId"] for _, _, op in operations} != EXPECTED_OPS:
        raise ValueError("operation coverage mismatch")
    for path, method, op in operations:
        public = op["operationId"] in {"register", "login"}
        if op["security"] != ([] if public else [{"session": []}]):
            raise ValueError("session guard missing")
        headers = {p["name"] for p in op["parameters"] if p["in"] == "header" and p.get("required")}
        if method != "get" and not public and "X-CSRF-Token" not in headers:
            raise ValueError("CSRF header missing")
        if op["operationId"] == "createRun" and (method != "post" or "Idempotency-Key" not in headers):
            raise ValueError("run mutation/idempotency mismatch")
        if op["operationId"] == "streamEvents" and (method != "get" or "requestBody" in op):
            raise ValueError("stream must be read-only GET")
        names = {p["name"] for p in op["parameters"] if p["in"] == "path" and p.get("required")}
        if names != set(re.findall(r"\{(\w+)\}", path)):
            raise ValueError("path parameters mismatch")

    def refs(node):
        if isinstance(node, dict):
            if "$ref" in node:
                target = document
                for part in node["$ref"].removeprefix("#/").split("/"):
                    if part not in target:
                        raise ValueError("unresolved schema reference")
                    target = target[part]
            for value in node.values():
                refs(value)
        elif isinstance(node, list):
            for value in node:
                refs(value)
    refs(document)
    schemas = document["components"]["schemas"]
    sequence = schemas["Event"]["properties"]["sequence"]
    if sequence != {"type": "string", "pattern": "^[1-9][0-9]*$"}:
        raise ValueError("event sequence wire precision mismatch")
    expected_kinds = {"run.queued", "run.started", "text.delta", "text.snapshot", "tool.arguments.delta", "tool.started",
                      "tool.result", "check.result", "run.succeeded", "run.failed", "run.cancelled"}
    if set(schemas["Event"]["properties"]["kind"]["enum"]) != expected_kinds:
        raise ValueError("event kind coverage mismatch")
    required = {"run_id", "sequence", "schema_version", "kind", "attempt", "payload"}
    if set(schemas["Event"]["required"]) != required:
        raise ValueError("event envelope incomplete")
    clauses = schemas["Event"].get("allOf", [])
    if len(clauses) != len(expected_kinds) or {x["if"]["properties"]["kind"]["const"] for x in clauses} != expected_kinds:
        raise ValueError("event correlation coverage missing")
    for clause in clauses:
        kind = clause["if"]["properties"]["kind"]["const"]
        payload = clause["then"]["properties"]["payload"]["allOf"]
        if payload[1]["properties"]["type"] != {"const": kind}:
            raise ValueError("kind/payload correlation missing")
        if kind.startswith("run.") and kind.split(".")[1] in {"succeeded", "failed", "cancelled"}:
            terminal = payload[2]["properties"]["snapshot"]["properties"]
            if terminal["status"] != {"const": kind.split(".")[1]}:
                raise ValueError("terminal status correlation missing")
            if kind == "run.succeeded" and terminal.get("artifact_revision") != {"type": "string", "format": "uuid"}:
                raise ValueError("success artifact must be non-null")
    queued = next(x for x in clauses if x["if"]["properties"]["kind"]["const"] == "run.queued")
    if queued["then"]["properties"].get("attempt") != {"const": 0} or schemas["Event"]["properties"]["attempt"]["minimum"] != 0:
        raise ValueError("queued attempt zero missing")
    if len(db["checks"]) != len(EXPECTED_DB) or {x["name"] for x in db["checks"]} != EXPECTED_DB:
        raise ValueError("DB probe identity coverage mismatch")
    if not all(x["passed"] is True for x in db["checks"]) or db["cleanup"] is not True:
        raise ValueError("DB probe failed or not cleaned")
    return {"operations": 10, "event_kinds": 11, "db_checks": 10,
            "status": "draft structural checks only; D4 pending"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    root = parser.parse_args().root
    print(json.dumps(validate(json.loads((root / "p0-openapi.json").read_text()),
                              json.loads((root / "p0-db-results.json").read_text()))))
