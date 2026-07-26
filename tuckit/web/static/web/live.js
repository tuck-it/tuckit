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

  /* Refresh only #main-content on live screens, morphing rather than replacing.
     Morph keeps elements alive, which is what lets ordinary CSS transitions
     apply to data changes at all — and it delivers what the original live
     design asked for ("never swap the focused form / input text") without the
     blunt instrument of skipping the refresh outright.

     ignoreActiveValue is load-bearing, not decoration. A live screen can
     morph a form whose fields are server-rendered empty (e.g. the Create Area
     modal lives inside #main-content) — without this flag idiomorph's
     input/textarea sync would overwrite whatever the user is mid-typing with
     that empty value on every poll. It is set per swap below rather than
     hardcoded here.
     #detail-modal is a sibling of #main-content and is never swapped. */
  window.__liveOnEvents = function (events) {
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
