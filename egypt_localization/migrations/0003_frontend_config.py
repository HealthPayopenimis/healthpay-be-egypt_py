"""Seed the frontend module configuration the insuree form reads.

The React app loads `{ moduleConfigurations { module, config } }` over GraphQL
at boot and `ModulesManager.getConf("fe-insuree", "insureeForm.chfIdMaxLength")`
reads from THAT — not from the assembly's openimis.json. Setting the key in the
assembly file is a silent no-op, which is why the National ID field kept
upstream's maxLength=12 and truncated 13/14-digit input before validation could
see it.

Rows must have layer="fe" and is_exposed=True to reach an unauthenticated boot.
Idempotent and reversible.
"""
import json

from django.db import migrations

FE_CONFIGS = {
    "fe-insuree": {
        # Egyptian National ID is exactly 14 digits (upstream default is 12).
        "insureeForm.chfIdMaxLength": 14,
    },
}


def seed(apps, schema_editor):
    ModuleConfiguration = apps.get_model("core", "ModuleConfiguration")
    for module, cfg in FE_CONFIGS.items():
        existing = ModuleConfiguration.objects.filter(module=module, layer="fe").first()
        if existing:
            merged = {}
            try:
                merged = json.loads(existing.config or "{}")
            except ValueError:
                merged = {}
            merged.update(cfg)
            existing.config = json.dumps(merged)
            existing.is_exposed = True
            existing.save()
        else:
            ModuleConfiguration.objects.create(
                module=module,
                layer="fe",
                version="1",
                config=json.dumps(cfg),
                is_exposed=True,
            )


def unseed(apps, schema_editor):
    ModuleConfiguration = apps.get_model("core", "ModuleConfiguration")
    ModuleConfiguration.objects.filter(module__in=FE_CONFIGS.keys(), layer="fe").delete()


class Migration(migrations.Migration):
    dependencies = [("egypt_localization", "0002_seed_districts_demo")]
    operations = [migrations.RunPython(seed, unseed)]
