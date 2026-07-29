/* Agent occupancy warmth.

   An element carries data-last-touch (epoch ms) when an agent touched it
   recently. Heat is a pure function of how long ago that was, so once the
   client knows the timestamp it can render the whole decay locally — no
   further server contact, which is why polling stays sufficient and a
   WebSocket would buy only a sooner onset.

   Ticks once a second: the fade runs over two minutes, so a 1s step changes
   alpha by well under one percent. 60fps would burn battery to no effect. */
(function () {
  var HOLD = 20000;    // full heat for the first 20s
  var FADE = 100000;   // then linear to zero over 100s
  var timer = null;

  function heatFor(lastTouch, now) {
    var age = now - lastTouch;
    if (age <= HOLD) return 1;
    if (age >= HOLD + FADE) return 0;
    return 1 - (age - HOLD) / FADE;
  }

  function tick() {
    var now = Date.now();
    var warm = 0;
    document.querySelectorAll("[data-last-touch]").forEach(function (el) {
      var heat = heatFor(parseInt(el.dataset.lastTouch, 10) || 0, now);
      if (heat > 0) {
        el.style.setProperty("--heat", heat.toFixed(3));
        warm++;
      } else {
        /* Clear the property but LEAVE the attribute: it is server-rendered,
           and stripping it here would fight the next morph, which re-adds it. */
        el.style.removeProperty("--heat");
      }
      var when = el.querySelector(".agent-when");
      if (when) when.textContent = heat > 0 ? " · " + ago(now - (parseInt(el.dataset.lastTouch, 10) || 0)) : "";
    });
    if (!warm) { clearInterval(timer); timer = null; }
  }

  function ago(ms) {
    var s = Math.round(ms / 1000);
    if (s < 10) return "just now";
    if (s < 60) return s + "s ago";
    return Math.round(s / 60) + "m ago";
  }

  function start() {
    tick();
    if (!timer && document.querySelector("[data-last-touch]")) {
      timer = setInterval(tick, 1000);
    }
  }

  start();
  /* Every refresh re-renders the attributes from the server, so rescanning
     after a swap is all the coupling this needs to the poller. */
  document.body.addEventListener("tuckit:live-refreshed", start);

  /* The old Ticket-based Inbox row (_ticket_row.html, retired in Task 9)
     mirrored its Area <select> into an Alpine `area` value that drove a
     separate Promote button's :disabled state — a morph could desync the
     two, hence a resync here on every live refresh. The Slice-based Inbox
     row (_inbox_row.html) has no such button and no local Alpine state to
     desync: picking an area posts immediately, so there is nothing left to
     resync after a morph. If a future row reintroduces a submit-gated
     control with its own Alpine mirror of a <select>, resurrect this
     pattern rather than reaching for a global one. */

  document.body.addEventListener("htmx:beforeSwap", function () {
    if (!window.Idiomorph) return;

    /* Shape ④ exit. Idiomorph asks before removing a node; answering false
       keeps it for one animation, then removes it. Only items with a stable
       id are animated — anything else is structural markup whose removal is
       not a "thing leaving" the user should watch. */
    window.Idiomorph.defaults.callbacks.beforeNodeRemoved = function (node) {
      if (!node.dataset) return true;
      var tracked = node.dataset.sliceId || node.dataset.ticketId || node.dataset.areaId;
      if (!tracked || node.classList.contains("is-leaving")) return true;
      node.classList.add("is-leaving");
      setTimeout(function () { node.remove(); }, 200);
      return false;
    };
  });
})();
