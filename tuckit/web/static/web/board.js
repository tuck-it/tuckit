// Board view drag-and-drop: initializes SortableJS on each board column's
// card list and POSTs the resulting position to web:slice_move on drop.
// This file is ours (not vendored) — see web/static/web/vendor/sortable.min.js
// for the third-party library it depends on.
(function () {
  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : null;
  }

  function moveUrl(sliceId) {
    return "/slices/" + sliceId + "/move";
  }

  function initBoard() {
    const lists = document.querySelectorAll(".board-col-cards");
    if (!lists.length) return;

    lists.forEach(function (list) {
      Sortable.create(list, {
        group: "board",
        animation: 150,
        onEnd: function (evt) {
          const item = evt.item;
          const sliceId = item.getAttribute("data-slice-id");
          const targetCol = evt.to.closest(".board-col");
          if (!sliceId || !targetCol) return;

          const status = targetCol.getAttribute("data-status");
          const before = item.nextElementSibling;
          const after = item.previousElementSibling;

          const body = new URLSearchParams();
          body.set("status", status);
          if (before) body.set("before_id", before.getAttribute("data-slice-id"));
          if (after) body.set("after_id", after.getAttribute("data-slice-id"));

          fetch(moveUrl(sliceId), {
            method: "POST",
            headers: {
              "X-CSRFToken": getCookie("csrftoken"),
              "Content-Type": "application/x-www-form-urlencoded",
            },
            body: body.toString(),
          });
        },
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initBoard);
  } else {
    initBoard();
  }
})();
