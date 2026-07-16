from django.db import migrations


def forward(apps, schema_editor):
    Slice = apps.get_model("core", "Slice")
    Plan = apps.get_model("core", "Plan")
    Bite = apps.get_model("core", "Bite")
    for s in Slice.objects.all():
        bites = list(Bite.objects.filter(plan__isnull=True, slice=s))
        if not bites:
            continue
        plan = Plan.objects.filter(slice=s).first() or Plan.objects.create(
            slice=s, title="Plan", source="human",
        )
        Bite.objects.filter(id__in=[b.id for b in bites]).update(plan=plan)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_bite_plan"),
    ]

    operations = [
        migrations.RunPython(forward, noop),
    ]
