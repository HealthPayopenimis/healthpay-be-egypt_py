import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from egypt_localization.codab_import import (
    CANDIDATE_SHA256,
    EXPECTED_COUNTS,
    OWNED_PROVENANCE_KEY,
    load_candidate,
    plan_diff,
    validate_apply_authorization,
    validate_candidate,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "codab-staged-candidate.json"


class CodabImportPureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidate = load_candidate(FIXTURE)

    def test_pinned_fixture_counts_and_exact_pcodes(self):
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), CANDIDATE_SHA256)
        self.assertEqual({kind: sum(row["type"] == kind for row in self.candidate) for kind in "RDV"}, EXPECTED_COUNTS)
        self.assertNotIn("W", {row["type"] for row in self.candidate})
        self.assertTrue(all(row["source_fields"]["lang1"] == "ar" for row in self.candidate))
        self.assertTrue(all(row["source_fields"].get({"R": "adm1", "D": "adm2", "V": "adm3"}[row["type"]] + "_pcode") == row["code"] for row in self.candidate))

    def test_invalid_fixture_hash_is_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json") as stream:
            stream.write("[]")
            stream.flush()
            with self.assertRaisesRegex(ValueError, "fixture SHA-256 mismatch"):
                load_candidate(Path(stream.name))

    def test_missing_parent_and_invented_w_are_rejected(self):
        bad = json.loads(json.dumps(self.candidate))
        bad[27]["parent_code"] = "EG-NOT-SOURCE"
        with self.assertRaisesRegex(ValueError, "candidate parent .* exact source"):
            validate_candidate(bad)
        bad = json.loads(json.dumps(self.candidate))
        bad[0]["type"] = "W"
        with self.assertRaisesRegex(ValueError, "unsupported candidate type"):
            validate_candidate(bad)

    def test_empty_target_is_all_adds_and_compatible_target_is_all_skips(self):
        empty = plan_diff(self.candidate, [])
        self.assertFalse(empty["has_conflicts"])
        self.assertEqual(empty["counts"]["add"], EXPECTED_COUNTS)
        existing = [
            {"code": row["code"], "type": row["type"], "parent__code": row["parent_code"], "name": row["name"], "validity_to": None}
            for row in self.candidate
        ]
        repeat = plan_diff(self.candidate, existing)
        self.assertEqual(repeat["counts"]["skip"], EXPECTED_COUNTS)
        self.assertFalse(repeat["has_conflicts"])

    def test_conflicts_include_inactive_rows_and_abort_is_plannable(self):
        first = self.candidate[0]
        existing = [{"code": first["code"], "type": first["type"], "parent__code": None, "name": first["name"], "validity_to": "2026-01-01"}]
        result = plan_diff(self.candidate, existing)
        self.assertEqual(result["counts"]["conflict"]["R"], 1)
        self.assertTrue(result["has_conflicts"])
        self.assertIn("inactive", result["decisions"][0]["reason"])

    def test_provenance_is_owned_and_retains_all_source_fields(self):
        from egypt_localization.codab_import import provenance
        record = provenance(self.candidate[0])
        self.assertIn("source_fields", record)
        self.assertEqual(record["source_fields"], self.candidate[0]["source_fields"])
        self.assertEqual(OWNED_PROVENANCE_KEY, "healthpay_issue37_codab")

    def test_apply_requires_real_qa_settings_and_pinned_marker(self):
        kwargs = dict(
            apply=True,
            environment="qa",
            configured_token="oct11-2026-existing-healthpay-qa",
            cli_token="oct11-2026-existing-healthpay-qa",
            baseline="HEALTHPAY-QA-ISSUE37-CODAB-BASELINE-2026-10-07",
            database_name="IMIS",
            username="hpadmin",
        )
        validate_apply_authorization(**kwargs)
        for field, value in (("environment", "production"), ("database_name", "IMIS_rehearsal"), ("cli_token", "wrong"), ("username", "admin")):
            bad = dict(kwargs, **{field: value})
            with self.assertRaises(ValueError):
                validate_apply_authorization(**bad)
        validate_apply_authorization(**dict(kwargs, apply=False, environment="production", database_name=""))


if __name__ == "__main__":
    unittest.main()
