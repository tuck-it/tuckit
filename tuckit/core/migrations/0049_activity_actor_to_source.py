from django.db import migrations


class Migration(migrations.Migration):
    """Rename ActivityEvent.actor to source.

    Hand-written rather than generated: makemigrations cannot tell a rename
    from a drop-and-add without being asked interactively, and in a
    non-interactive run it emits RemoveField + AddField — which silently
    discards every existing row's value. RenameField preserves the column.

    Migrations 0006 and 0012 still say `actor` and must keep saying it: they
    describe the schema as it stood then, and this operation is what carries
    the name forward from there.
    """

    dependencies = [
        ("core", "0048_activity_member"),
    ]

    operations = [
        migrations.RenameField(
            model_name="activityevent",
            old_name="actor",
            new_name="source",
        ),
    ]
