// Show/hide rows that are already in the page. Without JS every row stays
// visible; this only narrows them.
//
// Inside a [data-filter-scope]:
//   [data-filter=key]          <input> (substring of data-key, case-insensitive)
//                              or <select> (exact match; "" means all)
//   button[data-tab=key][data-value=v]   tab group; "all" matches every row.
//                              A row matches if any of its space-separated
//                              data-{key} values equals v.
//   [data-row]                 a filterable row, carrying data-{key} attributes.
//                              Without a tab's data-{key}, a row ignores that
//                              tab; without a select's or search box's, it
//                              counts as "" and hides once that one is set.
//   [data-limit=n]             on a list: show at most n matching rows
//   [data-skip-when=key:v ...] on a row: hide while that tab is selected
//   [data-show-when=key:v]     shown only while that tab is selected
//   [data-count]               "Showing x of n {noun}" (data-noun); with
//                              data-count-of=key, n counts only rows whose
//                              data-{key} matches that select (current or
//                              former members), so it's not "x of all".
//   [data-empty]               shown when nothing matches
(function () {
  "use strict";

  function setUp(scope) {
    var controls = scope.querySelectorAll("[data-filter]");
    var tabs = scope.querySelectorAll("button[data-tab]");
    var rows = scope.querySelectorAll("[data-row]");
    var count = scope.querySelector("[data-count]");
    var empty = scope.querySelector("[data-empty]");
    var noun = count ? count.getAttribute("data-noun") || "" : "";
    var countOf = count && scope.querySelector('[data-filter="' + count.getAttribute("data-count-of") + '"]');
    var tabState = {};

    tabs.forEach(function (b) {
      if (b.getAttribute("aria-pressed") === "true") tabState[b.dataset.tab] = b.dataset.value;
    });

    function matches(row) {
      for (var i = 0; i < controls.length; i++) {
        var c = controls[i];
        var key = c.dataset.filter;
        var want = c.value.trim().toLowerCase();
        if (!want) continue;
        var have = (row.getAttribute("data-" + key) || "").toLowerCase();
        // Search boxes match a substring; selects match the whole value
        // ("Not Voting", "Johnson (LA)" contain spaces).
        if (c.tagName === "INPUT" ? have.indexOf(want) === -1 : have !== want) return false;
      }
      for (var tab in tabState) {
        var value = tabState[tab];
        if (value === "all") continue;
        var attr = row.getAttribute("data-" + tab);
        if (attr !== null && attr.split(" ").indexOf(value) === -1) return false;
      }
      var skip = row.getAttribute("data-skip-when");
      if (skip) {
        var pairs = skip.split(" ");
        for (var j = 0; j < pairs.length; j++) {
          var kv = pairs[j].split(":");
          if (tabState[kv[0]] === kv[1]) return false;
        }
      }
      return true;
    }

    function apply() {
      var shown = 0;
      var perList = new Map();
      rows.forEach(function (row) {
        var ok = matches(row);
        var list = row.closest("[data-limit]");
        if (ok && list) {
          var n = (perList.get(list) || 0) + 1;
          perList.set(list, n);
          if (n > Number(list.dataset.limit)) ok = false;
        }
        row.hidden = !ok;
        if (ok) shown++;
      });
      scope.querySelectorAll("[data-show-when]").forEach(function (el) {
        var kv = el.dataset.showWhen.split(":");
        el.hidden = tabState[kv[0]] !== kv[1];
      });
      if (count) {
        var total = rows.length;
        if (countOf) {
          total = 0;
          rows.forEach(function (row) {
            if (row.getAttribute("data-" + countOf.dataset.filter) === countOf.value) total++;
          });
        }
        count.textContent = shown === total
          ? total + " " + noun
          : "Showing " + shown + " of " + total + " " + noun;
      }
      if (empty) empty.hidden = shown !== 0;
    }

    controls.forEach(function (c) {
      c.addEventListener(c.tagName === "INPUT" ? "input" : "change", apply);
    });
    tabs.forEach(function (b) {
      b.addEventListener("click", function () {
        tabs.forEach(function (o) {
          if (o.dataset.tab === b.dataset.tab) o.setAttribute("aria-pressed", String(o === b));
        });
        tabState[b.dataset.tab] = b.dataset.value;
        apply();
      });
    });

    // Prefill from the query string, e.g. /members/?q=kentucky from the home page search.
    var params = new URLSearchParams(location.search);
    controls.forEach(function (c) {
      if (c.name && params.get(c.name)) c.value = params.get(c.name);
    });
    apply();
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-filter-scope]").forEach(setUp);
  });
})();
