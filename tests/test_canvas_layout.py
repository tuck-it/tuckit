import pytest

from tuckit.core.services.canvas import COL_W, NODE_W, ROW_GAP, layout


def _tree():
    return [
        {"id": "root", "parent": None},
        {"id": "a", "parent": "root"},
        {"id": "b", "parent": "root"},
        {"id": "b1", "parent": "b"},
        {"id": "b2", "parent": "b"},
    ]


def _centre(box):
    return box["y"] + box["h"] / 2


def test_x_is_a_function_of_depth_only():
    pos = layout(_tree(), {})
    assert pos["root"]["x"] == 0
    assert pos["a"]["x"] == COL_W
    assert pos["b1"]["x"] == 2 * COL_W


def test_the_gutter_leaves_room_for_an_edge_to_turn():
    # A bezier's control points cross, and the curve bulges backwards into a
    # stray vertical line, when the gutter is narrow. See constraint 11.
    assert COL_W - NODE_W >= 100


def test_a_parent_is_centred_on_its_children():
    pos = layout(_tree(), {})
    assert _centre(pos["b"]) == pytest.approx(
        (_centre(pos["b1"]) + _centre(pos["b2"])) / 2
    )


def test_no_two_cards_in_a_column_overlap_when_every_card_is_tall():
    # The regression that matters: cards have no height cap (D13), so a tall
    # parent must not spill into the band above or below it.
    nodes = _tree()
    pos = layout(nodes, {n["id"]: 400 for n in nodes})

    columns = {}
    for box in pos.values():
        columns.setdefault(box["x"], []).append(box)

    for boxes in columns.values():
        boxes.sort(key=lambda b: b["y"])
        for prev, cur in zip(boxes, boxes[1:]):
            assert cur["y"] >= prev["y"] + prev["h"], "cards overlap"


def test_missing_heights_fall_back_to_a_default():
    pos = layout(_tree(), {"root": 500})
    assert pos["root"]["h"] == 500
    assert pos["a"]["h"] > 0


def test_row_gap_is_honoured_between_siblings():
    pos = layout(_tree(), {})
    assert pos["b2"]["y"] - (pos["b1"]["y"] + pos["b1"]["h"]) == ROW_GAP
