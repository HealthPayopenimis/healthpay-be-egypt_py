"""
Create the first *interactive* openIMIS user (bootstrap admin).

WHY THIS EXISTS
---------------
Django's `createsuperuser` creates only the Django-side `core_User` row with
`t_user_id` set (a TECHNICAL user). openIMIS's web UI authenticates and
authorises interactive users, which additionally require:

  * a row in legacy `tblUsers` (`InteractiveUser`) carrying the legacy
    SHA-256 + private-key password format, and
  * a role binding in `tblUserRole` (`UserRole`),
  * with `core_User.i_user_id` pointing at the InteractiveUser.

A technical-only user authenticates (`/api/core/users/current_user/` returns
200) but resolves ZERO rights, so the app renders an empty menu — a failure
that looks like a frontend defect and is not.

Note this command does NOT use `core.services.userServices
.create_or_update_interactive_user()`, because that service assumes the legacy
demo dump's Admin row (InteractiveUser id=1) already exists and creates a
`User(username="Admin", i_user_id=1)` referencing it. Our bootstrap
deliberately seeds no user rows, so that path raises
`InteractiveUser.DoesNotExist` on a clean database. This command uses core's
own model APIs instead — crucially `InteractiveUser.set_password()`, so the
legacy hash is produced by core itself and never hand-crafted. No raw SQL and
no fabricated hashes.

USAGE
-----
    # administrator (gates A1-A7)
    docker compose -f compose.healthpay.yml run --rm backend \\
        manage create_interactive_user --username hpadmin --email admin@example.org

    # least-privilege enrolment officer (gate A8 role isolation)
    docker compose -f compose.healthpay.yml run --rm backend \\
        manage create_interactive_user --username hpofficer --role-is-system 1 \\
        --last-name Officer --other-names Enrolment

Password is read from HP_USER_PASSWORD (or HP_ADMIN_PASSWORD), or prompted
interactively; it is never passed as a command-line argument (shell history /
process list exposure). Idempotent: re-running updates the role binding and
core_User link without duplicating rows.
"""
import getpass
import os

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


def apps_get_location():
    return django_apps.get_model("location", "Location")


