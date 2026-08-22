/* The decision record's controls: choosing an option, and the map toggle.

   Everything here is delegated on `document` and guarded by a sentinel,
   because this file is loaded from _spine.html which renders INSIDE
   .detail-body -- the hx-target of Reopen, Restore, Ship, the spec editor, the
   constraints editor and every bite edit. htmx re-creates and evaluates script
   tags in swapped content, so without the sentinel each swap would stack
   another listener and one "Choose this" click would fire N irreversible
   POSTs. */
(function () {
  if (window.__spine) return;
  window.__spine = true;

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
    var id = pick.dataset.id;
    if (!choiceUrl || !id) return;

    pick.disabled = true;
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
        pick.disabled = false;
        /* Show the server's own words. A refusal here is nearly always the
           lock, and its message says WHY and what to do instead (start a new
           slice) -- swallowing that for a generic toast turns a rule being
           taught into a button that mysteriously fails. */
        return res.text().then(function (why) {
          if (window.showToast) window.showToast(why.trim() || "Couldn't record that choice.", "err");
        });
      }
      /* Skip past our own write -- this is a fetch, so live.js never sees the
         htmx event it usually adopts the cursor from. */
      if (window.__liveAdoptCursor) window.__liveAdoptCursor(res.headers.get("X-Live-Cursor"));
      /* Redraw from the server: one answer changes the question's state, its
         chosen row, its fold and whether it is locked, all at once. */
      if (window.__liveRefreshSpine) window.__liveRefreshSpine();
      else location.reload();
    }).catch(function () {
      pick.disabled = false;
      if (window.showToast) window.showToast("Couldn't reach the server.", "err");
    });
  });

  /* The map is a second opinion on the same record. It starts closed -- the
     default lives in CSS, not here, so it survives a swap and never flashes
     open before this file runs. */
  document.addEventListener("click", function (e) {
    var toggle = e.target.closest("[data-view-toggle]");
    if (!toggle) return;
    var slot = document.querySelector("[data-graph-slot]");
    if (!slot) return;
    var open = toggle.getAttribute("aria-pressed") === "true";
    toggle.setAttribute("aria-pressed", open ? "false" : "true");
    slot.classList.toggle("is-open", !open);
    /* The stage was display:none until this instant, so brainstorm.js measured
       it at zero. Re-fitting is the entire correction: layout() never reads the
       stage, and the cards are a fixed width. */
    if (!open && window.__canvas) window.__canvas.fit();
  });
})();
