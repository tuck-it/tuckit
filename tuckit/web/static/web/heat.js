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

  /* Idiomorph re-syncs each <option selected> during a morph, which can force
     an Inbox row's Area <select> back to its unselected placeholder — but
     Alpine's `area` x-data value (the one driving the Promote button's
     :disabled) is not touched by that, since morph never fires input/change
     events. Left alone, the two disagree: Alpine still thinks an area is
     chosen (button enabled) while the DOM would submit area_id="". Re-derive
     Alpine's value from the DOM after every refresh so the button's enabled
     state always matches what the form would actually submit. */
  function resyncTicketAreaSelects() {
    document.querySelectorAll(".ticket-row select[name='area_id']").forEach(function (select) {
      var row = select.closest("[x-data]");
      var stack = row && row._x_dataStack;
      if (stack && stack[0]) stack[0].area = select.value;
    });
  }
  document.body.addEventListener("tuckit:live-refreshed", resyncTicketAreaSelects);

  /* Shape ④ exit. Idiomorph asks before removing a node; answering false keeps
     it for one animation, then removes it. Only items with a stable id are
     animated — anything else is structural markup whose removal is not a
     "thing leaving" the user should watch. */
  document.body.addEventListener("htmx:beforeSwap", function () {
    if (!window.Idiomorph) return;
    window.Idiomorph.defaults.callbacks.beforeNodeRemoved = function (node) {
      if (!node.dataset) return true;
      var tracked = node.dataset.sliceId || node.dataset.ticketId || node.dataset.areaId;
      if (!tracked || node.classList.contains("is-leaving")) return true;
      node.classList.add("is-leaving");
      setTimeout(function () { node.remove(); }, 200);
      return false;
    };
  });

  /* 서버는 .area-inbox를 항상 닫힌 채 렌더한다(열림은 클라이언트 선호다).
     그래서 morph의 속성 동기화를 그냥 두면 사용자가 연 스트립이 2초마다,
     즉 폴링마다 도로 접힌다. 폴링 후에 다시 열어주는 사후 복구도 가능하지만
     닫혔다 열리는 한 프레임이 남는다 — 아예 벗기지 않는 쪽이 옳다.
     보호 범위는 이 요소의 open 하나뿐이라, 나머지는 평소대로 morph된다. */
  document.body.addEventListener("htmx:beforeSwap", function () {
    if (!window.Idiomorph) return;
    window.Idiomorph.defaults.callbacks.beforeAttributeUpdated = function (name, node) {
      if (name !== "open") return true;
      return !(node.classList && node.classList.contains("area-inbox"));
    };
  });
})();
