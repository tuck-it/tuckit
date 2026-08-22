from django.db import migrations, models


def drop_every_cooldown_row(apps, schema_editor):
    """Existing rows predate the channel column and cannot be assigned one.

    A cooldown row is a note that a card was already drawn somewhere; guessing
    a channel for it would suppress a real unfurl in whichever channel we
    guessed. Dropping them costs at most one card drawn a second time, which
    is the harmless direction -- the failure this migration exists to end is
    the silent one.
    """
    apps.get_model("slack", "SlackUnfurl").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("slack", "0002_slackunfurl"),
    ]

    operations = [
        migrations.RunPython(drop_every_cooldown_row, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="slackunfurl",
            name="uniq_slack_unfurl_per_ref",
        ),
        migrations.AddField(
            model_name="slackunfurl",
            name="channel",
            field=models.CharField(default="", max_length=32),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name="slackunfurl",
            constraint=models.UniqueConstraint(
                fields=("install", "channel", "ref"),
                name="uniq_slack_unfurl_per_channel_ref",
            ),
        ),
    ]
