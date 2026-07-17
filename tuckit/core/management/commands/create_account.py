import getpass
import os

from django.core.management.base import BaseCommand, CommandError

from tuckit.core.services.accounts import register
from tuckit.core.services.exceptions import InvalidValue


class Command(BaseCommand):
    help = "Create a real user with an org (owner membership)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--org", required=True, help="Organization name.")
        parser.add_argument("--slug", required=True, help="Org slug.")
        parser.add_argument(
            "--password-env",
            default=None,
            help="Name of an env var holding the password (else prompt interactively).",
        )

    def handle(self, *args, **options):
        if options["password_env"]:
            password = os.environ.get(options["password_env"])
            if not password:
                raise CommandError(
                    f"Env var {options['password_env']} is empty or unset"
                )
        else:
            password = getpass.getpass("Password: ")

        try:
            user, org = register(
                email=options["email"],
                org_name=options["org"],
                slug=options["slug"],
                password=password,
            )
        except InvalidValue as exc:
            raise CommandError(str(exc))

        self.stdout.write(
            self.style.SUCCESS(f"Created user {user.email} + org {org.slug}")
        )
