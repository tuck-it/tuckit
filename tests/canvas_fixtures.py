"""Slice 208's real decision record, as structure.

Read off the live board on 2026-08-23: 25 nodes, every parent, kind, `chosen`,
`recommended` and batch timestamp exactly as stored. Bodies are filler at the
length the originals actually have, because what these tests exercise is the
SHAPE -- and this shape is the reason the redesign exists:

  - the continuation hangs off the QUESTION (`d1.parent == "q1"`), so the
    chosen option is a leaf and the story walks past it
  - `q1` is answered with `o3` while `o1` is the one marked recommended
  - `q2` and `q3` have no answer AND no later sibling: the design finished
    around them, so nothing marks them as passed except the record being sealed

Every synthetic fixture in the suite is a simplification of one of those.
"""

_ROWS = (
    "root,,n,,,1787404521678,389;q1,root,q,o3,,1787404521678,287;"
    "o1,q1,o,,R,1787404521678,312;o2,q1,o,,,1787404521678,396;"
    "o3,q1,o,,,1787404521678,430;d1,q1,n,,,1787404947826,295;"
    "q2,d1,q,,,1787404947826,267;p1,q2,o,,R,1787404947826,577;"
    "p2,q2,o,,,1787404947826,308;p3,q2,o,,,1787404947826,294;"
    "p4,q2,o,,,1787404947826,200;d2,q2,n,,,1787405543023,472;"
    "q3,d2,q,,,1787405543023,321;r1,q3,o,,R,1787405543023,283;"
    "r2,q3,o,,,1787405543023,279;r3,q3,o,,,1787405543023,290;"
    "r4,q3,o,,,1787405543023,197;d3,q3,n,,,1787405974558,132;"
    "n1,d3,n,,,1787405974558,1103;q4,d3,q,s1,,1787406643793,416;"
    "s1,q4,o,,R,1787406643793,357;s2,q4,o,,,1787406643793,178;"
    "s3,q4,o,,,1787406643793,168;s4,q4,o,,,1787406643793,236;"
    "d4,q4,n,,,1787406811321,347"
)

_KIND = {"n": "note", "q": "question", "o": "option"}
_FILL = "what this option changes, what it buys, and what it costs. "


def slice_208_nodes():
    """A fresh copy each call -- callers mutate (choose, propose, re-parent)."""
    nodes = []
    for row in _ROWS.split(";"):
        node_id, parent, kind, chosen, rec, at, body_len = row.split(",")
        node = {"id": node_id, "parent": parent or None, "kind": _KIND[kind],
                "title": f"node {node_id}", "summary": f"one line about {node_id}",
                "body": (_FILL * 30)[: int(body_len)], "at": int(at)}
        if chosen:
            node["chosen"] = chosen
        if rec:
            node["recommended"] = True
        nodes.append(node)
    return nodes
