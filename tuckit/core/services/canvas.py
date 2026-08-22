"""Geometry for the slice canvas.

Pure functions only: no models, no request, no template. The arithmetic lives
here so it can be tested without a browser -- the animation layered on top of it
cannot be, so everything that *can* be checked headlessly is.
"""

COL_W = 372      # column pitch
NODE_W = 264     # card width
ROW_GAP = 20     # vertical breathing room between cards
DEFAULT_H = 88   # used when the caller has not measured a card yet

# The gap an edge has to turn in. A bezier whose control points are pushed past
# each other bulges backwards and reads as a stray vertical line floating
# between two cards, so this is a real constraint and not a spacing preference.
GUTTER = COL_W - NODE_W


def layout(nodes, heights):
    """Place a left-to-right tree. Returns {id: {"x", "y", "h"}}.

    `heights` maps a node id to its measured card height. The server does not
    know real heights at first paint and passes {}; the client re-runs this
    same algorithm once it can measure.
    """
    children = {}
    for node in nodes:
        parent = node.get("parent")
        if parent:
            children.setdefault(parent, []).append(node["id"])

    depth = {}
    band = {}
    cursor = 0

    def walk(node_id, level):
        nonlocal cursor
        depth[node_id] = level
        height = heights.get(node_id, DEFAULT_H)
        kids = children.get(node_id, [])
        if not kids:
            top = cursor
            cursor = top + height + ROW_GAP
            band[node_id] = (top, height)
            return top + height / 2
        centres = [walk(kid, level + 1) for kid in kids]
        middle = (min(centres) + max(centres)) / 2
        band[node_id] = (middle - height / 2, height)
        return middle

    for node in nodes:
        if not node.get("parent"):
            walk(node["id"], 0)

    placed = {
        node_id: {"x": depth[node_id] * COL_W, "y": top, "h": height}
        for node_id, (top, height) in band.items()
    }
    _push_apart_within_columns(placed, depth)
    return placed


def _push_apart_within_columns(placed, depth):
    """Resolve overlap one column at a time.

    A parent sits at the midpoint of its children, so a parent taller than its
    children's band spills into the neighbouring band -- visible as soon as
    several cards are expanded, and cards have no height cap. Columns never
    overlap horizontally (COL_W > NODE_W), so sorting each column by y and
    pushing anything that collides with its predecessor downwards is enough.
    """
    columns = {}
    for node_id in placed:
        columns.setdefault(depth[node_id], []).append(node_id)

    for ids in columns.values():
        ids.sort(key=lambda i: placed[i]["y"])
        for previous, current in zip(ids, ids[1:]):
            floor = placed[previous]["y"] + placed[previous]["h"] + ROW_GAP
            if placed[current]["y"] < floor:
                placed[current]["y"] = floor


def graph_for(slice_):
    """The canvas source for one slice: its decision record, and nothing else.

    The spec has its own surface on the slice page, so drawing it here too --
    which this used to do, by parsing its headings into a tree -- put a table of
    contents on screen in the shape of a decision record. The two answer
    different questions and they do not share a picture.
    """
    return (slice_.decision_tree or {}).get("nodes", [])


def _kind(node):
    return node.get("kind") or "note"


def question_state(question, nodes):
    """answered | waiting | passed.

    `passed` is a question nobody answered and the conversation moved past: a
    later sibling question exists. That state has no field of its own on
    purpose -- the record is append-only, so storing it would need a write
    path for "the human said no", and "no" is just the next question.

    A batch shares one `at` (propose_nodes stamps it once), so equal
    timestamps mean parallel questions rather than a passed-over one. Legacy
    nodes carry no `at` at all; reading those as 0 makes every comparison a
    tie, which errs towards `waiting` -- the state that shows more, never less.
    """
    if question.get("chosen"):
        return "answered"
    at = question.get("at") or 0
    parent = question.get("parent")
    for other in nodes:
        if other is question or _kind(other) != "question":
            continue
        if other.get("parent") == parent and (other.get("at") or 0) > at:
            return "passed"
    return "waiting"


def is_locked(question, nodes):
    """True once the chosen option has grown children.

    That moment -- not the clock, not the spec -- is when re-answering would
    start lying: everything under the chosen option exists BECAUSE of it, so
    pointing `chosen` elsewhere would silently re-read all of it as the
    consequence of a decision that never produced it.
    """
    chosen = question.get("chosen")
    if not chosen:
        return False
    return any(n.get("parent") == chosen for n in nodes)


def spine_for(nodes):
    """The decision record in reading order: one flat list of rows.

    Linear, so unlike the map this needs no re-parenting -- with the rows in
    the right ORDER it does not matter which node the author hung the
    continuation on. That is what makes every canvas written before this
    rule existed readable rather than merely present.

    A row is {node, row, state, locked, options, rejected}; `state`, `locked`,
    `options` and `rejected` only carry meaning on a question row.
    """
    by_id = {n["id"]: n for n in nodes}
    seq = {n["id"]: i for i, n in enumerate(nodes)}
    kids = {}
    for node in nodes:
        kids.setdefault(node.get("parent"), []).append(node)

    rows = []

    def walk(node):
        children = kids.get(node["id"], [])
        after = [c for c in children if _kind(c) != "option"]

        if _kind(node) == "question":
            options = [c for c in children if _kind(c) == "option"]
            state = question_state(node, nodes)
            chosen = by_id.get(node.get("chosen") or "")
            rows.append({
                "node": node, "row": "question", "state": state,
                "locked": is_locked(node, nodes),
                "options": options if state == "waiting" else [],
                "rejected": [] if state == "waiting"
                            else [o for o in options if o is not chosen],
            })
            if chosen is not None:
                rows.append({"node": chosen, "row": "chosen", "state": None,
                             "locked": False, "options": [], "rejected": []})
                # The continuation can hang off either one. Correct callers
                # put it under the chosen option; every canvas older than that
                # rule put it under the question, and both have to read.
                after = [c for c in kids.get(chosen["id"], [])
                         if _kind(c) != "option"] + after
        else:
            rows.append({"node": node, "row": "note", "state": None,
                         "locked": False, "options": [], "rejected": []})

        for child in sorted(after, key=lambda n: (n.get("at") or 0, seq[n["id"]])):
            walk(child)

    for node in nodes:
        if not node.get("parent"):
            walk(node)
    return rows


def reparented(nodes):
    """The map's view of the same tree, with the continuation under the winner.

    Display only -- the stored nodes are never touched, because the record is
    append-only and the canvases needing this correction were written before
    the rule existed. The map draws EDGES, so unlike the spine it cannot fix
    this with ordering alone: an edge that skips the chosen card is exactly
    the picture that makes a reader doubt what they chose.
    """
    answered = {n["id"]: n["chosen"] for n in nodes
                if _kind(n) == "question" and n.get("chosen")}
    out = []
    for node in nodes:
        winner = answered.get(node.get("parent"))
        if winner and _kind(node) != "option" and node["id"] != winner:
            node = dict(node, parent=winner)
        out.append(node)
    return out
