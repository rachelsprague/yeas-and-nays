// District map on /find/: zoom (buttons, wheel, pinch), pan (drag), and a
// card naming the chosen district's representative and senators. Without JS
// the map still shows, and each district links to its representative.
(function () {
  "use strict";

  var MAX_ZOOM = 40;
  var DRAG_PX = 5; // movement below this is a click, not a pan

  function setUp(root) {
    var svg = root.querySelector("svg");
    var card = root.querySelector("[data-card]");
    var people = JSON.parse(root.querySelector("[data-people]").textContent);
    var full = svg.viewBox.baseVal;
    var W = full.width, H = full.height;
    var view = { x: 0, y: 0, w: W, h: H };
    var selected = null;

    // Map units per screen pixel, so labels and dots keep one size at any zoom
    // (--u in site.css), and the zoom level, which decides which cities show.
    var ZOOM_LEVELS = [["z2", 2.5], ["z3", 6]];
    function apply() {
      svg.setAttribute("viewBox", [view.x, view.y, view.w, view.h].join(" "));
      var px = svg.getBoundingClientRect().width;
      if (px) svg.style.setProperty("--u", view.w / px);
      ZOOM_LEVELS.forEach(function (z) { svg.classList.toggle(z[0], W / view.w >= z[1]); });
    }
    apply();
    window.addEventListener("resize", apply);

    // Keep the view inside the map and between whole-map and MAX_ZOOM.
    function clamp() {
      view.w = Math.min(W, Math.max(W / MAX_ZOOM, view.w));
      view.h = view.w * H / W;
      view.x = Math.min(W - view.w, Math.max(0, view.x));
      view.y = Math.min(H - view.h, Math.max(0, view.y));
    }

    // Map coordinates under a point on screen.
    function toMap(clientX, clientY) {
      var r = svg.getBoundingClientRect();
      return { x: view.x + (clientX - r.left) / r.width * view.w,
               y: view.y + (clientY - r.top) / r.height * view.h };
    }

    // Zoom by factor (>1 zooms in), keeping the map point at (clientX, clientY) still.
    function zoomAt(factor, clientX, clientY) {
      var p = toMap(clientX, clientY);
      var w = view.w / factor;
      w = Math.min(W, Math.max(W / MAX_ZOOM, w));
      var k = w / view.w;
      view.x = p.x - (p.x - view.x) * k;
      view.y = p.y - (p.y - view.y) * k;
      view.w = w;
      clamp();
      apply();
    }

    function zoomCenter(factor) {
      var r = svg.getBoundingClientRect();
      zoomAt(factor, r.left + r.width / 2, r.top + r.height / 2);
    }

    root.querySelectorAll("[data-zoom]").forEach(function (b) {
      b.addEventListener("click", function () {
        if (b.dataset.zoom === "in") zoomCenter(2);
        else if (b.dataset.zoom === "out") zoomCenter(0.5);
        else { view = { x: 0, y: 0, w: W, h: H }; apply(); }
      });
    });

    // A plain scroll scrolls the page. Trackpad pinches arrive as wheel events
    // with ctrlKey set, so Ctrl/⌘ + scroll and pinching zoom the map.
    svg.addEventListener("wheel", function (e) {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      zoomAt(Math.pow(2, -e.deltaY / (e.ctrlKey ? 100 : 300)), e.clientX, e.clientY);
    }, { passive: false });

    // Drag to pan with one pointer, pinch to zoom with two.
    var pointers = new Map();
    var dragged = false;
    var start = null;

    svg.addEventListener("pointerdown", function (e) {
      if (e.pointerType === "mouse" && e.button !== 0) return; // right-click, middle button
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size === 1) {
        dragged = false;
        start = { x: e.clientX, y: e.clientY };
      }
    });

    svg.addEventListener("pointermove", function (e) {
      var prev = pointers.get(e.pointerId);
      if (!prev) return;
      var r = svg.getBoundingClientRect();
      if (pointers.size === 1) {
        if (!dragged && Math.hypot(e.clientX - start.x, e.clientY - start.y) < DRAG_PX) return;
        if (!dragged) svg.setPointerCapture(e.pointerId);
        dragged = true;
        view.x -= (e.clientX - prev.x) / r.width * view.w;
        view.y -= (e.clientY - prev.y) / r.height * view.h;
        clamp();
        apply();
      } else if (pointers.size === 2) {
        dragged = true;
        var other = Array.from(pointers.entries()).find(function (kv) { return kv[0] !== e.pointerId; })[1];
        var before = Math.hypot(prev.x - other.x, prev.y - other.y);
        var after = Math.hypot(e.clientX - other.x, e.clientY - other.y);
        if (before > 0) zoomAt(after / before, (e.clientX + other.x) / 2, (e.clientY + other.y) / 2);
      }
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    });

    // A press can end where the svg never hears it (released outside the map,
    // or a context menu opened by Ctrl-click); drop it so it can't act as a
    // second finger on the next drag.
    function release(e) { pointers.delete(e.pointerId); }
    svg.addEventListener("pointerup", release);
    svg.addEventListener("pointercancel", release);
    // Only the svg's own capture: on touch the district under the finger holds
    // the pointer first, and its loss (when the svg takes over) bubbles up here.
    svg.addEventListener("lostpointercapture", function (e) { if (e.target === svg) release(e); });
    svg.addEventListener("pointerleave", function (e) { if (!svg.hasPointerCapture(e.pointerId)) release(e); });
    svg.addEventListener("contextmenu", function () { pointers.clear(); });

    // A click (not the end of a drag) chooses a district instead of following its link.
    svg.addEventListener("click", function (e) {
      e.preventDefault();
      if (dragged) return;
      var link = e.target.closest("a[data-seat]");
      if (link) choose(link);
    });

    function choose(link) {
      if (selected) selected.classList.remove("on");
      selected = link;
      link.classList.add("on");
      show(people[link.dataset.seat]);
    }

    // Builds the card with text nodes only; names never become markup.
    function show(p) {
      card.textContent = "";
      card.appendChild(el("h2", "kicker", p.where));
      if (p.places.length) {
        var more = p.more_places ? ", and " + p.more_places + " more" : "";
        var places = el("div", "dmap-row");
        places.appendChild(el("span", "kicker soft", "Cities and towns, all or part"));
        places.appendChild(el("span", "small", p.places.join(", ") + more));
        card.appendChild(places);
      }
      card.appendChild(row("Representative", p.rep ? [p.rep] : [], "Seat vacant"));
      card.appendChild(row("Senators", p.senators, "None listed"));
      // On a phone the card sits below the map; bring it into view.
      var r = card.getBoundingClientRect();
      if (r.top < 0 || r.bottom > window.innerHeight) card.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    function row(label, list, none) {
      var div = el("div", "dmap-row");
      div.appendChild(el("span", "kicker soft", label));
      if (!list.length) div.appendChild(el("span", "soft", none));
      list.forEach(function (m) {
        var a = el("a", "dmap-member", m.name);
        // Built here from the ID, so the link can only ever be a member page.
        a.href = "/members/" + encodeURIComponent(m.id) + "/";
        a.appendChild(el("span", "soft", " · " + m.party));
        div.appendChild(a);
      });
      return div;
    }

    function el(tag, cls, text) {
      var n = document.createElement(tag);
      if (cls) n.className = cls;
      if (text) n.textContent = text;
      return n;
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-dmap]").forEach(setUp);
  });
})();
