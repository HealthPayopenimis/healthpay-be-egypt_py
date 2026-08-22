"""
Enforce Egyptian identifier rules on every write path.

openIMIS's assembly probes each configured module for a `signals` submodule at
startup (see the `signal_binding` app), so this binds validation without forking
`be-insuree` — a Tier B change rather than Tier C.

Scope note: this applies to the UI, GraphQL, FHIR and bulk-import paths alike,
because it hooks the model's pre_save. A form-level or client-side check would
leave the API unprotected while making browser tests pass, which is the wrong
kind of green.

Toggle: `egypt_localization` module config key `enforce_national_id`
(default True). Set False for tenants not using National ID as the insuree
identifier.
"""
import logging

from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def _enabled():
    from egypt_localization.apps import EgyptLocalizationConfig
    return getattr(EgyptLocalizationConfig, "enforce_national_id", True)


def bind_signals():
    """Called from apps.ready(); tolerant if be-insuree is not installed."""
    try:
        from insuree.models import Insuree
    except ImportError:  # pragma: no cover - module not in this assembly slice
        logger.info("egypt_localization: insuree module absent, National ID enforcement not bound")
        return

    @receiver(pre_save, sender=Insuree, dispatch_uid="egypt_localization.validate_chf_id")
    def _validate_insuree_national_id(sender, instance, **kwargs):
        if not _enabled():
            return
        value = getattr(instance, "chf_id", None)
        if not value:
            return  # presence/uniqueness is core's concern, not ours
        from egypt_localization.validators import parse_national_id
        info = parse_national_id(value)  # raises ValidationError on bad structure

        # Cross-field consistency: the ID encodes DOB and gender.
        dob = getattr(instance, "dob", None)
        if dob and dob != info["birth_date"]:
            raise ValidationError(
                {"dob": "تاريخ الميلاد لا يطابق الرقم القومي المُدخل."}
            )
        gender_id = getattr(instance, "gender_id", None)
        if gender_id and str(gender_id).upper() in ("M", "F") and str(gender_id).upper() != info["gender"]:
            raise ValidationError(
                {"gender": "النوع لا يطابق الرقم القومي المُدخل."}
            )

    logger.info("egypt_localization: National ID enforcement bound to Insuree.pre_save")