class Command(BaseCommand):
    help = "Create an interactive (UI-capable) openIMIS user with a given role."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", default=None)
        parser.add_argument("--last-name", default="User")
        parser.add_argument("--other-names", default="HealthPay")
        parser.add_argument(
            "--language", default="ar", help="Language code (default: ar)"
        )
        parser.add_argument(
            "--districts",
            default=None,
            help=(
                "Comma-separated District (type D) location CODES defining this "
                "user's geographic scope, e.g. 'EG-01-D01'. Location pickers "
                "populate from the user's assigned districts, so an account with "
                "none sees an EMPTY region list and cannot select anywhere."
            ),
        )
        parser.add_argument(
            "--officer",
            action="store_true",
            help=(
                "Also create/link an Officer record (tblOfficer) with the same "
                "code. Required for enrolment personas: policies are attached to "
                "an Officer, and the officer picker is filtered by district."
            ),
        )
        parser.add_argument(
            "--officer-code",
            default=None,
            help=(
                "Officer code (tblOfficer.Code). PHYSICAL COLUMN IS varchar(8) even "
                "though the Django model declares max_length=50, so codes longer "
                "than 8 characters fail at the database. Defaults to --username "
                "when that fits; otherwise this argument is REQUIRED (the command "
                "will not silently truncate)."
            ),
        )
        parser.add_argument(
            "--officer-villages",
            default=None,
            help="Comma-separated Village (type V) codes for the Officer's catchment.",
        )
        parser.add_argument(
            "--role-is-system",
            type=int,
            default=64,
            help=(
                "is_system id of the role to bind. Seeded matrix (bootstrap/03_reference_data.sql):\n"
                "  1=Enrolment Officer (23 rights)   2=Manager (5)        4=Accountant (29)\n"
                "  8=Clerk (18)                     16=Medical Officer (6) 32=Scheme Administrator (52)\n"
                " 64=IMIS Administrator (27)        128=Receptionist (4)  256=Claim Administrator (11)\n"
                "512=Claim Contributor (3)      524288=HF Administrator (10)\n"
                "Default 64 = IMIS Administrator."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from core.models import InteractiveUser, Role, User, UserRole

        username = options["username"]
        password = os.environ.get("HP_USER_PASSWORD") or os.environ.get("HP_ADMIN_PASSWORD")
        if not password:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Password (again): "):
                raise CommandError("Passwords do not match.")
        if not password:
            raise CommandError(
                "No password supplied (set HP_ADMIN_PASSWORD or enter interactively)."
            )

        role = Role.objects.filter(
            is_system=options["role_is_system"], validity_to__isnull=True
        ).first()
        if not role:
            raise CommandError(
                "Role with is_system=%s not found. Was the reference-data bootstrap "
                "(bootstrap/03_reference_data.sql) applied?" % options["role_is_system"]
            )

        i_user = InteractiveUser.objects.filter(
            login_name=username, validity_to__isnull=True
        ).first()
        created = False
        if not i_user:
            i_user = InteractiveUser(
                login_name=username,
                last_name=options["last_name"],
                other_names=options["other_names"],
                language_id=options["language"],
                email=options["email"],
                is_associated=False,
            )
            created = True
        # set_password() applies core's own legacy hashing (sha256 over
        # password+private_key, uppercased) — never construct this by hand.
        i_user.set_password(password)
        i_user.save()

        if not UserRole.objects.filter(
            user=i_user, role=role, validity_to__isnull=True
        ).exists():
            UserRole.objects.create(user=i_user, role=role, audit_user_id=i_user.id)

        # --- geographic scope -------------------------------------------------
        from core.services.userServices import (
            create_or_update_user_districts, create_or_update_officer,
        )

        district_codes = [c.strip() for c in (options["districts"] or "").split(",") if c.strip()]
        if district_codes:
            Location = apps_get_location()
            districts = list(
                Location.objects.filter(
                    code__in=district_codes, type="D", validity_to__isnull=True
                )
            )
            found = {d.code for d in districts}
            unknown = set(district_codes) - found
            if unknown:
                raise CommandError(
                    "Unknown district code(s): %s. Districts must exist and be type 'D' "
                    "(seeded by egypt_localization migration 0002)." % ", ".join(sorted(unknown))
                )
            create_or_update_user_districts(i_user, [d.id for d in districts], i_user.id)

        core_user = User.objects.filter(username=username).first() or User(
            username=username
        )
        core_user.i_user = i_user
        # An interactive account must NOT also carry a technical user. core's
        # resolve_users() filters the Users admin page with Q(t_user__isnull=True),
        # so a row with both is fully entitled everywhere yet invisible on its own
        # admin page. This happens when `createsuperuser` was run for the same
        # username first (it sets t_user). Detach it; the TechnicalUser row itself
        # is left intact for any API/service client that may reference it.
        detached_t_user = None
        if core_user.t_user_id:
            detached_t_user = core_user.t_user_id
            core_user.t_user = None
        core_user.save()

        # --- optional Officer record -----------------------------------------
        officer = None
        if options["officer"]:
            if not district_codes:
                raise CommandError("--officer requires --districts (an Officer is scoped to a location).")
            officer_code = options["officer_code"] or username
            if len(officer_code) > 8:
                raise CommandError(
                    "Officer code %r is %d characters; tblOfficer.Code is varchar(8). "
                    "Pass an explicit --officer-code of at most 8 characters. "
                    "(Not truncating automatically: the code is an operational identifier.)"
                    % (officer_code, len(officer_code))
                )
            village_codes = [c.strip() for c in (options["officer_villages"] or "").split(",") if c.strip()]
            Location = apps_get_location()
            villages = list(
                Location.objects.filter(
                    code__in=village_codes, type="V", validity_to__isnull=True
                )
            ) if village_codes else []
            if village_codes and len(villages) != len(village_codes):
                raise CommandError("One or more village codes not found (must be type 'V').")
            officer, _created_officer = create_or_update_officer(
                user_id=None,
                data={
                    "username": officer_code,
                    "last_name": options["last_name"],
                    "other_names": options["other_names"],
                    "phone": None,
                    "email": options["email"],
                    "birth_date": None,
                    "address": None,
                    "works_to": None,
                    "location_id": districts[0].id,
                    "substitution_officer_id": None,
                    "phone_communication": None,
                    "village_ids": [v.id for v in villages],
                },
                audit_user_id=i_user.id,
                connected=True,
            )
            core_user.officer = officer
            core_user.save()

        rights_count = len(i_user.rights or [])
        if detached_t_user:
            self.stdout.write(
                self.style.WARNING(
                    "  detached technical user %s from '%s' (an account with both "
                    "i_user and t_user is hidden from the Users admin page)"
                    % (detached_t_user, username)
                )
            )
        scope_note = ""
        if district_codes:
            scope_note = "\n  districts: %s" % ", ".join(district_codes)
        if officer:
            scope_note += "\n  officer: %s (id=%s)" % (officer.code, officer.id)
        self.stdout.write(
            self.style.SUCCESS(
                "%s interactive user '%s' (InteractiveUser id=%s, core_User id=%s)\n"
                "  role: %s | is_imis_admin: %s | rights resolved: %s%s"
                % (
                    "Created" if created else "Updated",
                    username,
                    i_user.id,
                    core_user.id,
                    role.name,
                    i_user.is_imis_admin,
                    rights_count,
                    scope_note,
                )
            )
        )
        if rights_count == 0:
            raise CommandError(
                "User resolves zero rights — the UI menu would be empty. "
                "Check that tblRoleRight was seeded by the bootstrap."
            )
