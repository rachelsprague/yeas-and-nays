// Pinned filter bar: once the reader scrolls past a long list's filters
// (marked [data-pinbar] inside a [data-filter-scope]), a slim bar fixed to the
// top of the screen keeps them in reach until the list ends. The filters stay
// where they are; the bar holds copies kept in step with them, so filters.js
// sees every change on the originals. Without JS there's no bar.
//
// Phones: the name search, a "Filters" button (with the number of filters
// set) that opens the other controls, and a "Showing x of n" line. From 760px
// every control shows in one row and the button is hidden (site.css).
//
// The bar is fixed rather than sticky, so showing or hiding it never moves
// the list under the reader. Load after filters.js: its listeners must run
// first so the count is current when the bar copies it.
(function () {
  "use strict";

  // The text of a control's <label for>, used to name its copy.
  function labelOf(scope, c) {
    var l = c.id && scope.querySelector('label[for="' + c.id + '"]');
    return l ? l.textContent.trim() : c.getAttribute("aria-label") || "";
  }

  function defaultValue(select) {
    for (var i = 0; i < select.options.length; i++) {
      if (select.options[i].defaultSelected) return select.options[i].value;
    }
    return select.options.length ? select.options[0].value : "";
  }

  // A copy of a control with no id or name (so it neither collides nor gets
  // submitted), forwarding its changes to the original.
  function copyControl(c, name) {
    var k = c.cloneNode(true);
    k.removeAttribute("id");
    k.removeAttribute("name");
    k.removeAttribute("data-filter");
    k.setAttribute("aria-label", name);
    k.value = c.value;
    var type = c.tagName === "INPUT" ? "input" : "change";
    k.addEventListener(type, function () {
      c.value = k.value;
      c.dispatchEvent(new Event(type, { bubbles: true }));
    });
    return k;
  }

  // A copy of a tab group whose buttons click the originals.
  function copyTabs(group) {
    var g = group.cloneNode(true);
    g.removeAttribute("id");
    g.classList.remove("js-only");
    var originals = group.querySelectorAll("button[data-tab]");
    g.querySelectorAll("button[data-tab]").forEach(function (b, i) {
      b.removeAttribute("data-tab");
      b.addEventListener("click", function () { originals[i].click(); });
    });
    return { el: g, originals: originals, copies: g.querySelectorAll("button") };
  }

  function setUp(source) {
    var scope = source.closest("[data-filter-scope]");
    if (!scope) return;
    var count = scope.querySelector("[data-count]");
    var search = source.querySelector("input[data-filter]");
    var selects = source.querySelectorAll("select[data-filter]");
    var groups = source.querySelectorAll(".tabs");
    if (!search) return;

    var bar = document.createElement("div");
    bar.className = "pinbar";
    bar.setAttribute("role", "group");
    bar.setAttribute("aria-label", "Filters");
    bar.hidden = true;
    var inner = document.createElement("div");
    inner.className = "pinbar-inner wrap";
    bar.appendChild(inner);

    var pairs = [];
    var searchCopy = copyControl(search, labelOf(scope, search));
    searchCopy.classList.add("pinbar-q");
    pairs.push([search, searchCopy]);
    inner.appendChild(searchCopy);

    var more = document.createElement("div");
    more.className = "pinbar-more";
    more.id = "pinbar-more-" + (setUp.n = (setUp.n || 0) + 1);

    var toggle = null;
    if (selects.length || groups.length) {
      toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "pinbar-toggle";
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-controls", more.id);
      toggle.textContent = "Filters";
      toggle.addEventListener("click", function () {
        var open = toggle.getAttribute("aria-expanded") !== "true";
        toggle.setAttribute("aria-expanded", String(open));
        // A class, not [hidden]: site.css hides [hidden] with !important,
        // and from 760px these controls always show.
        more.classList.toggle("is-open", open);
      });
      inner.appendChild(toggle);
    }

    var tabCopies = [];
    groups.forEach(function (group) {
      var t = copyTabs(group);
      tabCopies.push(t);
      more.appendChild(t.el);
    });
    selects.forEach(function (s) {
      var name = labelOf(scope, s);
      var label = document.createElement("label");
      var text = document.createElement("span");
      text.className = "kicker";
      text.textContent = name;
      var k = copyControl(s, name);
      label.appendChild(text);
      label.appendChild(k);
      pairs.push([s, k]);
      more.appendChild(label);
    });
    inner.appendChild(more);

    // Copied, not live: the original count keeps aria-live, so a screen
    // reader hears each change once.
    var line = document.createElement("p");
    line.className = "pinbar-count small muted nums";
    line.setAttribute("aria-hidden", "true");
    inner.appendChild(line);

    source.after(bar);

    // Copy values, pressed tabs, the count and what's set from the originals.
    // An event from a copy itself is skipped for values: a select fires
    // "input" before "change", and copying then would undo the choice before
    // it reached the original. Its forwarded event syncs the rest.
    function refresh(e) {
      if (!e || !bar.contains(e.target)) {
        pairs.forEach(function (p) { if (p[1] !== document.activeElement) p[1].value = p[0].value; });
      }
      var parts = [];
      tabCopies.forEach(function (t) {
        t.originals.forEach(function (o, i) {
          var pressed = o.getAttribute("aria-pressed") === "true";
          t.copies[i].setAttribute("aria-pressed", String(pressed));
          if (pressed && o.dataset.value !== "all") parts.push(o.textContent.trim());
        });
      });
      selects.forEach(function (s) {
        if (s.value !== defaultValue(s)) parts.push(s.options[s.selectedIndex].textContent.trim());
      });
      if (toggle) toggle.textContent = parts.length ? "Filters (" + parts.length + ")" : "Filters";
      line.textContent = [count ? count.textContent : ""].concat(parts).filter(Boolean).join(" · ");
    }

    // Shown once the filters are above the top of the screen; as the list's
    // end comes up, the bar slides up with it, as a sticky one would, and
    // hides once the end is past. Kept in full while focus is in the bar: a
    // search that leaves a few rows shortens the page, and hiding the box
    // being typed in would close a phone's keyboard.
    var queued = false;
    function place() {
      queued = false;
      var above = source.getBoundingClientRect().bottom < 0;
      var end = scope.getBoundingClientRect().bottom;
      var focused = !bar.hidden && bar.contains(document.activeElement);
      var show = (above && end > 0) || focused;
      if (bar.hidden === show) bar.hidden = !show;
      var h = bar.offsetHeight;
      bar.style.transform = show && !focused && end < h ? "translateY(" + (end - h) + "px)" : "";
    }
    function queue() {
      if (!queued) { queued = true; window.requestAnimationFrame(place); }
    }

    scope.addEventListener("input", refresh);
    scope.addEventListener("change", refresh);
    scope.addEventListener("click", refresh);
    window.addEventListener("scroll", queue, { passive: true });
    window.addEventListener("resize", queue);
    bar.addEventListener("focusout", queue);
    refresh();
    place();
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-pinbar]").forEach(setUp);
  });
})();
