"""Geometry for the slice canvas.

Pure functions only: no models, no request, no template. The arithmetic lives
here so it can be tested without a browser -- the animation layered on top of it
cannot be, so everything that *can* be checked headlessly is.
"""
import re

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


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def nodes_from_spec(spec, title):
    """Derive a node tree from a markdown spec's heading structure.

    The canvas is a view, never a second store: once a slice has a spec, the
    spec's own shape is what it shows. Prose above the first heading becomes
    the root's body so nothing on the page is silently dropped.
    """
    root = {"id": "s0", "parent": None, "kind": "note",
            "title": title, "summary": "", "body": ""}
    nodes = [root]
    bodies = {"s0": []}
    stack = [("s0", 0)]

    for line in (spec or "").splitlines():
        match = _HEADING.match(line)
        if not match:
            bodies[stack[-1][0]].append(line)
            continue
        level = len(match.group(1))
        # Climb out of every heading at or below this level, so a "#" after a
        # "###" lands back on the root rather than under its predecessor.
        while len(stack) > 1 and stack[-1][1] >= level:
            stack.pop()
        node_id = f"s{len(nodes)}"
        nodes.append({"id": node_id, "parent": stack[-1][0], "kind": "note",
                      "title": match.group(2), "summary": "", "body": ""})
        bodies[node_id] = []
        stack.append((node_id, level))

    for node in nodes:
        node["body"] = "\n".join(bodies[node["id"]]).strip()
    return nodes


def graph_for(slice_):
    """The canvas source for one slice.

    `decision_tree` while the design is still being made, the spec's own structure once
    it has been written. The two are exclusive in storage, so this never has to
    merge them -- and an untouched slice simply has nothing to draw.
    """
    if (slice_.spec or "").strip():
        return nodes_from_spec(slice_.spec, slice_.title)
    return (slice_.decision_tree or {}).get("nodes", [])
