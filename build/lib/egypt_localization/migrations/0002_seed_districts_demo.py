"""Seed D/W/V levels beneath the governorates (demo subset: Cairo + Giza).

openIMIS attaches families to a village/ward, so Region-only seeding leaves
enrolment impossible (Scenario A precondition P2). This migration completes the
hierarchy for two governorates so the flow can run; the national dataset from
CAPMAS is a separate operational load and does not belong in a migration.

Idempotent and reversible.
"""
import json
import os

from django.db import migrations

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "districts_demo.json")


def seed(apps, schema_editor):
    Location = apps.get_model("location", "Location")
    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)

    def ensure(code, name, ltype, parent):
        obj = Location.objects.filter(code=code, validity_to__isnull=True).first()
        if obj:
            return obj
        return Location.objects.create(
            code=code, name=name, type=ltype, parent=parent, audit_user_id=-1
        )

    for d in data["districts"]:
        gov = Location.objects.filter(
            code=d["governorate"], type="R", validity_to__isnull=True
        ).first()
        if not gov:
            continue  # governorate seed absent; 0001 owns that
        district = ensure(d["code"], d["name_ar"], "D", gov)
        for w in d.get("wards", []):
            ward = ensure(w["code"], w["name_ar"], "W", district)
            for v in w.get("villages", []):
                ensure(v["code"], v["name_ar"], "V", ward)


def unseed(apps, schema_editor):
    Location = apps.get_model("location", "Location")
    Location.objects.filter(code__startswith="EG-", type__in=["D", "W", "V"]).delete()


class Migration(migrations.Migration):
    dependencies = [("egypt_localization", "0001_seed_egypt")]
    operations = [migrations.RunPython(seed, unseed)]
