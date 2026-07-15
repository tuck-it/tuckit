from django.db import migrations, models


def backfill_completed(apps, schema_editor):
    Workspace = apps.get_model("core", "Workspace")
    Area = apps.get_model("core", "Area")
    Slice = apps.get_model("core", "Slice")
    Bite = apps.get_model("core", "Bite")
    ActivityEvent = apps.get_model("core", "ActivityEvent")
    for ws in Workspace.objects.all():
        if ws.onboarding_dismissed:
            ws.onboarding_completed = True
            ws.save(update_fields=["onboarding_completed"])
            continue
        has_area = Area.objects.filter(workspace=ws, is_triage=False).exists()
        has_slice = Slice.objects.filter(area__workspace=ws).exists()
        has_bite = Bite.objects.filter(slice__area__workspace=ws).exists()
        connected = ActivityEvent.objects.filter(workspace=ws, actor="agent").exists()
        if has_area and has_slice and has_bite and connected:
            ws.onboarding_completed = True
            ws.save(update_fields=["onboarding_completed"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_workspacestatsnapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="onboarding_completed",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(backfill_completed, noop),
    ]
