import pytest

from tuckit.core.services.slices import create_slice


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
