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
  var seen = Object.create(null);        // cards already placed at least once
  var drawnEdges = Object.create(null);  // edges whose draw-in has already played

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
      if (el.classList.contains("cnode--question"))
        el.classList.toggle("is-settled", !!el.dataset.chosen);
      // Once the answer is in, the agent's preference is noise on the picture.
      if (winner && el.classList.contains("cnode--option"))
        el.classList.remove("is-rec");
    });

    // PASS 2 -- measure, lay out, place
    var heights = {};
    cards.forEach(function (el) { heights[el.dataset.id] = el.offsetHeight; });
    placed = layout(cards, heights);

    /* Only cards that ARRIVED animate. Replaying the entrance for a graph that
       was already complete means every page load opens on ~2s of empty canvas. */
    var arriving = cards.filter(function (el) { return !seen[el.dataset.id]; });
    cards.forEach(function (el) {
      var p = placed.get(el.dataset.id);
      if (!p) return;
      var target = "translate(" + p.x + "px," + p.y + "px)";

      if (seen[el.dataset.id] || cold) {
        if (cold) { el.style.transition = "none"; el.style.opacity = "1"; }
        el.style.transform = target;
        if (cold) requestAnimationFrame(function () { el.style.transition = ""; });
      } else {
        var parent = placed.get(el.dataset.parent);
        el.style.opacity = "0";
        el.style.transform = parent
          ? "translate(" + parent.x + "px," + parent.y + "px) scale(.9)"
          : target;
        var delay = arriving.indexOf(el) * 90;
        requestAnimationFrame(function () { requestAnimationFrame(function () {
          el.style.transitionDelay = delay + "ms";
          el.style.opacity = "1";
          el.style.transform = target;
          setTimeout(function () { el.style.transitionDelay = "0ms"; }, delay + 700);
        }); });
      }
      seen[el.dataset.id] = true;
    });

    drawEdges(cold);
    follow(arriving);
    root.removeAttribute("data-pending");
  }

  /* The tree grows rightwards. A viewport that stays put makes the reader chase
     each new card by hand -- the exact friction this canvas exists to remove.
     Yields for 15s after any deliberate pan or zoom. */
  function follow(arriving) {
    if (!arriving.length || Date.now() - userMovedAt < 15000) return;
    var a = Infinity, b = -Infinity, c = Infinity, d = -Infinity;
    arriving.forEach(function (el) {
      var p = placed.get(el.dataset.id);
      if (!p) return;
      a = Math.min(a, p.x); b = Math.max(b, p.x + NODE_W);
      c = Math.min(c, p.y); d = Math.max(d, p.y + p.h);
    });
    if (a > b) return;
    tx = Math.min(24, stage.clientWidth * 0.62 - ((a + b) / 2) * scale);
    ty = stage.clientHeight * 0.5 - ((c + d) / 2) * scale;
    world.style.transition = "transform .85s var(--ease)";
    applyView();
  }

  function drawEdges(cold) {
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

      if (!drawnEdges[key]) {
        drawnEdges[key] = true;
        if (cold) return;                       // cold load: plain solid line
        var len = path.getTotalLength();
        path.style.transition = "none";
        path.style.strokeDasharray = len;
        path.style.strokeDashoffset = len;
        requestAnimationFrame(function () { requestAnimationFrame(function () {
          path.style.transition = "stroke-dashoffset .6s var(--ease), stroke .3s";
          path.style.strokeDashoffset = "0";
          /* A dasharray left behind is frozen at the length the path had when
             it first appeared. The moment the layout moves and the path grows,
             that stale value repeats as a dash pattern and the edge renders
             broken -- so drop it once the draw-in has played. */
          setTimeout(function () {
            path.style.transition = "";
            path.style.strokeDasharray = "";
            path.style.strokeDashoffset = "";
          }, 1500);
        }); });
      }
    });
  }

  /* Adopt a freshly rendered canvas partial: keep the cards already on screen,
     append the ones that are new, and let render() animate exactly those.
     Returns true if anything arrived.

     A caller running this from a polling loop must wrap it in its own
     try/catch -- live.js catches after invoking its hook and blames the
     network, so an exception thrown here would surface only as a visual
     glitch with a silent console. */
  function syncFromServer(html) {
    var incoming = document.createElement("div");
    incoming.innerHTML = html;
    var added = false;
    incoming.querySelectorAll(".cnode").forEach(function (el) {
      var known = byId[el.dataset.id];
      if (known) {
        known.dataset.chosen = el.dataset.chosen || "";
        return;
      }
      world.appendChild(el);
      cards.push(el);
      byId[el.dataset.id] = el;
      observer.observe(el);
      added = true;
    });
    if (added || incoming.querySelector("[data-chosen]")) render(false);
    return added;
  }

  /* A mockup in a 264px card is decoration; opened large it is evidence. */
  stage.addEventListener("click", function (e) {
    var img = e.target.closest("[data-media]");
    if (!img) return;
    e.stopPropagation();
    var box = document.createElement("div");
    box.className = "canvas-lightbox";
    var big = document.createElement("img");
    big.src = img.src;
    big.alt = img.alt;
    box.appendChild(big);
    box.addEventListener("click", function () { box.remove(); });
    document.addEventListener("keydown", function esc(ev) {
      if (ev.key === "Escape") { box.remove(); document.removeEventListener("keydown", esc); }
    });
    document.body.appendChild(box);
  });

  /* Choosing used to live here. It moved to spine.js, delegated on the
     document, when the spine became the surface that answers questions: the
     map no longer renders a pick control at all, and one irreversible POST
     wants exactly one implementation. */

  /* width/height on the <img> reserve the box, so a mockup that arrives late
     changes nothing. This is the net for everything else -- a font swap, an
     edited body, an image whose dimensions were never recorded. Without the
     reserved box the page jumps once per image; without this it jumps once
     per image that forgot to declare one. */
  var reflowTimer = null;
  var observer = new ResizeObserver(function () {
    clearTimeout(reflowTimer);
    reflowTimer = setTimeout(function () { render(false); }, 60);
  });
  cards.forEach(function (el) { observer.observe(el); });

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

  /* Maximize is a class on the section and nothing more. The element never
     leaves the DOM, so nothing here has to be re-measured or re-initialised --
     only the view transform is wrong afterwards, because the stage changed
     size. fit() is exactly that recomputation; render() would be busywork,
     since layout() does not read the stage and the cards are a fixed width. */
  var maxBtn = root.querySelector("[data-maximize]");

  function maximize(on) {
    root.classList.toggle("is-max", on);
    document.body.classList.toggle("canvas-maxed", on);
    if (maxBtn) {
      maxBtn.setAttribute("aria-expanded", on ? "true" : "false");
      maxBtn.textContent = on ? "Restore" : "Expand";
    }
    /* The stage resizes with the class; fit() has to measure it afterwards, so
       it waits a frame. Note this makes maximize a no-op in a background tab,
       where rAF is suspended entirely -- harmless, since nobody is looking. */
    requestAnimationFrame(fit);
  }

  if (maxBtn) maxBtn.addEventListener("click", function () {
    maximize(!root.classList.contains("is-max"));
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape" || !root.classList.contains("is-max")) return;
    /* The lightbox opens FROM this surface and registers its own Escape
       handler. Without this both fire on one keypress: the image closes and
       the canvas collapses out from under it. Innermost wins. */
    if (document.querySelector(".canvas-lightbox")) return;
    maximize(false);
    if (maxBtn) maxBtn.focus();
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
                     sync: syncFromServer, maximize: maximize,
                     placed: function () { return placed; },
                     view: function () { return { tx: tx, ty: ty, scale: scale }; } };
})();
