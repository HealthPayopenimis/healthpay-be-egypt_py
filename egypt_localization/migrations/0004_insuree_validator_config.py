"""Activate the Egyptian National ID validator and fix the truncation gap.

TWO corrections to migration 0003:

1. BACKEND CONFIG (the reason validation never activated). InsureeConfig loads
   from `ModuleConfiguration.get_or_default("insuree", DEFAULT_CFG)` with
   layer="be" — NOT from the backend assembly's openimis.json. 0003 seeded only
   the layer="fe" row, so `insuree_number_validator` stayed None and every value
   returned isValid: true. This seeds/merges module="insuree", layer="be".

   Note is_exposed stays FALSE for the be row: it is backend configuration and
   must not be served to unauthenticated clients.

2. FIELD LENGTH vs NEGATIVE TESTING. HTML maxlength truncates silently, so with
   chfIdMaxLength=14 a 15-digit entry became a VALID 14-digit ID before the
   resolver ever saw it — a wrong-length value would be silently "corrected"
   into a passing one, for operators as well as tests. The field therefore
   allows 15 characters so the server-side rule can reject over-length input
   explicitly, while the backend bounds stay exactly 14. Silent correction of
   an identifier is worse than a visible rejection.
"""
import json

from django.db import migrations

BE_INSUREE_CFG = {
    "insuree_number_validator": (
        "egypt_localization.validators.validate_egyptian_national_id_for_insuree"
    ),
    "insuree_number_max_length": 14,
    "insuree_number_min_length": 14,
}

FE_INSUREE_CFG = {
    # One character of headroom so over-length input reaches the validator
    # instead of being silently truncated to a valid 14-digit ID.
    "insureeForm.chfIdMaxLength": 15,
}


def _upsert(ModuleConfiguration, module, layer, cfg, exposed):
    row = ModuleConfiguration.objects.filter(module=module, layer=layer).first()
    if row:
        try:
            merged = json.loads(row.config or "{}")
        except ValueError:
            merged = {}
        merged.update(cfg)
        row.config = json.dumps(merged)
        row.is_exposed = exposed
        row.save()
    else:
        ModuleConfiguration.objects.create(
            module=module, layer=layer, version="1",
            config=json.dumps(cfg), is_exposed=exposed,
        )


def seed(apps, schema_editor):
    ModuleConfiguration = apps.get_model("core", "ModuleConfiguration")
    _upsert(ModuleConfiguration, "insuree", "be", BE_INSUREE_CFG, exposed=False)
    _upsert(ModuleConfiguration, "fe-insuree", "fe", FE_INSUREE_CFG, exposed=True)


def unseed(apps, schema_editor):
    ModuleConfiguration = apps.get_model("core", "ModuleConfiguration")
    row = ModuleConfiguration.objects.filter(module="insuree", layer="be").first()
    if row:
        try:
            cfg = json.loads(row.config or "{}")
        except ValueError:
            cfg = {}
        for k in BE_INSUREE_CFG:
            cfg.pop(k, None)
        row.config = json.dumps(cfg)
        row.save()
    _upsert(ModuleConfiguration, "fe-insuree", "fe",
            {"insureeForm.chfIdMaxLength": 14}, exposed=True)


class Migration(migrations.Migration):
    dependencies = [("egypt_localization", "0003_frontend_config")]
    operations = [migrations.RunPython(seed, unseed)]
