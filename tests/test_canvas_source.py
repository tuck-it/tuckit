import pytest

from tuckit.core.services.canvas import graph_for, nodes_from_spec
from tuckit.core.services.slices import create_slice


def test_headings_become_a_nested_tree():
    nodes = nodes_from_spec("## One\nbody one\n\n### Under one\ndeeper\n\n## Two\n", "T")
    by_title = {n["title"]: n for n in nodes}

    assert by_title["T"]["parent"] is None
    assert by_title["One"]["parent"] == by_title["T"]["id"]
    assert by_title["Under one"]["parent"] == by_title["One"]["id"]
    assert by_title["Two"]["parent"] == by_title["T"]["id"]
    assert by_title["One"]["body"] == "body one"


def test_prose_before_the_first_heading_lands_on_the_root():
    nodes = nodes_from_spec("intro line\n\n## One\n", "T")
    assert nodes[0]["body"] == "intro line"


def test_a_spec_with_no_headings_is_a_single_root_node():
    nodes = nodes_from_spec("just prose", "T")
    assert len(nodes) == 1
    assert nodes[0]["body"] == "just prose"


def test_a_deeper_heading_after_a_shallower_one_climbs_back_out():
    # ### under ## under #, then a second # -- the stack has to unwind two
    # levels, not one.
    nodes = nodes_from_spec("# A\n## B\n### C\n# D\n", "T")
    by_title = {n["title"]: n for n in nodes}
    assert by_title["C"]["parent"] == by_title["B"]["id"]
    assert by_title["D"]["parent"] == by_title["T"]["id"]


@pytest.mark.django_db
def test_graph_uses_draft_while_the_spec_is_empty(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    s.draft = {"nodes": [{"id": "n1", "parent": None, "kind": "question",
                          "title": "Root", "summary": "", "body": ""}]}
    s.save(update_fields=["draft"])

    assert [n["id"] for n in graph_for(s)] == ["n1"]


@pytest.mark.django_db
def test_graph_switches_to_the_spec_once_it_is_written(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    s.draft = {"nodes": [{"id": "n1", "parent": None, "kind": "question",
                          "title": "Root", "summary": "", "body": ""}]}
    s.spec = "## Decided\nthe design"
    s.save(update_fields=["draft", "spec"])

    titles = [n["title"] for n in graph_for(s)]
    assert "Decided" in titles
    assert "Root" not in titles


@pytest.mark.django_db
def test_an_empty_slice_has_an_empty_graph(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    assert graph_for(s) == []
