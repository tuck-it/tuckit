import re

from django.db import migrations

# ActivityEvent.to_value is the ONLY place a ref string is persisted — written
# by promote_ticket/absorb_ticket. Everything else derives its ref at read time
# from org + number, so this is the whole of the data migration.


def rewrite(apps, schema_editor):
    Org = apps.get_model("core", "Org")
    ActivityEvent = apps.get_model("core", "ActivityEvent")
    for org in Org.objects.all():
        pattern = re.compile(rf"^{re.escape(org.slug)}-(\d+)$")
        for ev in ActivityEvent.objects.filter(org=org).exclude(to_value=""):
            m = pattern.match(ev.to_value)
            if m:
                ev.to_value = f"{org.key}-{m.group(1)}"
                ev.save(update_fields=["to_value"])


class Migration(migrations.Migration):
    dependencies = [("core", "0041_backfill_org_key")]

    operations = [migrations.RunPython(rewrite, migrations.RunPython.noop)]
