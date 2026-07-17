from django.core.management.base import BaseCommand

from tuckit.core.models import ApiToken, Org, OrgMember, User
from tuckit.core.services.orgs import create_workspace
from tuckit.core.services.tokens import generate_token


def ensure_bootstrap(email: str = "local@tuckit.local", org_slug: str = "default") -> tuple[Org, str | None]:
    user, _ = User.objects.get_or_create(email=email)
    org, _ = Org.objects.get_or_create(slug=org_slug, defaults={"name": "Default"})
    OrgMember.objects.get_or_create(user=user, org=org, defaults={"role": "owner"})
    workspace = org.workspaces.first() or create_workspace(org, "Default", slug="default")

    raw = None
    if not ApiToken.objects.filter(org=workspace.org).exists():
        _, raw = generate_token(workspace, "local-cli")
    return org, raw


class Command(BaseCommand):
    help = "Create the default local user, org, workspace, area, and API token."

    def handle(self, *args, **options):
        org, raw = ensure_bootstrap()
        self.stdout.write(self.style.SUCCESS(f"Workspace ready: {org.slug}"))
        if raw:
            self.stdout.write(self.style.WARNING(f"API token (shown once): {raw}"))
        else:
            self.stdout.write("API token already exists — re-run with a fresh workspace to mint another.")
