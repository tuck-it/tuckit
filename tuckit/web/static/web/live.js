/* Live dashboard poller. Reads a cheap org-scoped activity cursor and raises
   toasts + (Task 6) refreshes the current screen. No persistent connection:
   every poll is a stateless request, so the server holds zero per-client state.
   Cost controls: pause when the tab is hidden; back off when idle. */
(function () {
  var cfg = document.getElementById("live-config");
  if (!cfg) return;
  var url = cfg.dataset.liveUrl;
  var cursor = parseInt(cfg.dataset.cursor || "0", 10) || 0;

  var FAST = 2000, SLOW = 30000;
  var interval = FAST;
  var timer = null;
  var inFlight = false;

  function schedule() {
    clearTimeout(timer);
    if (document.hidden) return;            // visibility gating: hidden tab polls nothing
    timer = setTimeout(poll, interval);
  }

  function poll() {
    if (inFlight || document.hidden) { schedule(); return; }
    inFlight = true;
    fetch(url + "?since=" + cursor, { headers: { "X-Requested-With": "live" }, credentials: "same-origin" })
      .then(function (r) {
        if (r.status === 204) { interval = Math.min(interval * 1.5, SLOW); return null; }
        if (!r.ok) return null;
        return r.json();
      })
      .then(function (data) {
        if (data && data.events && data.events.length) {
          cursor = data.cursor;
          interval = FAST;                   // activity → poll fast again
          announce(data.events);
          if (window.__liveOnEvents) window.__liveOnEvents(data.events);
        }
      })
      .catch(function () { /* transient network error: just keep polling */ })
      .then(function () { inFlight = false; schedule(); });
  }

  function label(verb) {
    return { created: "added", status_changed: "updated", moved: "moved",
             shipped: "shipped", dropped: "dropped", planned: "planned a plan on",
             noted: "noted on", chose: "chose on",
             promoted: "promoted", dismissed: "dismissed",
             deleted: "deleted" }[verb] || verb;
  }

  /* One toast per poll batch (showToast replaces #toast, so N calls would only
     leave the last). Single event → describe it; many → summarize. */
  function announce(events) {
    var anyAgent = events.some(function (e) { return e.actor === "agent"; });
    var who = anyAgent ? "🤖 agent" : "Someone";
    if (events.length === 1) {
      var e = events[0];
      var actor = e.actor === "agent" ? "🤖 agent" : "Someone";
      showToast(actor + " " + label(e.verb) + " " + (e.target_label || e.target_type));
    } else {
      showToast(who + " made " + events.length + " updates");
    }
  }

  /* Skip past the events THIS tab just caused.

     The poll feed is org-scoped and unfiltered — the server has no way to
     exclude you, because ActivityEvent.actor only records human-vs-agent, not
     which member. So your own click came back on the next tick and announce()
     called it "Someone", i.e. the app narrated your action to you as if a
     stranger had done it. Worse: showToast REPLACES #toast, so that stranger
     message overwrote the action's own toast — and the Undo button inside it.
     With FAST at 2s the reversal this release is built on was on screen for
     about two seconds, and the user was never told why it went.

     Every mutating response carries the org's newest activity id (see
     LiveCursorMiddleware); adopting it means the poller resumes from AFTER
     your own writes. Other people's events are unaffected — they land with
     higher ids and still toast. Only ever moves forward. */
  /* Let a write that is NOT an htmx request adopt the same watermark.
     brainstorm.js posts a choice with fetch(), which never fires
     htmx:afterRequest -- so without this the click comes back on the next poll
     and is announced to the person who just made it, replacing their own
     toast. Only ever moves forward. */
  window.__liveAdoptCursor = function (value) {
    var seen = parseInt(value || "", 10);
    if (seen && seen > cursor) cursor = seen;
  };

  document.body.addEventListener("htmx:afterRequest", function (e) {
    var xhr = e.detail && e.detail.xhr;
    if (!xhr) return;
    window.__liveAdoptCursor(xhr.getResponseHeader("X-Live-Cursor"));
  });

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) { interval = FAST; schedule(); }
  });

  /* Refresh only #main-content on live screens, morphing rather than replacing.
     Morph keeps elements alive, which is what lets ordinary CSS transitions
     apply to data changes at all — and it delivers what the original live
     design asked for ("never swap the focused form / input text") without the
     blunt instrument of skipping the refresh outright.

     ignoreActiveValue is load-bearing, not decoration — but not for the
     reason a live screen morphing a form might suggest: per-screen overlays
     like the Create Area modal live in {% block overlays %}, never inside
     #main-content, so no <input>/<textarea> is ever in scope here. The
     value-bearing control that IS in scope is the Inbox row's Area
     <select> (_inbox_row.html). A <select>'s selection rides on
     <option selected>, reached only via morphChildren, so it is the
     focused-node subtree skip — not idiomorph's input/textarea value sync —
     that protects it. It is set per swap below rather than hardcoded here
     because that same subtree skip also covers #main-content itself
     (tabindex="-1", base.html:77), which takes focus on any click that lands
     on non-focusable content; a hardcoded flag froze the whole screen
     whenever that happened. The per-swap check trades that coverage away
     deliberately: the screen stays live and the Area select can reset to its
     placeholder on the next poll if the user isn't actively focused on it —
     harmless here, since (unlike the old Ticket row) nothing mirrors this
     select into a separate Alpine value that could desync from it.
     #detail-modal is a sibling of #main-content and is never swapped. */
  /* The canvas keeps its own DOM. A #main-content morph would replace the
     cards mid-animation and drop every transform the client just computed, so
     it merges from the same page instead -- and it does that whether or not
     this screen opted into the main-content swap.

     Two cases. Once the stage exists, sync() folds the new cards in and
     animates only those. Before it exists -- a slice nobody has designed yet,
     which is where every design conversation starts -- there is no stage and no
     brainstorm.js at all, so the first proposal has to install both. */
  function mergeCanvas() {
    return fetch(location.pathname + location.search, {
      headers: { "X-Requested-With": "live" }, credentials: "same-origin"
    })
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (html) {
        if (!html) return;
        /* Its own try/catch: the .catch() below reads every failure as a
           network hiccup, so an exception thrown in here would show up as a
           visual glitch with a silent console. */
        try {
          /* The SPINE first. It is the surface that carries the pick controls,
             so a question proposed mid-session is unanswerable until this runs
             -- which is the whole point of watching a canvas grow. The slice
             page never opted into the #main-content swap, so nothing else
             brings it up to date. */
          mergeSpine(html);
          if (window.__canvas) { window.__canvas.sync(html); return; }
          installCanvas(html);
        } catch (e) { console.error("[canvas] sync failed", e); }
      })
      .catch(function () { /* transient: the next poll tries again */ });
  }

  /* Replace the spine when the server's copy differs from what is on screen.

     Comparing first is load-bearing, not an optimisation: the spine holds open
     <details> folds, and replacing it every two seconds would snap shut the
     rejected branch a reader was in the middle of. It is server-rendered from
     spine_for(), so equal HTML means equal state.

     A slice with nothing to draw renders no spine at all, so the first ever
     proposal has to INSERT one -- and _spine.html carries the <script> tag
     that loads spine.js, which is why the insert has to re-run it. spine.js
     guards itself with a sentinel, so re-running is safe. */
  var lastSpine = (document.querySelector("[data-spine]") || {}).innerHTML;

  function mergeSpine(html) {
    var incoming = document.createElement("div");
    incoming.innerHTML = html;
    var fresh = incoming.querySelector("[data-spine]");
    if (!fresh) return;
    var current = document.querySelector("[data-spine]");
    if (current) {
      /* Compare against the last SERVER html, never against the live DOM.
         Opening a <details> writes the `open` attribute into the DOM, so a
         DOM comparison differs on every poll from the moment a reader expands
         a rejected branch -- and the replacement would then snap it shut every
         two seconds, which is worse than not updating at all. */
      if (fresh.innerHTML === lastSpine) return;
      /* A replacement is real, so carry the reader's expanded folds across it.
         Matching on the summary text rather than position keeps them attached
         to the branch they belong to when new rows appear above. */
      var open = {};
      current.querySelectorAll("details[open] > summary").forEach(function (s) {
        open[s.textContent.trim()] = true;
      });
      current.replaceWith(fresh);
      fresh.querySelectorAll("details > summary").forEach(function (s) {
        if (open[s.textContent.trim()]) s.parentNode.open = true;
      });
      lastSpine = fresh.innerHTML;
    } else {
      var slot = document.querySelector("[data-graph-slot]");
      if (!slot) return;                       // not a slice page
      slot.parentNode.insertBefore(fresh, slot);
      lastSpine = fresh.innerHTML;
    }
    var script = document.createElement("script");
    script.src = "/static/web/spine.js";
    document.body.appendChild(script);
  }

  /* Answering is a fetch, so it never produces the htmx event live.js watches.
     spine.js calls this to redraw from the server instead of reloading the
     page, which would throw away scroll position mid-conversation. */
  window.__liveRefreshSpine = mergeCanvas;

  /* First nodes ever: move the rendered stage into the slot and load the script
     that drives it. brainstorm.js is an IIFE that returns immediately when it
     finds no [data-canvas], so it has to run AFTER the stage is in the DOM --
     which is also why re-appending the tag is how it gets started, rather than
     calling something on it.

     The static path is written out here rather than derived. It is safe for the
     reason the org-scoped routes are not: STATIC_URL is "/static/" and carries
     no /<org>/ segment. If static files ever move behind a hash or a CDN, read
     the src off the <script> tag in the fetched HTML instead. */
  function installCanvas(html) {
    var slot = document.querySelector("[data-graph-slot]");
    if (!slot || slot.querySelector("[data-canvas]")) return;
    var incoming = document.createElement("div");
    incoming.innerHTML = html;
    var stage = incoming.querySelector("[data-canvas]");
    if (!stage) return;                       // still nothing to draw
    slot.appendChild(stage);
    var script = document.createElement("script");
    script.src = "/static/web/brainstorm.js";
    document.body.appendChild(script);
  }

  window.__liveOnEvents = function (events) {
    if (window.__canvas || document.querySelector("[data-graph-slot]")) mergeCanvas();
    var main = document.getElementById("main-content");
    if (!main || !main.hasAttribute("data-live-refresh")) return;
    htmx.ajax("GET", location.pathname + location.search, {
      target: "#main-content",
      select: "#main-content",
      swap: 'morph:{"morphStyle":"outerHTML"}'
    }).then(function () {
      document.body.dispatchEvent(new CustomEvent("tuckit:live-refreshed", { detail: { events: events } }));
    });
  };

  /* Ask for ignoreActiveValue only while the focus is actually holding a value.
     The flag protects what the user is typing, but idiomorph enforces it far
     more bluntly than that: morphNode skips morphChildren entirely for
     document.activeElement, so the whole focused subtree stops updating — not
     just its value. A <summary> takes focus when it is clicked, so opening the
     Area Inbox strip froze the "N untriaged" count inside it while the rows
     below it kept morphing. Requesting the flag only for a control that has a
     value to lose keeps the typing protection and lets everything else morph.

     Decided per swap (and not in the swap spec above) because the honest answer
     only exists when the response lands: the user can start typing while the
     poll request is in flight. htmx fires this event immediately before the
     morph, and a spec that omits the key inherits it from Idiomorph.defaults. */
  function focusHoldsAValue() {
    var el = document.activeElement;
    if (!el) return false;
    if (el.isContentEditable) return true;
    return el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT";
  }
  document.body.addEventListener("htmx:beforeSwap", function () {
    if (window.Idiomorph) window.Idiomorph.defaults.ignoreActiveValue = focusHoldsAValue();
  });

  schedule();
})();
