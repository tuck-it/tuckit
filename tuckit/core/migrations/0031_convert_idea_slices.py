from django.db import migrations


def forward(apps, schema_editor):
    # Import the real service (one-way, run once on a small DB). It operates on
    # current models — acceptable here because we don't replay history.
    from tuckit.core.models import Org
    from tuckit.core.services.tickets import convert_org_backlog

    for org in Org.objects.all():
        convert_org_backlog(org)


def backward(apps, schema_editor):
    raise migrations.RunPython.noop  # not reversible; conversion is one-way


class Migration(migrations.Migration):
    dependencies = [("core", "0030_ticket")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
