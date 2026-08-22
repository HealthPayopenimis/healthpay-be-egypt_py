"""
Enforce Egyptian identifier rules on every write path.

openIMIS's assembly probes each configured module for a `signals` submodule at
startup (the `signal_binding` app), so this binds validation without forking
`be-insuree` — Tier B rather than Tier C.

Scope: hooks the model's pre_save, so it applies to UI, GraphQL, FHIR and bulk
import alike. A form-level or client-side check would leave the API unprotected
while making browser tests pass.

IMPLEMENTATION NOTE — why this is not written with @receiver on a nested
function. The first version defined the handler inside a bind function and used
the @receiver decorator, which calls Signal.connect(weak=True). The only strong
reference to a nested function is the enclosing frame, so once the bind function
returns the referent can be collected: the dispatch_uid entry survives (so it
LOOKS registered and the startup log line prints) while nothing is enforced.
Whether it survives depends on refcount/GC timing, so it was observed live in
one environment and dead in another — a silent, environment-dependent no-op.

Two defences here:
  1. the handler is at MODULE scope and connected with weak=False, so the
     module and the signal both hold strong references;
  2. bind_signals() then ASSERTS the handler is actually in
     pre_save._live_receivers(Insuree) and raises otherwise, turning a silent
     absence into a startup failure.
"""
import logging

from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save

logger = logging.getLogger(__name__)

DISPATCH_UID = "egypt_localization.validate_chf_id"


def _enforcement_enabled():
    from egypt_localization.apps import EgyptLocalizationConfig
    return getattr(EgyptLocalizationConfig, "enforce_national_id", True)


def validate_insuree_national_id(sender, instance, **kwargs):
    """Module-scope pre_save handler — see IMPLEMENTATION NOTE above."""
    if not _enforcement_enabled():
        return
    value = getattr(instance, "chf_id", None)
    if not value:
        return  # presence/uniqueness is core's concern, not ours

    from egypt_localization.validators import parse_national_id

    info = parse_national_id(value)  # raises ValidationError on bad structure

    dob = getattr(instance, "dob", None)
    if dob and dob != info["birth_date"]:
        raise ValidationError({"dob": "تاريخ الميلاد لا يطابق الرقم القومي المُدخل."})

    gender_id = getattr(instance, "gender_id", None)
    if gender_id and str(gender_id).upper() in ("M", "F"):
        if str(gender_id).upper() != info["gender"]:
            raise ValidationError({"gender": "النوع لا يطابق الرقم القومي المُدخل."})


def _handler_is_live(model):
    live = pre_save._live_receivers(model)
    if isinstance(live, tuple):  # Django >= 5 returns (sync, async)
        candidates = [r for group in live if group for r in group]
    else:
        candidates = list(live or [])
    return any(r is validate_insuree_national_id for r in candidates)


def bind_signals():
    """Bind and then PROVE the binding is live. Raises if it is not."""
    try:
        from insuree.models import Insuree
    except ImportError:
        logger.info(
            "egypt_localization: insuree module not installed; "
            "National ID enforcement not bound"
        )
        return

    pre_save.connect(
        validate_insuree_national_id,
        sender=Insuree,
        dispatch_uid=DISPATCH_UID,
        weak=False,  # explicit: a weak ref here is collectable and silently no-ops
    )

    if not _handler_is_live(Insuree):
        raise RuntimeError(
            "egypt_localization: National ID validator failed to bind to "
            "Insuree.pre_save — refusing to start with identifier validation "
            "silently disabled."
        )
    logger.info(
        "egypt_localization: National ID enforcement bound and verified live "
        "on Insuree.pre_save"
    )
