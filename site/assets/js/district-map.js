// District map on /find/: zoom (buttons, wheel, pinch), pan (drag), a card
// naming the chosen district's representative and senators, and ZIP code
// search. Without JS the map still shows, and each district links to its
// representative.
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
    // Each city label with its dot's map point, to find the ones in a chosen district.
    var cities = Array.prototype.map.call(svg.querySelectorAll(".city"), function (c) {
      var m = c.transform.baseVal.consolidate().matrix;
      return { el: c, point: { x: m.e, y: m.f } };
    });

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
      // Labels on the accent fill switch to its text color, so they stay readable.
      var path = link.querySelector("path");
      cities.forEach(function (c) {
        c.el.classList.toggle("in", !!path.isPointInFill && path.isPointInFill(c.point));
      });
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

    // ZIP code search (form[data-zip] names the lookup, fetched on the first
    // search). A ZIP code split between districts highlights them all and
    // lets the reader choose; it never picks one.
    var zipForm = document.querySelector("form[data-zip]");
    if (zipForm) setUpZip(zipForm, document.querySelector("[data-zip-note]"));

    function setUpZip(form, note) {
      var input = form.querySelector("input");
      var cardStart = card.innerHTML;
      var bySeat = {};
      svg.querySelectorAll("a[data-seat]").forEach(function (a) { bySeat[a.dataset.seat] = a; });
      var lookup = null;

      form.addEventListener("submit", function (e) {
        e.preventDefault();
        var zip = input.value.trim();
        if (!/^\d{5}$/.test(zip)) { say(["Enter a five-digit ZIP code."]); return; }
        if (!lookup) {
          lookup = fetch(form.dataset.zip)
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(index);
        }
        lookup.then(function (zips) { found(zip, zips[zip]); }, function () {
          lookup = null; // try again on the next search
          say(["The ZIP code lookup didn't load. Try again, or search by name or state below."]);
        });
      });

      // {zip: [seat, ...]} from the file's {seat: "zip zip ..."}; [] where no member votes.
      function index(doc) {
        var zips = {};
        Object.keys(doc.districts).forEach(function (seat) {
          doc.districts[seat].split(" ").forEach(function (z) { (zips[z] = zips[z] || []).push(seat); });
        });
        doc.no_voting_member.split(" ").forEach(function (z) { if (z && !zips[z]) zips[z] = []; });
        return zips;
      }

      function found(zip, seats) {
        svg.querySelectorAll("a.zip").forEach(function (a) { a.classList.remove("zip"); });
        var links = (seats || []).map(function (s) { return bySeat[s]; }).filter(Boolean);
        if (links.length === 1) {
          zoomTo(links);
          choose(links[0]);
          say(["ZIP code " + zip + " is in " + people[links[0].dataset.seat].where + "."]);
          return;
        }
        // Anything else leaves no district chosen, so an earlier one's card doesn't linger.
        if (selected) selected.classList.remove("on");
        selected = null;
        cities.forEach(function (c) { c.el.classList.remove("in"); });
        card.innerHTML = cardStart;
        if (seats && !seats.length) {
          say(["ZIP code " + zip + " is in the District of Columbia or a U.S. territory. Its member of the House can't vote on the floor, so it isn't on this map."]);
        } else if (!links.length) {
          say(["No ZIP Code Tabulation Area matches " + zip + ". Some ZIP codes, such as those for PO boxes, have none. ",
               byAddress("Find your representative by address at house.gov"), ", or search by name or state below."]);
        } else {
          links.forEach(function (a) { a.classList.add("zip"); });
          zoomTo(links);
          var choices = el("div", "zipseats");
          links.forEach(function (a) {
            var b = el("button", "button", people[a.dataset.seat].where);
            b.type = "button";
            b.addEventListener("click", function () { choose(a); });
            choices.appendChild(b);
          });
          say(["ZIP code " + zip + " is split between " + links.length + " districts. Choose yours below or on the map. ",
               byAddress("Your address at house.gov"), " shows which one is yours.", choices]);
        }
      }

      // The note under the form, from strings (as text) and nodes.
      function say(parts) {
        note.textContent = "";
        parts.forEach(function (p) { note.appendChild(typeof p === "string" ? document.createTextNode(p) : p); });
        note.hidden = false;
      }
    }

    function byAddress(text) {
      var a = el("a", null, text);
      a.href = "https://www.house.gov/representatives/find-your-representative";
      return a;
    }

    // Fits the view to the districts' outlines, with a margin.
    function zoomTo(links) {
      var boxes = links.map(function (a) { return a.querySelector("path"); })
        .filter(function (p) { return p.getBBox; })
        .map(function (p) { return p.getBBox(); });
      if (!boxes.length) return;
      var x0 = Math.min.apply(null, boxes.map(function (b) { return b.x; }));
      var y0 = Math.min.apply(null, boxes.map(function (b) { return b.y; }));
      var x1 = Math.max.apply(null, boxes.map(function (b) { return b.x + b.width; }));
      var y1 = Math.max.apply(null, boxes.map(function (b) { return b.y + b.height; }));
      view.w = Math.min(W, Math.max(W / MAX_ZOOM, Math.max(x1 - x0, (y1 - y0) * W / H) * 1.5));
      view.h = view.w * H / W;
      view.x = (x0 + x1 - view.w) / 2;
      view.y = (y0 + y1 - view.h) / 2;
      clamp();
      apply();
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-dmap]").forEach(setUp);
  });
})();
