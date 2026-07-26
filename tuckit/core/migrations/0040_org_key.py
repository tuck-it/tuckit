from django.db import migrations, models


class Migration(migrations.Migration):
    """Add `key` WITHOUT unique — 0041 backfills, then adds the constraint.

    Adding it unique in one step would fail on any deployment with two or more
    orgs: they would all take the same empty default."""

    dependencies = [("core", "0039_alter_activityevent_verb_and_more")]

    operations = [
        migrations.AddField(
            model_name="org",
            name="key",
            field=models.CharField(default="", max_length=6),
            preserve_default=False,
        ),
    ]
