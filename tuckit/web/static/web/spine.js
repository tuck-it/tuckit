/* Choosing an option, for every surface that offers it.

   Delegated on `document` rather than bound to a container: the spine and the
   node graph both carry [data-pick] controls, and cards arriving on the live
   poll are appended without anything re-binding them. One implementation of an
   irreversible POST is the right number. */
(function () {
  function cookie(name) {
    var hit = document.cookie.split("; ").find(function (row) {
      return row.indexOf(name + "=") === 0;
    });
    return hit ? decodeURIComponent(hit.slice(name.length + 1)) : "";
  }

  document.addEventListener("click", function (e) {
    var pick = e.target.closest("[data-pick]");
    if (!pick) return;
    /* The address is read off the element, never assembled here: these routes
       are org-scoped, and a hand-built path 404s in a way no endpoint test can
       see. */
    var host = pick.closest("[data-choice-url]");
    var choiceUrl = host && host.dataset.choiceUrl;
    var id = pick.dataset.id || (pick.closest("[data-id]") || {}).dataset.id;
    if (!choiceUrl || !id) return;

    var body = new URLSearchParams();
    body.set("node_id", id);
    fetch(choiceUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-CSRFToken": cookie("csrftoken"),
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: body.toString(),
    }).then(function (res) {
      if (!res.ok) {
        /* A refusal here is usually the lock: something already hangs off the
           current answer, so re-answering would re-read all of it as the
           result of a decision that never produced it. */
        if (window.showToast) window.showToast("Couldn't record that choice.", "err");
        return;
      }
      /* Skip past our own write -- this is a fetch, so live.js never sees the
         htmx event it usually adopts the cursor from. */
      if (window.__liveAdoptCursor) window.__liveAdoptCursor(res.headers.get("X-Live-Cursor"));
      /* The spine is server-rendered per row, so redraw it from the server
         rather than guessing here: the answer changes a question's state, its
         chosen row, its fold, and whether it is locked, all at once. */
      if (window.htmx) window.htmx.ajax("GET", location.pathname + location.search,
                                        { target: "#main-content", select: "#main-content" });
      else location.reload();
    }).catch(function () {
      if (window.showToast) window.showToast("Couldn't reach the server.", "err");
    });
  });

  /* The map starts closed. Reading the record is the common case, and opening
     the stage costs a measure-and-place pass nobody asked for. */
  var toggle = document.querySelector("[data-view-toggle]");
  var slot = document.querySelector("[data-graph-slot]");
  if (toggle && slot) {
    slot.hidden = true;
    toggle.addEventListener("click", function () {
      var open = toggle.getAttribute("aria-pressed") === "true";
      toggle.setAttribute("aria-pressed", open ? "false" : "true");
      slot.hidden = open;
      /* The stage was hidden until this instant, so brainstorm.js measured it
         at zero. Re-fitting is the entire correction: layout() never reads the
         stage, and the cards are a fixed width. */
      if (!open && window.__canvas) window.__canvas.fit();
    });
  }

  /* A canvas born mid-session lands inside a hidden slot, and stays hidden on
     purpose. The spine grows at the same moment, and that is where the reader
     is looking -- yanking the map open would move the page under them. */
})();
