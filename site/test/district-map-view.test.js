// Tests for assets/js/district-map.js's zoom, pan and pinch, and the city
// labels' recolor in the chosen district: run with `make jstest` (node --test).
// jsdom has no layout or SVG geometry, so the svg is stubbed as 1000 x 500
// screen pixels at the page's corner (one map unit per pixel at full view), a
// city label's point comes from its data-x and data-y, and a district contains
// the points in the 10 x 10 square its path starts from.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const SCRIPT = fs.readFileSync(path.join(__dirname, "..", "assets", "js", "district-map.js"), "utf8");

const PEOPLE = {
  "KY-1": { where: "Kentucky, 1st District", places: [], more_places: 0, rep: { name: "Rep One", id: "A000001", party: "R" }, senators: [] },
  "KY-2": { where: "Kentucky, 2nd District", places: [], more_places: 0, rep: { name: "Rep Two", id: "A000002", party: "D" }, senators: [] },
};

const PAGE = `
  <section data-dmap>
    <button data-zoom="in">+</button><button data-zoom="out">-</button><button data-zoom="reset">Reset</button>
    <svg viewBox="0 0 1000 500">
      <g class="districts">
        <a href="/m/1/" data-seat="KY-1"><path d="M0 0l10 0 0 10z"/></a>
        <a href="/m/2/" data-seat="KY-2"><path d="M10 0l10 0 0 10z"/></a>
      </g>
      <g class="cities">
        <g class="city" data-x="5" data-y="5"></g>
        <g class="city" data-x="15" data-y="5"></g>
        <g class="city" data-x="500" data-y="400"></g>
      </g>
    </svg>
    <div data-card><p class="soft">Choose a district on the map.</p></div>
    <script type="application/json" data-people>${JSON.stringify(PEOPLE)}</script>
  </section>`;

async function load() {
  const dom = new JSDOM(`<!doctype html><body>${PAGE}</body>`, {
    url: "https://example.test/find/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  const proto = window.SVGElement.prototype;
  proto.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 500, right: 1000, bottom: 500 });
  proto.setPointerCapture = () => {};
  proto.hasPointerCapture = () => false;
  Object.defineProperty(proto, "transform", {
    get() {
      const e = +this.dataset.x, f = +this.dataset.y;
      return { baseVal: { consolidate: () => ({ matrix: { e, f } }) } };
    },
  });
  proto.isPointInFill = function (p) {
    const [x, y] = this.getAttribute("d").match(/^M(\d+) (\d+)/).slice(1).map(Number);
    return p.x >= x && p.x <= x + 10 && p.y >= y && p.y <= y + 10;
  };
  window.Element.prototype.scrollIntoView = () => {};
  const ready = new Promise((resolve) => window.document.addEventListener("DOMContentLoaded", resolve));
  window.eval(SCRIPT);
  await ready;

  const doc = window.document;
  const svg = doc.querySelector("svg");
  const map = {
    window, svg,
    view: () => svg.getAttribute("viewBox").split(" ").map(Number),
    button: (which) => doc.querySelector(`[data-zoom=${which}]`).click(),
    seat: (s) => doc.querySelector(`a[data-seat="${s}"]`),
    cities: () => [...doc.querySelectorAll(".city")],
    pointer(type, init, target = svg) {
      const e = new window.PointerEvent(type, { bubbles: true, cancelable: true, pointerType: "touch", ...init });
      target.dispatchEvent(e);
      return e;
    },
    click(target, init = {}) {
      return target.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true, ...init }));
    },
    wheel(init) {
      const e = new window.WheelEvent("wheel", { bubbles: true, cancelable: true, ...init });
      svg.dispatchEvent(e);
      return e;
    },
  };
  return map;
}

test("the zoom buttons halve and double the view around its center, and reset restores it", async () => {
  const m = await load();
  m.button("in");
  assert.deepEqual(m.view(), [250, 125, 500, 250]);
  m.button("in");
  assert.deepEqual(m.view(), [375, 187.5, 250, 125]);
  m.button("out");
  assert.deepEqual(m.view(), [250, 125, 500, 250]);
  m.button("reset");
  assert.deepEqual(m.view(), [0, 0, 1000, 500]);
});

test("zooming out stops at the whole map, and zooming in at 40 times", async () => {
  const m = await load();
  m.button("out");
  assert.deepEqual(m.view(), [0, 0, 1000, 500]);
  for (let i = 0; i < 10; i++) m.button("in");
  assert.deepEqual(m.view(), [487.5, 243.75, 25, 12.5]);
});

test("the zoom class names the levels that decide which cities show", async () => {
  const m = await load();
  const has = (c) => m.svg.classList.contains(c);
  assert.deepEqual([has("z2"), has("z3")], [false, false]);
  m.button("in"); // 2x
  assert.deepEqual([has("z2"), has("z3")], [false, false]);
  m.button("in"); // 4x
  assert.deepEqual([has("z2"), has("z3")], [true, false]);
  m.button("in"); // 8x
  m.button("in");
  assert.deepEqual([has("z2"), has("z3")], [true, true]);
  m.button("reset");
  assert.deepEqual([has("z2"), has("z3")], [false, false]);
});

