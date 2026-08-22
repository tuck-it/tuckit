from django.db import migrations


class Migration(migrations.Migration):
    """`draft` meant "a rough version of the spec", which is what made deleting
    it on a spec write look correct. The field holds the decision record: what
    was considered and what won. Renaming it is the same fix as TP-238's
    behaviour change, written into the schema."""

    dependencies = [("core", "0057_canvas_watch_question")]

    operations = [
        migrations.RenameField(
            model_name="slice", old_name="draft", new_name="decision_tree",
        ),
    ]
