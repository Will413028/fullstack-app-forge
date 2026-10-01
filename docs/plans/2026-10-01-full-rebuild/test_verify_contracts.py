"""Negative checks prevent a structurally unsafe draft from passing the gate."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("contract_gate", ROOT / "verify_contracts.py")
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class ContractGateTests(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads((ROOT / "p0-openapi.json").read_text())
        self.db = json.loads((ROOT / "p0-db-results.json").read_text())

    def test_baseline(self):
        self.assertEqual(GATE.validate(self.doc, self.db)["operations"], 10)

    def test_missing_owner_session_rejected(self):
        self.doc["paths"]["/v1/apps/{app_id}/runs/{run_id}/events"]["get"]["security"] = []
        with self.assertRaisesRegex(ValueError, "session"):
            GATE.validate(self.doc, self.db)

    def test_create_run_as_get_rejected(self):
        paths = self.doc["paths"]["/v1/apps/{app_id}/runs"]
        paths["get"] = paths.pop("post")
        with self.assertRaisesRegex(ValueError, "idempotency"):
            GATE.validate(self.doc, self.db)

    def test_missing_csrf_rejected(self):
        op = self.doc["paths"]["/v1/apps/{app_id}/runs"]["post"]
        op["parameters"] = [x for x in op["parameters"] if x["name"] != "X-CSRF-Token"]
        with self.assertRaisesRegex(ValueError, "CSRF"):
            GATE.validate(self.doc, self.db)

    def test_broken_schema_ref_rejected(self):
        self.doc["components"]["schemas"]["Event"]["properties"]["payload"]["$ref"] = "#/components/schemas/Missing"
        with self.assertRaisesRegex(ValueError, "reference"):
            GATE.validate(self.doc, self.db)

    def test_number_sequence_rejected(self):
        self.doc["components"]["schemas"]["Event"]["properties"]["sequence"] = {"type": "integer"}
        with self.assertRaisesRegex(ValueError, "precision"):
            GATE.validate(self.doc, self.db)

    def test_duplicate_db_check_rejected(self):
        self.db["checks"][0] = copy.deepcopy(self.db["checks"][1])
        with self.assertRaisesRegex(ValueError, "identity"):
            GATE.validate(self.doc, self.db)

    def test_missing_event_correlations_rejected(self):
        self.doc["components"]["schemas"]["Event"].pop("allOf")
        with self.assertRaisesRegex(ValueError, "correlation"):
            GATE.validate(self.doc, self.db)

    def test_nullable_success_artifact_rejected(self):
        clauses = self.doc["components"]["schemas"]["Event"]["allOf"]
        clause = next(x for x in clauses if x["if"]["properties"]["kind"]["const"] == "run.succeeded")
        clause["then"]["properties"]["payload"]["allOf"][2]["properties"]["snapshot"]["properties"]["artifact_revision"] = {"type": "null"}
        with self.assertRaisesRegex(ValueError, "non-null"):
            GATE.validate(self.doc, self.db)


if __name__ == "__main__":
    unittest.main()
