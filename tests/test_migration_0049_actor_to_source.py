"""0049 — ActivityEvent.actor becomes source.

Worth a test even though a rename looks trivial. The suite builds every test
database from empty, so it would stay green against a migration that dropped
the old column and added a new empty one — which is exactly what
makemigrations emits for a rename when it cannot ask interactively. The bug
would only surface in production, on rows nobody can reconstruct, and the
whole point of this column is that it records history.

So: write rows at 0048 under the old name, migrate, and assert the VALUES came
through — not merely that a column called source exists.
"""

import pytest

from tests.migration_utils import at, forward, leave_migrated

BEFORE = ("core", "0048_activity_member")
AFTER = ("core", "0049_activity_actor_to_source")


@pytest.mark.django_db(transaction=True)
def test_existing_values_survive_the_rename():
    old = at(BEFORE)
    Org = old.get_model("core", "Org")
    ActivityEvent = old.get_model("core", "ActivityEvent")

    org = Org.objects.create(name="Acme", slug="acme", key="ACME")
    ActivityEvent.objects.create(
        org=org, actor="agent", verb="created", target_type="slice",
        target_id=1, target_label="By an agent",
    )
    ActivityEvent.objects.create(
        org=org, actor="human", verb="shipped", target_type="slice",
        target_id=2, target_label="By a human",
    )

    new = forward(AFTER)
    ActivityEvent = new.get_model("core", "ActivityEvent")

    # A RemoveField+AddField pair would leave these NULL or blank.
    rows = {e.target_label: e.source for e in ActivityEvent.objects.all()}
    assert rows == {"By an agent": "agent", "By a human": "human"}

    # Both names existing would mean the data was copied rather than renamed,
    # and the two would drift the first time anything wrote to one of them.
    fields = {f.name for f in ActivityEvent._meta.get_fields()}
    assert "source" in fields
    assert "actor" not in fields

    leave_migrated()
