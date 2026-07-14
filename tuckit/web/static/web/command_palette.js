/* Cmd+K palette. Rows are rendered server-side with data-label; this filters
   them client-side, supports up/down/enter, and clicks the active row.
   No backend — every row is a link or a local action. */
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
      this.rows().forEach(function (r) { r.classList.remove("cmdk-row--active"); });
      if (list[this.active]) list[this.active].classList.add("cmdk-row--active");
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
