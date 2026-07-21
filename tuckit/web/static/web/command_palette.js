/* Cmd+K palette. Rows are rendered server-side with data-label; this filters
   them client-side, supports up/down/enter, and clicks the active row.
   No backend — every row is a link or a local action.

   The active row is published to assistive tech via aria-activedescendant plus
   a live result count. Without them the palette was silent to a screen reader:
   typing changed which rows were display:none and which one was highlighted,
   and none of that is observable without ARIA (WCAG 4.1.2 / 4.1.3). */
function commandPalette() {
  return {
    q: "",
    active: 0,
    opener: null,
    rows() {
      return Array.prototype.slice.call(this.$refs.list.querySelectorAll("[data-label]"));
    },
    visible() {
      var q = this.q.trim().toLowerCase();
      return this.rows().filter(function (r) {
        return !q || r.dataset.label.toLowerCase().indexOf(q) !== -1;
      });
    },
    open() {
      this.opener = document.activeElement;
      this.q = "";
      this.active = 0;
      this.$nextTick(function () {
        this.filter();
        this.$refs.search.focus();
      }.bind(this));
    },
    filter() {
      var vis = this.visible();
      this.rows().forEach(function (r) { r.style.display = "none"; });
      vis.forEach(function (r) { r.style.display = ""; });
      if (this.active >= vis.length) this.active = Math.max(0, vis.length - 1);
      this.highlight(vis);
    },
    highlight(vis) {
      var list = vis || this.visible();
      this.rows().forEach(function (r) {
        r.classList.remove("cmdk-row--active");
        r.setAttribute("aria-selected", "false");
      });
      var cur = list[this.active];
      if (cur) {
        cur.classList.add("cmdk-row--active");
        cur.setAttribute("aria-selected", "true");
        if (!cur.id) cur.id = "cmdk-opt-" + Math.abs(this.rows().indexOf(cur));
        this.$refs.search.setAttribute("aria-activedescendant", cur.id);
      } else {
        this.$refs.search.removeAttribute("aria-activedescendant");
      }
      this.announce(list.length);
    },
    /* Announced politely so it does not interrupt each keystroke's echo. */
    announce(n) {
      if (!this.$refs.status) return;
      this.$refs.status.textContent = n
        ? n + (n === 1 ? " result" : " results")
        : "No results";
    },
    move(d) {
      var vis = this.visible();
      if (!vis.length) return;
      this.active = (this.active + d + vis.length) % vis.length;
      this.highlight(vis);
      vis[this.active].scrollIntoView({ block: "nearest" });
    },
    choose() {
      var vis = this.visible();
      if (vis[this.active]) vis[this.active].click();
    },
    /* Tab trap while the palette is open — mirrors trapFocus/trapPanel in
       base.html, scoped to the search input plus the currently visible rows. */
    trap(e) {
      var f = [this.$refs.search].concat(this.visible());
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    },
  };
}
