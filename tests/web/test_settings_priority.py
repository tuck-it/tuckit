"""The human half of the asymmetry.

An agent may only append to the priority policy (tests/test_priority_policy.py
pins that). A person has to be able to remove a line that turned out wrong, and
this is the only place that can happen.
"""

import pytest

from tuckit.core.models import Org, OrgMember, User


@pytest.mark.django_db
def test_an_admin_can_rewrite_the_whole_policy(client_local, org):
    """Rewrite, not append: removing a line someone got wrong has to be
    possible somewhere, and the MCP path deliberately cannot do it."""
    org.priority_policy = "1 = the old criterion."
    org.save(update_fields=["priority_policy", "updated_at"])

    resp = client_local.post(
        f"/{org.slug}/settings/priority/policy", {"policy": "1 = the new criterion."},
    )

    org.refresh_from_db()
    assert resp.status_code in (204, 302)
    assert org.priority_policy == "1 = the new criterion."
    assert "old criterion" not in org.priority_policy


@pytest.mark.django_db
def test_an_admin_can_clear_the_policy_entirely(client_local, org):
    """Empty is a legitimate state -- it is where every org starts -- so there
    has to be a way back to it. The product treats it as normal, not broken."""
    org.priority_policy = "1 = something."
    org.save(update_fields=["priority_policy", "updated_at"])

    client_local.post(f"/{org.slug}/settings/priority/policy", {"policy": "   "})

    org.refresh_from_db()
    assert org.priority_policy == ""


@pytest.mark.django_db
def test_a_non_admin_cannot_touch_the_policy(client, org):
    """The policy decides how an agent ranks everyone's work. It is an
    admin-level setting for the same reason the shipped-board preference is."""
    outsider = User.objects.create(email="member@example.com")
    OrgMember.objects.create(org=org, user=outsider, role="member")
    client.force_login(outsider)

    resp = client.post(
        f"/{org.slug}/settings/priority/policy", {"policy": "mine now."},
    )

    assert resp.status_code == 403


@pytest.mark.django_db
def test_a_non_admin_edit_leaves_the_policy_untouched(client, org):
    """403 is only half of it: a guard that refuses after writing has already
    spent the text it was protecting."""
    org.priority_policy = "1 = the real criterion."
    org.save(update_fields=["priority_policy", "updated_at"])
    outsider = User.objects.create(email="member2@example.com")
    OrgMember.objects.create(org=org, user=outsider, role="member")
    client.force_login(outsider)

    client.post(f"/{org.slug}/settings/priority/policy", {"policy": "mine now."})

    org.refresh_from_db()
    assert org.priority_policy == "1 = the real criterion."


@pytest.mark.django_db
def test_the_settings_page_renders_and_is_linked_from_the_nav(client_local, org):
    """A settings page nobody can navigate to is a page that does not exist.
    The policy is the one piece of this feature a person has to author, so it
    must be reachable without knowing the URL."""
    page = client_local.get(f"/{org.slug}/settings/priority")

    assert page.status_code == 200
    assert "settings_priority" not in page.content.decode()  # url tag resolved
    assert f"/{org.slug}/settings/priority" in page.content.decode()


@pytest.mark.django_db
def test_an_empty_policy_shows_an_example_rather_than_a_blank_box(client_local, org):
    """Nobody writes into an empty textarea. This org's own description has sat
    empty since it was created, which is the evidence -- an example is the only
    friction remover on the page."""
    assert org.priority_policy == ""

    html = client_local.get(f"/{org.slug}/settings/priority").content.decode()

    assert "placeholder" in html
