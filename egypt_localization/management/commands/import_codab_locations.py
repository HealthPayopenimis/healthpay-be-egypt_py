"""Guarded, local-fixture-only Issue37 COD-AB QA location importer.

Dry-run is the default.  Apply is deliberately gated by the real QA environment,
IMIS database name, an exact owner confirmation token, an exact baseline label, and
an interactive core.User operator.  This command never imports W rows, overwrites
locations, runs migrations, changes settings, or calls an HTTP API.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from egypt_localization.codab_import import (
    AUTHORIZATION_REPORT_SHA256,
    CANDIDATE_SHA256,
    OWNED_PROVENANCE_KEY,
    plan_diff,
    load_candidate,
    provenance,
    validate_apply_authorization,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "codab-staged-candidate.json"


class Command(BaseCommand):
    help = "Dry-run or explicitly apply the pinned COD-AB R/D/V fixture to QA only."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Create missing rows; without this, only report a diff.")
        parser.add_argument("--username", default=None, help="Interactive core.User operator; required with --apply.")
        parser.add_argument("--confirm-authorization", default=None, help="Must equal the pinned Issue37 QA token.")
        parser.add_argument("--authorization-baseline", default=None, help="Must equal the pinned authorization baseline label.")
        parser.add_argument("--report", type=Path, default=Path("codab-import-report.json"), help="JSON report path.")

    def handle(self, *args, **options):
        candidate = load_candidate(FIXTURE)
        self._check_runtime(options)
        Location = self._location_model()
        self._check_json_ext_support(Location)
        existing = self._inventory(Location)
        report = self._report(candidate, existing, options, Location)
        if options["apply"] and report["diff"]["has_conflicts"]:
            report["status"] = "ABORTED_CONFLICTS"
            self._write_report(options["report"], report)
            raise CommandError("Issue37 apply aborted: conflicts exist; no rows were written")
        if options["apply"]:
            operator = self._operator(options["username"])
            self._apply(candidate, report["diff"], Location, operator)
            report["status"] = "APPLIED"
            report["database_mutation"] = any(report["diff"]["counts"]["add"].values())
        else:
            report["status"] = "DRY_RUN"
        self._write_report(options["report"], report)
        self.stdout.write(json.dumps({"status": report["status"], "counts": report["diff"]["counts"], "report": str(options["report"])}, ensure_ascii=False))

    @staticmethod
    def _check_runtime(options):
        try:
            db_name = settings.DATABASES["default"]["NAME"]
        except (AttributeError, KeyError, TypeError) as exc:
            raise CommandError("apply requires default Django database NAME IMIS") from exc
        try:
            validate_apply_authorization(
                apply=options["apply"],
                environment=getattr(settings, "HEALTHPAY_DEPLOYMENT_ENV", None),
                configured_token=getattr(settings, "HEALTHPAY_QA_AUTHORIZATION", None),
                cli_token=options["confirm_authorization"],
                baseline=options["authorization_baseline"],
                database_name=db_name,
                username=options["username"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

    @staticmethod
    def _location_model():
        from django.apps import apps
        try:
            return apps.get_model("location", "Location")
        except LookupError as exc:
            raise CommandError("deployed location.Location model is unavailable") from exc

    @staticmethod
    def _check_json_ext_support(Location):
        try:
            Location._meta.get_field("json_ext")
        except Exception as exc:
            raise CommandError("Location.json_ext is required to preserve source provenance; no schema change is performed") from exc

    @staticmethod
    def _inventory(Location):
        # Deliberately includes inactive/historical rows: every code collision is reported.
        fields = ("code", "name", "type", "validity_to", "parent__code")
        manager = getattr(Location, "_base_manager", Location.objects)
        return list(manager.all().values(*fields))

    @staticmethod
    def _operator(username):
        from core.models import User
        user = User.objects.filter(username=username).first()
        if not user:
            raise CommandError("authorized core.User hpadmin was not found")
        if not getattr(user, "i_user_id", None):
            raise CommandError("operator must be an interactive core.User profile")
        if not getattr(user, "is_active", True):
            raise CommandError("operator core.User profile is inactive")
        if not getattr(user, "is_imis_admin", False):
            raise CommandError("operator core.User profile is not an IMIS Administrator")
        return user

    @staticmethod
    def _report(candidate, existing, options, Location):
        diff = plan_diff(candidate, existing)
        return {
            "status": "PLANNED",
            "operation": "issue37-codab-qa-import",
            "environment": getattr(settings, "HEALTHPAY_DEPLOYMENT_ENV", None),
            "database_name": settings.DATABASES.get("default", {}).get("NAME"),
            "fixture": str(FIXTURE),
            "candidate_sha256": CANDIDATE_SHA256,
            "authorization_report_sha256": AUTHORIZATION_REPORT_SHA256,
            "source_resource_id": "81126a96-2991-48e1-93cb-24c164a4de88",
            "source_sha256": "9d8ed34df98f328048b0c2e8be28f2fcab27484f00b3f6fd55aa8851850a0250",
            "mapping": "ADM1→R, ADM2→D, ADM3→V; exact P-codes unchanged; no W rows",
            "json_ext_provenance_key": OWNED_PROVENANCE_KEY,
            "diff": diff,
            "database_mutation": False,
            "model": f"{Location._meta.app_label}.{Location.__name__}",
        }

    @staticmethod
    def _apply(candidate, diff, Location, operator):
        from location.services import LocationService
        by_code = {row["code"]: row for row in candidate}
        with transaction.atomic():
            service = LocationService(operator)
            for decision in diff["decisions"]:
                if decision["outcome"] != "add":
                    continue
                row = by_code[decision["code"]]
                parent = None
                if row["parent_code"] is not None:
                    manager = getattr(Location, "_base_manager", Location.objects)
                    parent = manager.filter(code=row["parent_code"]).first()
                    if parent is None:
                        raise CommandError(f"parent {row['parent_code']} missing for {row['code']}")
                # Recheck immediately before the supported service call; never update an existing row.
                manager = getattr(Location, "_base_manager", Location.objects)
                if manager.filter(code=row["code"]).exists():
                    raise CommandError(f"concurrent code collision for {row['code']}; transaction rolled back")
                data = {
                    "code": row["code"], "name": row["name"], "type": row["type"],
                    "json_ext": {OWNED_PROVENANCE_KEY: provenance(row)},
                    "validity_to": None, "audit_user_id": getattr(operator, "id_for_audit", operator.id),
                }
                if parent is not None:
                    data["parent_uuid"] = str(parent.uuid)
                # This is the sole write path.  No model .create(), save(), or raw SQL.
                service.update_or_create(data)

    @staticmethod
    def _write_report(path: Path, report: dict[str, Any]):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
