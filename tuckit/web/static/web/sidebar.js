/* Sidebar drag-to-resize. Adjusts the --sidebar-w custom property live while
   dragging (or via arrow keys when the handle is focused), clamps to
   [MIN, MAX], and persists the result to localStorage["sidebar-width"]. The
   pre-paint script in base.html restores that value before first paint. */
(function () {
  var MIN = 180, MAX = 420, STEP = 16;
  var root = document.documentElement;
  var handle = document.querySelector(".side-resize");
  var sidebar = document.querySelector(".sidebar");
  if (!handle || !sidebar) return;

  function clamp(w) { return Math.max(MIN, Math.min(MAX, w)); }

  function currentWidth() {
    var stored = parseInt(localStorage.getItem("sidebar-width"), 10);
    if (stored >= MIN && stored <= MAX) return stored;
    return 220;
  }

  function apply(w, persist) {
    root.style.setProperty("--sidebar-w", w + "px");
    handle.setAttribute("aria-valuenow", String(w));
    if (persist) localStorage.setItem("sidebar-width", String(w));
  }

  var dragging = false;

  handle.addEventListener("pointerdown", function (e) {
    dragging = true;
    root.classList.add("resizing");
    handle.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  handle.addEventListener("pointermove", function (e) {
    if (!dragging) return;
    var left = sidebar.getBoundingClientRect().left;
    apply(clamp(Math.round(e.clientX - left)), false);
  });

  function endDrag(e) {
    if (!dragging) return;
    dragging = false;
    root.classList.remove("resizing");
    if (handle.hasPointerCapture(e.pointerId)) handle.releasePointerCapture(e.pointerId);
    var w = parseInt(getComputedStyle(root).getPropertyValue("--sidebar-w"), 10);
    if (w) localStorage.setItem("sidebar-width", String(w));
  }
  handle.addEventListener("pointerup", endDrag);
  handle.addEventListener("pointercancel", endDrag);

  handle.addEventListener("keydown", function (e) {
    if (e.key === "ArrowLeft") { apply(clamp(currentWidth() - STEP), true); e.preventDefault(); }
    else if (e.key === "ArrowRight") { apply(clamp(currentWidth() + STEP), true); e.preventDefault(); }
  });
})();
