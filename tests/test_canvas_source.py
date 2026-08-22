import pytest

from tuckit.core.services.canvas import graph_for
from tuckit.core.services.slices import create_slice


@pytest.mark.django_db
def test_graph_uses_the_decision_tree_while_the_spec_is_empty(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    s.decision_tree = {"nodes": [{"id": "n1", "parent": None, "kind": "question",
                          "title": "Root", "summary": "", "body": ""}]}
    s.save(update_fields=["decision_tree"])

    assert [n["id"] for n in graph_for(s)] == ["n1"]


@pytest.mark.django_db
def test_graph_still_shows_the_decision_tree_after_a_spec_is_written(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    s.decision_tree = {"nodes": [{"id": "n1", "parent": None, "kind": "question",
                                  "title": "Root", "summary": "", "body": ""}]}
    s.spec = "## Decided\nthe design"
    s.save(update_fields=["decision_tree", "spec"])

    titles = [n["title"] for n in graph_for(s)]
    assert titles == ["Root"]
    assert "Decided" not in titles   # the spec has its own surface; this is not it


@pytest.mark.django_db
def test_a_spec_with_no_decision_tree_draws_nothing(org, area):
    """No fallback to heading parsing. A spec's table of contents drawn as a
    tree reads as a decision tree and is not one."""
    s = create_slice(org, area=area, title="Canvas", spec="## One\n## Two\n")
    assert graph_for(s) == []


def test_the_heading_parser_is_gone():
    """Guard: it draws a table of contents in the shape of a decision record,
    which is exactly the confusion TP-238 removed. Not a harmless fallback."""
    import tuckit.core.services.canvas as canvas_module

    assert not hasattr(canvas_module, "nodes_from_spec")


@pytest.mark.django_db
def test_an_empty_slice_has_an_empty_graph(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    assert graph_for(s) == []
