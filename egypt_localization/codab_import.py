"""Pure validation and reconciliation helpers for the Issue 37 COD-AB importer.

This module deliberately has no Django import.  The management command is the only
layer allowed to resolve the deployed LocationService and perform writes.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

SOURCE_RESOURCE_ID = "81126a96-2991-48e1-93cb-24c164a4de88"
SOURCE_SHA256 = "9d8ed34df98f328048b0c2e8be28f2fcab27484f00b3f6fd55aa8851850a0250"
CANDIDATE_SHA256 = "1cb6fb7614b63128eda12863748541385d070857eba57fce9e26118cfd7e24b8"
AUTHORIZATION_REPORT_SHA256 = "a805884b0040cbe369438ea1151ddedd2be0243bdeb0af182d0294ea18395950"
SOURCE_URL = "https://data.humdata.org/dataset/b90d81ba-7c7a-4283-9899-827480d80a79/resource/81126a96-2991-48e1-93cb-24c164a4de88/download/egy_admin_boundaries.xlsx"
SOURCE_LICENSE = "CC BY-IGO"
SOURCE_ATTRIBUTION = "CAPMAS / Government of Egypt; OCHA FIS/HDX publication; ITOS processing"
AUTHORIZATION_CONFIRMATION = "oct11-2026-existing-healthpay-qa"
AUTHORIZATION_BASELINE = "HEALTHPAY-QA-ISSUE37-CODAB-BASELINE-2026-10-07"
EXPECTED_COUNTS = {"R": 27, "D": 365, "V": 5716}
ALLOWED_TYPES = frozenset(EXPECTED_COUNTS)
OWNED_PROVENANCE_KEY = "healthpay_issue37_codab"


def _fail(message: str) -> None:
    raise ValueError(message)


def validate_apply_authorization(
    *, apply: bool, environment: str | None, configured_token: str | None,
    cli_token: str | None, baseline: str | None, database_name: str | None,
    username: str | None,
) -> None:
    """Enforce the non-user-label runtime gates without importing Django."""
    if not apply:
        return
    if environment != "qa":
        _fail("apply requires the real Django setting HEALTHPAY_DEPLOYMENT_ENV=qa")
    if username != "hpadmin":
        _fail("apply requires the authorized --username hpadmin")
    if configured_token != AUTHORIZATION_CONFIRMATION or cli_token != AUTHORIZATION_CONFIRMATION:
        _fail("wrong or missing Issue37 QA authorization marker")
    if baseline != AUTHORIZATION_BASELINE:
        _fail("wrong or missing Issue37 authorization baseline")
    if database_name != "IMIS":
        _fail("apply requires default Django database NAME IMIS")


def candidate_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_candidate(path: Path) -> list[dict[str, Any]]:
    actual = candidate_sha256(path)
    if actual != CANDIDATE_SHA256:
        _fail(f"candidate fixture SHA-256 mismatch: {actual}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"candidate fixture is not valid JSON: {exc}")
    if not isinstance(document, list):
        _fail("candidate fixture schema must be a JSON array")
    validate_candidate(document)
    return document


def validate_candidate(rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            _fail(f"candidate row {index} is not an object")
        required = {"source_sheet", "code", "name", "type", "parent_code", "source_fields"}
        missing = required.difference(row)
        if missing:
            _fail(f"candidate row {index} missing fields: {sorted(missing)}")
        code, name, kind, parent, source_fields = (
            row["code"], row["name"], row["type"], row["parent_code"], row["source_fields"]
        )
        if not isinstance(code, str) or not code.startswith("EG") or len(code) > 50:
            _fail(f"invalid candidate P-code at row {index}: {code!r}")
        if code in seen:
            _fail(f"duplicate candidate P-code: {code}")
        seen.add(code)
        if kind not in ALLOWED_TYPES:
            _fail(f"unsupported candidate type {kind!r}; W is never fabricated")
        if not isinstance(name, str) or not name or len(name) > 100:
            _fail(f"invalid candidate Arabic name for {code}")
        if kind == "R":
            if parent is not None:
                _fail(f"R row {code} must not have a parent")
        elif not isinstance(parent, str) or not parent.startswith("EG"):
            _fail(f"missing candidate parent for {code}")
        if not isinstance(source_fields, dict):
            _fail(f"source_fields for {code} must be an object")
        if source_fields.get("lang1") != "ar":
            _fail(f"Arabic source metadata missing for {code}")
        level = {"R": "1", "D": "2", "V": "3"}[kind]
        if row["source_sheet"] != f"egy_admin{level}":
            _fail(f"type {kind} row {code} has unexpected source sheet {row['source_sheet']!r}")
        if source_fields.get(f"adm{level}_pcode") != code:
            _fail(f"candidate code {code} is not the exact source P-code")
        if kind != "R" and source_fields.get(f"adm{int(level)-1}_pcode") != parent:
            _fail(f"candidate parent for {code} is not the exact source parent P-code")
        if source_fields.get(f"adm{level}_name1") != name:
            _fail(f"candidate name for {code} is not the exact Arabic source name")
        counts[kind] += 1
    if dict(counts) != EXPECTED_COUNTS:
        _fail(f"candidate counts mismatch: {dict(counts)}")
    for row in rows:
        if row["parent_code"] is not None and row["parent_code"] not in seen:
            _fail(f"candidate parent is missing: {row['parent_code']} for {row['code']}")


def _existing_value(row: Mapping[str, Any], key: str, default: Any = None) -> Any:
    value = row.get(key, default)
    if key == "parent__code" and value is None:
        value = row.get("parent_code", default)
    return value


def plan_diff(candidate: Iterable[Mapping[str, Any]], existing: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a deterministic add/skip/conflict plan from model-shaped rows.

    Existing rows are intentionally not filtered by validity: an inactive row with
    the same code is still a collision and is never silently reused or overwritten.
    """
    candidate = list(candidate)
    validate_candidate(candidate)
    by_code: dict[str, list[Mapping[str, Any]]] = {}
    for row in existing:
        code = row.get("code")
        if not isinstance(code, str):
            _fail("existing inventory contains a row without a code")
        by_code.setdefault(code, []).append(row)

    decisions: list[dict[str, Any]] = []
    counts = {outcome: {kind: 0 for kind in ("R", "D", "V")} for outcome in ("add", "skip", "conflict")}
    for row in candidate:
        code = row["code"]
        matches = by_code.get(code, [])
        if not matches:
            outcome, reason = "add", "no existing row with exact P-code"
            existing_row = None
        elif len(matches) != 1:
            outcome, reason = "conflict", "multiple existing rows share the P-code"
            existing_row = None
        else:
            prior = matches[0]
            same = (
                _existing_value(prior, "type") == row["type"]
                and _existing_value(prior, "parent__code") == row["parent_code"]
                and _existing_value(prior, "name") == row["name"]
            )
            inactive = prior.get("validity_to") is not None
            if inactive:
                outcome, reason = "conflict", "P-code collides with an inactive existing row"
            elif same:
                outcome, reason = "skip", "exact code/type/parent/name match"
            else:
                outcome, reason = "conflict", "same P-code has different type, parent or name"
            existing_row = dict(prior)
        counts[outcome][row["type"]] += 1
        decisions.append({
            "code": code, "type": row["type"], "parent_code": row["parent_code"],
            "name": row["name"], "outcome": outcome, "reason": reason,
            "existing": existing_row,
        })
    return {
        "counts": counts,
        "total": len(candidate),
        "has_conflicts": any(counts["conflict"].values()),
        "decisions": decisions,
    }


def provenance(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_dataset": "cod-ab-egy",
        "source_resource_id": SOURCE_RESOURCE_ID,
        "source_sha256": SOURCE_SHA256,
        "source_url": SOURCE_URL,
        "source_dataset_version": "HDX version 01",
        "source_license": SOURCE_LICENSE,
        "source_attribution": SOURCE_ATTRIBUTION,
        "source_sheet": row["source_sheet"],
        "source_pcode": row["code"],
        "source_parent_pcode": row["parent_code"],
        "source_name_language": "lang1=ar",
        "coverage_status": "PARTIAL" if row["type"] == "V" else "REPRESENTED",
        "source_fields": row["source_fields"],
    }
