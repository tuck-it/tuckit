import pytest

from tuckit.core.services.slices import (
    choose_option, create_slice, propose_nodes, update_slice,
)
from tuckit.core.services.watches import open_watch, read_watch


def _tree(slice_):
    propose_nodes(slice_, [
        {"id": "q1", "parent": None, "kind": "question", "title": "Which way?"},
        {"id": "o1", "parent": "q1", "kind": "option", "title": "Left"},
        {"id": "o2", "parent": "q1", "kind": "option", "title": "Right"},
    ])


@pytest.mark.django_db
def test_a_choice_reaches_the_watch(org, area):
    s = create_slice(org, area=area, title="Canvas", spec="")
    _tree(s)
    _, raw = open_watch(s)

    choose_option(s, "o2")

    assert read_watch(raw) == {"status": "chosen", "choice": "o2"}


@pytest.mark.django_db
def test_a_choice_never_reaches_another_slice_s_watch(org, area):
    mine = create_slice(org, area=area, title="Mine", spec="")
    theirs = create_slice(org, area=area, title="Theirs", spec="")
    _tree(mine)
    _, raw = open_watch(theirs)

    choose_option(mine, "o2")

    assert read_watch(raw) == {"status": "waiting"}


@pytest.mark.django_db
def test_writing_the_spec_retires_the_channel(org, area):
    """The design stopped being open, so the channel is not a channel any
    more."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    _tree(s)
    _, raw = open_watch(s)

    update_slice(s, spec="## Decided\nWe went with Right.")

    assert read_watch(raw) is None


@pytest.mark.django_db
def test_an_empty_spec_is_not_a_written_one(org, area):
    """'' means "still being designed". Retiring the watch there would kill the
    channel in the middle of the conversation it exists for -- the same rule
    that stops an empty spec wiping the draft."""
    s = create_slice(org, area=area, title="Canvas", spec="")
    _tree(s)
    _, raw = open_watch(s)

    update_slice(s, spec="   ")

    assert read_watch(raw) == {"status": "waiting"}