test("Ctrl or Command with the wheel zooms at the pointer; a plain wheel scrolls the page", async () => {
  const m = await load();
  assert.equal(m.wheel({ deltaY: -100, clientX: 200, clientY: 100 }).defaultPrevented, false);
  assert.deepEqual(m.view(), [0, 0, 1000, 500]);

  // A trackpad pinch (Ctrl set): 100 wheel units is a doubling. The map point under the pointer stays put.
  assert.equal(m.wheel({ deltaY: -100, ctrlKey: true, clientX: 200, clientY: 100 }).defaultPrevented, true);
  assert.deepEqual(m.view(), [100, 50, 500, 250]);

  m.button("reset");
  m.wheel({ deltaY: -300, metaKey: true, clientX: 200, clientY: 100 });
  assert.deepEqual(m.view(), [100, 50, 500, 250]);
});

test("dragging pans the map with the pointer, and stops at its edges", async () => {
  const m = await load();
  m.button("in"); // 500 x 250 at (250, 125)
  m.pointer("pointerdown", { pointerId: 1, clientX: 500, clientY: 250, isPrimary: true });
  m.pointer("pointermove", { pointerId: 1, clientX: 400, clientY: 200 });
  // 100 screen pixels is 50 map units at 2x; the map moves with the pointer.
  assert.deepEqual(m.view(), [300, 150, 500, 250]);
  m.pointer("pointermove", { pointerId: 1, clientX: -5000, clientY: -5000 });
  assert.deepEqual(m.view(), [500, 250, 500, 250]);
  m.pointer("pointerup", { pointerId: 1 });
  m.pointer("pointermove", { pointerId: 1, clientX: 0, clientY: 0 });
  assert.deepEqual(m.view(), [500, 250, 500, 250]);
});

test("a drag ends without choosing the district under it; a click or small wobble chooses it", async () => {
  const m = await load();
  const link = m.seat("KY-1");
  const path = link.querySelector("path");

  m.pointer("pointerdown", { pointerId: 1, clientX: 5, clientY: 5 }, path);
  m.pointer("pointermove", { pointerId: 1, clientX: 60, clientY: 5 });
  m.pointer("pointerup", { pointerId: 1 });
  assert.equal(m.click(path), false); // the link isn't followed
  assert.equal(link.classList.contains("on"), false);

  m.pointer("pointerdown", { pointerId: 2, clientX: 5, clientY: 5 }, path);
  m.pointer("pointermove", { pointerId: 2, clientX: 7, clientY: 6 }); // under 5px: still a click
  m.pointer("pointerup", { pointerId: 2 });
  m.click(path);
  assert.ok(link.classList.contains("on"));
  assert.deepEqual(m.view(), [0, 0, 1000, 500]);
});

test("a right-click press doesn't start a drag", async () => {
  const m = await load();
  m.button("in");
  m.pointer("pointerdown", { pointerId: 1, pointerType: "mouse", button: 2, clientX: 500, clientY: 250 });
  m.pointer("pointermove", { pointerId: 1, pointerType: "mouse", clientX: 400, clientY: 250 });
  assert.deepEqual(m.view(), [250, 125, 500, 250]);
});

test("two fingers pinch to zoom around their midpoint, and the drag that follows isn't a click", async () => {
  const m = await load();
  m.pointer("pointerdown", { pointerId: 1, clientX: 400, clientY: 250 });
  m.pointer("pointerdown", { pointerId: 2, clientX: 600, clientY: 250 });
  // The second finger moves from 200px to 400px away from the first: 2x, about (500, 250).
  m.pointer("pointermove", { pointerId: 2, clientX: 800, clientY: 250 });
  const [, , w] = m.view();
  assert.equal(w, 500);
  m.pointer("pointerup", { pointerId: 2 });
  m.pointer("pointerup", { pointerId: 1 });
  m.click(m.seat("KY-1").querySelector("path"));
  assert.equal(m.seat("KY-1").classList.contains("on"), false);
});

test("a finger lifted without the svg hearing it doesn't act as a second finger", async () => {
  const m = await load();
  m.pointer("pointerdown", { pointerId: 1, clientX: 400, clientY: 250 });
  m.pointer("pointercancel", { pointerId: 1 });
  m.pointer("pointerdown", { pointerId: 2, clientX: 500, clientY: 250 });
  m.pointer("pointermove", { pointerId: 2, clientX: 700, clientY: 250 });
  // One finger: a pan (clamped at the whole map, so no change), never a pinch.
  assert.deepEqual(m.view(), [0, 0, 1000, 500]);
});

test("city labels inside the chosen district switch to its text color; choosing another moves it", async () => {
  const m = await load();
  const [a, b, far] = m.cities();
  m.click(m.seat("KY-1").querySelector("path"));
  assert.deepEqual([a, b, far].map((c) => c.classList.contains("in")), [true, false, false]);
  m.click(m.seat("KY-2").querySelector("path"));
  assert.deepEqual([a, b, far].map((c) => c.classList.contains("in")), [false, true, false]);
});
