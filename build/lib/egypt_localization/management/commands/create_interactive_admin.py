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
    docker compose -f compose.healthpay.yml run --rm backend \\
        manage create_interactive_admin --username hpadmin --email admin@example.org

Password is read from the HP_ADMIN_PASSWORD environment variable, or prompted
interactively; it is never passed as a command-line argument (shell history /
process list exposure). Idempotent: re-running updates the role binding and
core_User link without duplicating rows.
"""
import getpass
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Create the first interactive (UI-capable) openIMIS admin user."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", default=None)
        parser.add_argument("--last-name", default="Admin")
        parser.add_argument("--other-names", default="HealthPay")
        parser.add_argument(
            "--language", default="ar", help="Language code (default: ar)"
        )
        parser.add_argument(
            "--role-is-system",
            type=int,
            default=64,
            help="is_system id of the role to bind (default 64 = IMIS Administrator)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from core.models import InteractiveUser, Role, User, UserRole

        username = options["username"]
        password = os.environ.get("HP_ADMIN_PASSWORD")
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

        core_user = User.objects.filter(username=username).first() or User(
            username=username
        )
        core_user.i_user = i_user
        core_user.save()

        rights_count = len(i_user.rights or [])
        self.stdout.write(
            self.style.SUCCESS(
                "%s interactive user '%s' (InteractiveUser id=%s, core_User id=%s)\n"
                "  role: %s | is_imis_admin: %s | rights resolved: %s"
                % (
                    "Created" if created else "Updated",
                    username,
                    i_user.id,
                    core_user.id,
                    role.name,
                    i_user.is_imis_admin,
                    rights_count,
                )
            )
        )
        if rights_count == 0:
            raise CommandError(
                "User resolves zero rights — the UI menu would be empty. "
                "Check that tblRoleRight was seeded by the bootstrap."
            )
