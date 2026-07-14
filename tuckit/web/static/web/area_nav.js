// Sidebar Area drag-reorder: initializes SortableJS on #area-nav and POSTs the
// new position to web:area_reorder on drop. Re-initializes after htmx swaps the
// list (e.g. OOB swap on area create), since the old Sortable instance is bound
// to a replaced DOM node. Depends on the vendored SortableJS (see base.html).
(function () {
  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : null;
  }

  let instance = null;

  function initAreaNav() {
    const nav = document.getElementById("area-nav");
    if (!nav) return;
    if (instance) { instance.destroy(); instance = null; }
    instance = Sortable.create(nav, {
      animation: 150,
      draggable: ".area-item",
      filter: ".area-act, .area-menu-item, .area-rename-input",  // don't start a drag from action buttons/input
      onEnd: function (evt) {
        const item = evt.item;
        const areaId = item.getAttribute("data-area-id");
        if (!areaId) return;
        const before = item.nextElementSibling;
        const after = item.previousElementSibling;

        const body = new URLSearchParams();
        if (before && before.getAttribute("data-area-id")) {
          body.set("before_id", before.getAttribute("data-area-id"));
        }
        if (after && after.getAttribute("data-area-id")) {
          body.set("after_id", after.getAttribute("data-area-id"));
        }

        fetch("/areas/" + areaId + "/reorder", {
          method: "POST",
          headers: {
            "X-CSRFToken": getCookie("csrftoken"),
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: body.toString(),
        });
      },
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAreaNav);
  } else {
    initAreaNav();
  }

  // The sidebar Areas list is OOB-swapped on area create; re-bind Sortable to
  // the fresh #area-nav node when THAT swap lands. Listen for the out-of-band
  // swap event specifically and confirm the swapped element is #area-nav — other
  // OOB swaps (capture's toast/count/triage list) must not trigger a re-init,
  // and a page-wide htmx:afterSwap listener would waste work and could tear down
  // a drag already in progress.
  document.body.addEventListener("htmx:oobAfterSwap", function (evt) {
    var t = (evt.detail && evt.detail.target) || evt.target;
    if (t && t.id === "area-nav") initAreaNav();
  });
})();
