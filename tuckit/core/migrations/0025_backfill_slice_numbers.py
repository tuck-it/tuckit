from django.db import migrations


def backfill(apps, schema_editor):
    Org = apps.get_model("core", "Org")
    Slice = apps.get_model("core", "Slice")
    for org in Org.objects.all():
        n = 0
        qs = Slice.objects.filter(area__org=org).order_by("created_at", "id")
        for n, s in enumerate(qs, start=1):
            s.number = n
            s.save(update_fields=["number"])
        org.next_slice_number = n + 1
        org.save(update_fields=["next_slice_number"])


class Migration(migrations.Migration):
    dependencies = [("core", "0024_slice_number_org_counter")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
