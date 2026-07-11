from django.db import migrations


def _unique_org_slug(Org, base):
    slug = (base or "org")[:100]
    candidate = slug
    i = 2
    while Org.objects.filter(slug=candidate).exists():
        suffix = f"-{i}"
        candidate = slug[: 100 - len(suffix)] + suffix
        i += 1
    return candidate


def backfill(apps, schema_editor):
    Workspace = apps.get_model("core", "Workspace")
    Org = apps.get_model("core", "Org")
    OrgMember = apps.get_model("core", "OrgMember")
    Membership = apps.get_model("core", "Membership")

    for ws in Workspace.objects.filter(org__isnull=True):
        org = Org.objects.create(name=ws.name, slug=_unique_org_slug(Org, ws.slug))
        ws.org = org
        ws.save(update_fields=["org"])

    for m in Membership.objects.select_related("workspace__org").all():
        org = m.workspace.org
        if org is None:
            continue
        OrgMember.objects.get_or_create(
            user_id=m.user_id, org=org, defaults={"role": m.role}
        )


def noop(apps, schema_editor):
    # Forward-only: reversing would drop backfilled orgs; leave as no-op.
    pass


class Migration(migrations.Migration):
    dependencies = [("core", "0002_org_alter_workspace_slug_invitation_workspace_org_and_more")]
    operations = [migrations.RunPython(backfill, noop)]
