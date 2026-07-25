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
             noted: "noted on", promoted: "promoted", dismissed: "dismissed",
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

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) { interval = FAST; schedule(); }
  });

  function typingInMain(main) {
    var a = document.activeElement;
    if (!a || !main.contains(a)) return false;
    var tag = a.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || a.isContentEditable;
  }

  /* Refresh only #main-content on live screens. htmx inherits hx-swap/hx-target
     from ancestors, so we use the JS API with explicit options instead of
     attributes. #detail-modal is a sibling of #main-content and is never swapped. */
  window.__liveOnEvents = function (events) {
    var main = document.getElementById("main-content");
    if (!main || !main.hasAttribute("data-live-refresh")) return;
    // Never clobber in-progress typing. The cursor already advanced in poll(),
    // so these events won't re-deliver — the background stays as-is until the
    // NEXT activity batch triggers a refresh (after typing has moved on). The
    // toast for this batch already fired, so nothing is silently lost.
    if (typingInMain(main)) return;
    var scrollY = window.scrollY;
    htmx.ajax("GET", location.pathname + location.search, {
      target: "#main-content",
      select: "#main-content",
      swap: "outerHTML"
    }).then(function () {
      window.scrollTo(0, scrollY);          // preserve viewport across the swap
      document.body.dispatchEvent(new CustomEvent("tuckit:live-refreshed", { detail: { events: events } }));
    });
  };

  /* Highlight what CHANGED ON SCREEN, which is not always the event's target.
     A bite has no element of its own here — it shows up as its slice's bite
     progress — so those events carry highlight_type/highlight_id pointing at the
     parent slice. Everything else omits them and highlights itself. */
  document.body.addEventListener("tuckit:live-refreshed", function (e) {
    (e.detail.events || []).forEach(function (ev) {
      var type = ev.highlight_type || ev.target_type;
      var id = ev.highlight_id || ev.target_id;
      var sel = "[data-" + type + "-id=\"" + id + "\"]";
      document.querySelectorAll(sel).forEach(function (el) {
        el.classList.add("just-live");
        setTimeout(function () { el.classList.remove("just-live"); }, 1600);
      });
    });
  });

  schedule();
})();
