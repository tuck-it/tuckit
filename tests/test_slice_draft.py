import pytest

from tuckit.core.services.slices import create_slice, propose_nodes, update_slice


@pytest.mark.django_db
def test_draft_defaults_to_an_empty_dict(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    s.refresh_from_db()
    assert s.draft == {}


@pytest.mark.django_db
def test_draft_round_trips_a_node_tree(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    s.draft = {"nodes": [
        {"id": "n1", "parent": None, "kind": "question", "title": "Root",
         "summary": "", "body": "**bold**", "at": 1787200000000},
        {"id": "n2", "parent": "n1", "kind": "option", "title": "A",
         "summary": "s", "body": "", "recommended": True, "at": 1787200000001},
    ]}
    s.save(update_fields=["draft"])
    s.refresh_from_db()

    assert s.draft["nodes"][0]["parent"] is None
    assert s.draft["nodes"][0]["body"] == "**bold**"
    assert s.draft["nodes"][1]["recommended"] is True


@pytest.mark.django_db
def test_writing_a_spec_retires_the_draft(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    propose_nodes(s, [{"id": "n1", "parent": None, "kind": "question", "title": "Q"}])

    update_slice(s, spec="## Decision\nWe went with A.")

    s.refresh_from_db()
    assert s.draft == {}


@pytest.mark.django_db
def test_an_empty_spec_leaves_the_draft_alone(org, area):
    """`spec=""` is 'not designed yet', which is exactly when the draft is the
    only record of the thinking. Clearing it there would delete the work."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    propose_nodes(s, [{"id": "n1", "parent": None, "kind": "question", "title": "Q"}])

    update_slice(s, spec="   ")

    s.refresh_from_db()
    assert [n["id"] for n in s.draft["nodes"]] == ["n1"]


@pytest.mark.django_db
def test_an_unrelated_update_leaves_the_draft_alone(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    propose_nodes(s, [{"id": "n1", "parent": None, "kind": "question", "title": "Q"}])

    update_slice(s, title="Canvas, renamed")

    s.refresh_from_db()
    assert [n["id"] for n in s.draft["nodes"]] == ["n1"]
