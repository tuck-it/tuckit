import re

import django.core.validators
from django.db import migrations, models

# Copied from core/services/keys.py ON PURPOSE. A migration must keep working
# against the code as it was; importing the live service would silently rewrite
# history the day that service changes.
_MIN, _MAX = 2, 6


def _derive(slug):
    words = [w for w in (slug or "").split("-") if w]
    if len(words) >= 2:
        raw = "".join(w[0] for w in words[:4])
    elif words:
        # Strip a leading digit BEFORE truncating to 3 — "1abc"[:3] would keep
        # "1ab" and then lose the 'c', yielding "AB" instead of "ABC".
        raw = re.sub(r"^[^a-zA-Z]+", "", words[0])[:3]
    else:
        raw = ""
    raw = re.sub(r"[^A-Z0-9]", "", re.sub(r"^[^A-Z]+", "", raw.upper()))
    return raw if len(raw) >= _MIN else "ORG"


def _unique(base, used):
    if base not in used:
        return base
    n = 2
    while True:
        suffix = str(n)
        candidate = f"{base[: _MAX - len(suffix)]}{suffix}"
        if candidate not in used:
            return candidate
        n += 1


def backfill(apps, schema_editor):
    Org = apps.get_model("core", "Org")
    used = set()
    for org in Org.objects.order_by("pk"):
        key = _unique(_derive(org.slug), used)
        used.add(key)
        org.key = key
        org.save(update_fields=["key"])


class Migration(migrations.Migration):
    dependencies = [("core", "0040_org_key")]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="org",
            name="key",
            field=models.CharField(
                max_length=6,
                unique=True,
                validators=[
                    django.core.validators.RegexValidator(
                        "^[A-Z][A-Z0-9]{1,5}$", "invalid key"
                    )
                ],
            ),
        ),
    ]
