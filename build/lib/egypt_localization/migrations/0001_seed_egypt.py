import json
import os
from django.db import migrations

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "governorates.json")


def seed_language_ar(apps, schema_editor):
    """Register Arabic in the core Language table.

    NOTE: no raw RTL-flag UPDATE here. The PostgreSQL port of tblLanguages has
    no LanguageRTL column (MSSQL-era), and a failed statement aborts the whole
    migration transaction on PostgreSQL even when caught. RTL direction is
    driven by the frontend locale config ('ar' entry in openimis.json).
    """
    Language = apps.get_model("core", "Language")
    if not Language.objects.filter(code="ar").exists():
        Language.objects.create(code="ar", name="العربية", sort_order=1)


def seed_governorates(apps, schema_editor):
    Location = apps.get_model("location", "Location")
    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    for g in data["governorates"]:
        if not Location.objects.filter(code=g["code"], type="R", validity_to__isnull=True).exists():
            Location.objects.create(
                code=g["code"],
                name=g["name_ar"],  # Arabic-first display
                type="R",
                audit_user_id=-1,
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("location", "0001_initial"),
    ]
    operations = [
        migrations.RunPython(seed_language_ar, noop),
        migrations.RunPython(seed_governorates, noop),
    ]
