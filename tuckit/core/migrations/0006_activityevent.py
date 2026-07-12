import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_rename_area_is_inbox_is_triage"),
    ]

    operations = [
        migrations.CreateModel(
            name="ActivityEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("actor", models.CharField(choices=[("human", "Human"), ("agent", "Agent")], max_length=10)),
                ("verb", models.CharField(choices=[("created", "created"), ("status_changed", "status changed"), ("triaged", "triaged"), ("moved", "moved"), ("shipped", "shipped"), ("dropped", "dropped")], max_length=20)),
                ("target_type", models.CharField(choices=[("slice", "Slice"), ("bite", "Bite"), ("area", "Area")], max_length=10)),
                ("target_id", models.IntegerField()),
                ("target_label", models.CharField(max_length=300)),
                ("from_value", models.CharField(blank=True, default="", max_length=50)),
                ("to_value", models.CharField(blank=True, default="", max_length=50)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="activity", to="core.workspace")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="activityevent",
            index=models.Index(fields=["workspace", "-created_at"], name="core_activi_workspa_ac91de_idx"),
        ),
    ]
