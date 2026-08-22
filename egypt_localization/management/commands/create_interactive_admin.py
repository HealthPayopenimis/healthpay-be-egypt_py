"""Deprecated alias for `create_interactive_user` (kept so earlier runbook steps
still work). Defaults are identical: role is_system=64 (IMIS Administrator)."""
from egypt_localization.management.commands.create_interactive_user import Command as _Command


class Command(_Command):
    help = "DEPRECATED alias of create_interactive_user (defaults to IMIS Administrator)."
