// By state map on vote pages: fetches the US shapes (scripts/build_vote_map.py)
// and fills each House district, or each senator's side of a state, with the
// member's mark. The seats come from the page (Yan.state_map). Hovering or
// tapping a shape names its members in the caption under the map.
(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";

  function el(name, attrs, parent) {
    var node = document.createElementNS(NS, name);
    Object.keys(attrs).forEach(function (k) { if (attrs[k] !== "") node.setAttribute(k, attrs[k]); });
    parent.appendChild(node);
    return node;
  }

  // One shape per member: the whole seat in the House; side-by-side vertical
  // slices of the state in the Senate, two per state even if only one voted.
  function drawSeat(svg, layer, key, d, seat, slices) {
    var marks = seat ? seat.marks.slice() : [];
    while (marks.length < slices) marks.push("none");
    var g = el("g", { "class": "seat", "data-title": seat ? seat.title : "" }, layer);
    if (marks.length === 1) {
      el("path", { d: d, "class": marks[0] }, g);
      return;
    }
    // Measure the shape, then clip a copy of it to each slice of its width.
    var probe = el("path", { d: d }, g);
    var box = probe.getBBox();
    g.removeChild(probe);
    var defs = svg.querySelector("defs");
    marks.forEach(function (mark, i) {
      var id = "vmap-" + key + "-" + i;
      var clip = el("clipPath", { id: id }, defs);
      var w = box.width / marks.length;
      el("rect", { x: box.x + i * w, y: box.y - 1, width: w, height: box.height + 2 }, clip);
      el("path", { d: d, "class": mark, "clip-path": "url(#" + id + ")" }, g);
    });
  }

  function setUp(root) {
    var svg = root.querySelector("svg");
    var caption = root.querySelector("[data-caption]");
    var seats = JSON.parse(root.querySelector("[data-seats]").textContent);
    var house = root.getAttribute("data-chamber") === "house";

    fetch(root.getAttribute("data-src"))
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (map) {
        svg.setAttribute("viewBox", "0 0 " + map.width + " " + map.height);
        var shapes = el("g", { "class": "shapes" }, svg);
        var source = house ? map.districts : map.states;
        Object.keys(source).forEach(function (key) {
          drawSeat(svg, shapes, key, source[key], seats[key], house ? 1 : 2);
        });
        // State lines on top, so each state reads as one even when split.
        var lines = el("g", { "class": "states" }, svg);
        Object.keys(map.states).forEach(function (s) { el("path", { d: map.states[s] }, lines); });
        root.classList.add("ready");
      })
      .catch(function () { root.hidden = true; });

    var current = null;
    function show(seat) {
      if (current) current.classList.remove("on");
      current = seat;
      if (seat) seat.classList.add("on");
      caption.textContent = seat ? seat.getAttribute("data-title") || "No member recorded" : " ";
    }
    function seatAt(target) { return target.closest ? target.closest(".seat") : null; }
    svg.addEventListener("mouseover", function (e) { show(seatAt(e.target)); });
    svg.addEventListener("mouseleave", function () { show(null); });
    svg.addEventListener("click", function (e) { show(seatAt(e.target)); });
  }

  document.querySelectorAll("[data-vmap]").forEach(setUp);
})();
