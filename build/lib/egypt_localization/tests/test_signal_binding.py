"""Guard against the silent-no-op class: a bound signal whose referent is dead.

The first implementation used @receiver on a nested function (weak=True), so the
handler could be garbage-collected as soon as the binding function returned —
registered by dispatch_uid, but not live. Whether it survived depended on
refcount/GC timing, so it appeared to work in one environment and silently did
nothing in another.
"""
import datetime
import gc

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction


def test_handler_survives_garbage_collection():
    from insuree.models import Insuree
    from egypt_localization.signals import _handler_is_live

    gc.collect()
    gc.collect()
    assert _handler_is_live(Insuree), "National ID handler was collected — enforcement is silently off"


def test_binding_is_not_weak():
    import weakref
    from django.db.models.signals import pre_save
    from egypt_localization.signals import DISPATCH_UID

    entries = [ref for uid, ref in pre_save.receivers
               if isinstance(uid, tuple) and uid[0] == DISPATCH_UID]
    assert entries, "handler not registered at all"
    for ref in entries:
        assert not isinstance(ref, weakref.ref), "handler bound weakly; it can be collected"


@pytest.mark.django_db
@pytest.mark.parametrize("chf_id,dob,should_reject", [
    ("29001011234567", datetime.date(1990, 1, 1), False),
    ("1234567", None, True),
    ("290010112345678", None, True),
    ("19001011234567", None, True),
    ("29013991234567", None, True),
    ("29001019934567", None, True),
    ("29001011234567", datetime.date(1985, 5, 5), True),
])
def test_enforcement_matrix(chf_id, dob, should_reject):
    from insuree.models import Insuree

    def _save():
        with transaction.atomic():
            Insuree(chf_id=chf_id, last_name="X", other_names="Y",
                    dob=dob or datetime.date(1990, 1, 1), audit_user_id=1).save()
            transaction.set_rollback(True)

    if should_reject:
        with pytest.raises(ValidationError):
            _save()
    else:
        _save()
