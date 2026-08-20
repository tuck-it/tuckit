/* The slice canvas: a left-to-right tree of cards.

   The server sends facts (which cards, whose child each is, when it arrived);
   this file owns geometry and motion. That split is why a 2s poll can feed a
   smooth canvas -- the same trick heat.js uses for its decay. */
(function () {
  var root = document.querySelector("[data-canvas]");
  if (!root) return;

  var COL_W = 372, NODE_W = 264, ROW_GAP = 20;   // keep in step with canvas.py
  var stage = root.querySelector("[data-stage]");
  var world = root.querySelector("[data-world]");
  var svg = root.querySelector("[data-edges]");
  var cards = Array.prototype.slice.call(root.querySelectorAll(".cnode"));
  var byId = {};
  cards.forEach(function (el) { byId[el.dataset.id] = el; });

  var tx = 24, ty = 20, scale = 1;
  var placed = null;

  function applyView() {
    world.style.transform = "translate(" + tx + "px," + ty + "px) scale(" + scale + ")";
  }

  var userMovedAt = 0;   // auto-follow yields to a human who just moved the view

  function showScale() {
    var label = root.querySelector("[data-scale]");
    if (label) label.textContent = Math.round(scale * 100) + "%";
  }

  /* Keep whatever is under the middle of the stage under the middle of the
     stage. transform-origin is 0 0, so scaling on its own would swing the tree
     away from wherever the reader was looking, and they would have to hunt for
     it again. */
  function setScale(next) {
    next = Math.max(0.25, Math.min(1.6, next));
    var cx = stage.clientWidth / 2, cy = stage.clientHeight / 2;
    tx = cx - ((cx - tx) / scale) * next;
    ty = cy - ((cy - ty) / scale) * next;
    scale = next;
    world.style.transition = "transform .3s var(--ease)";
    showScale();
    applyView();
    userMovedAt = Date.now();
  }

  function bounds() {
    if (!placed || !placed.size) return null;
    var a = Infinity, b = -Infinity, c = Infinity, d = -Infinity;
    placed.forEach(function (p) {
      a = Math.min(a, p.x); b = Math.max(b, p.x + NODE_W);
      c = Math.min(c, p.y); d = Math.max(d, p.y + p.h);
    });
    return { a: a, b: b, c: c, d: d };
  }

  function fit() {
    var r = bounds();
    if (!r) return;
    var pad = 40;
    var w = r.b - r.a, h = r.d - r.c;
    scale = Math.max(0.25, Math.min(
      (stage.clientWidth - pad * 2) / w, (stage.clientHeight - pad * 2) / h, 1.6));
    tx = pad - r.a * scale + Math.max(0, (stage.clientWidth - pad * 2 - w * scale) / 2);
    ty = pad - r.c * scale + Math.max(0, (stage.clientHeight - pad * 2 - h * scale) / 2);
    world.style.transition = "transform .45s var(--ease)";
    showScale();
    applyView();
    userMovedAt = Date.now();
  }

  /* Port of canvas.layout(). Same algorithm, real measured heights. */
  function layout(list, heights) {
    var kids = {}, depth = {}, band = {}, cursor = 0;
    list.forEach(function (el) {
      var p = el.dataset.parent;
      if (p) (kids[p] = kids[p] || []).push(el.dataset.id);
    });

    function walk(id, level) {
      depth[id] = level;
      var h = heights[id] || 88;
      var children = kids[id] || [];
      if (!children.length) {
        var top = cursor;
        cursor = top + h + ROW_GAP;
        band[id] = [top, h];
        return top + h / 2;
      }
      var centres = children.map(function (c) { return walk(c, level + 1); });
      var middle = (Math.min.apply(null, centres) + Math.max.apply(null, centres)) / 2;
      band[id] = [middle - h / 2, h];
      return middle;
    }
    list.forEach(function (el) { if (!el.dataset.parent) walk(el.dataset.id, 0); });

    var out = new Map();
    Object.keys(band).forEach(function (id) {
      out.set(id, { x: depth[id] * COL_W, y: band[id][0], h: band[id][1] });
    });

    /* A parent sits at its children's midpoint, so a parent taller than their
       band spills into the neighbouring one. Columns never overlap
       horizontally, so resolving each column on its own is enough. */
    var columns = {};
    Object.keys(depth).forEach(function (id) {
      (columns[depth[id]] = columns[depth[id]] || []).push(id);
    });
    Object.keys(columns).forEach(function (d) {
      var ids = columns[d].sort(function (a, b) { return out.get(a).y - out.get(b).y; });
      for (var i = 1; i < ids.length; i++) {
        var prev = out.get(ids[i - 1]), cur = out.get(ids[i]);
        var floor = prev.y + prev.h + ROW_GAP;
        if (cur.y < floor) cur.y = floor;
      }
    });
    return out;
  }

  /* The id a question settled on, read off the card's parent. "" when the
     question is still open or this card has no parent. */
  function chosenSiblingOf(el) {
    var parent = el.dataset.parent && byId[el.dataset.parent];
    return parent ? parent.dataset.chosen || "" : "";
  }

  function render(cold) {
    /* PASS 1 -- settle every class that changes a card's height BEFORE
       anything is measured. Get this order wrong and the tree is laid out from
       heights nothing on screen has: cards and edges are drawn apart, and the
       next render quietly covers it up. */
    cards.forEach(function (el) {
      var winner = chosenSiblingOf(el);
      el.classList.toggle("is-chosen", !!winner && winner === el.dataset.id);
      el.classList.toggle("is-dim",
        !!winner && winner !== el.dataset.id && el.classList.contains("cnode--option"));
    });

    // PASS 2 -- measure, lay out, place
    var heights = {};
    cards.forEach(function (el) { heights[el.dataset.id] = el.offsetHeight; });
    placed = layout(cards, heights);

    cards.forEach(function (el) {
      var p = placed.get(el.dataset.id);
      if (p) el.style.transform = "translate(" + p.x + "px," + p.y + "px)";
    });

    drawEdges();
    root.removeAttribute("data-pending");
  }

  function drawEdges() {
    var maxX = 0, maxY = 0;
    placed.forEach(function (p) {
      maxX = Math.max(maxX, p.x + NODE_W);
      maxY = Math.max(maxY, p.y + p.h);
    });
    svg.setAttribute("width", maxX + 40);
    svg.setAttribute("height", maxY + 40);

    cards.forEach(function (el) {
      var pid = el.dataset.parent;
      if (!pid) return;
      var a = placed.get(pid), b = placed.get(el.dataset.id);
      if (!a || !b) return;

      var key = pid + ">" + el.dataset.id;
      var path = svg.querySelector('[data-k="' + key + '"]');
      if (!path) {
        path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("data-k", key);
        svg.appendChild(path);
      }
      var x1 = a.x + NODE_W, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2;
      /* Exactly half the gap. Forcing a minimum wider than the gutter puts the
         first control point past the second; the curve then bulges backwards
         and reads as a stray vertical line floating between two cards. */
      var dx = (x2 - x1) / 2;
      path.setAttribute("d", "M" + x1 + "," + y1 + " C" + (x1 + dx) + "," + y1 +
                             " " + (x2 - dx) + "," + y2 + " " + x2 + "," + y2);
      path.classList.toggle("is-taken", byId[pid].dataset.chosen === el.dataset.id);
    });
  }

  /* Drag the background to pan. */
  var dragging = false, sx = 0, sy = 0;
  stage.addEventListener("mousedown", function (e) {
    if (e.target.closest(".cnode")) return;
    dragging = true; sx = e.clientX - tx; sy = e.clientY - ty;
    stage.classList.add("is-dragging");
    world.style.transition = "none";
    userMovedAt = Date.now();
  });
  window.addEventListener("mousemove", function (e) {
    if (!dragging) return;
    tx = e.clientX - sx; ty = e.clientY - sy; applyView();
  });
  window.addEventListener("mouseup", function () {
    if (dragging) userMovedAt = Date.now();
    dragging = false; stage.classList.remove("is-dragging");
  });

  root.querySelectorAll("[data-zoom]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var how = btn.dataset.zoom;
      if (how === "fit") fit();
      else setScale(how === "in" ? scale * 1.25 : scale / 1.25);
    });
  });

  applyView();
  render(true);

  window.__canvas = { render: render, layout: layout, fit: fit, setScale: setScale,
                     placed: function () { return placed; },
                     view: function () { return { tx: tx, ty: ty, scale: scale }; } };
})();
