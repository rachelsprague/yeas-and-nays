// Tests for assets/js/activity.js: run with `make jstest` (node --test).
// Each test loads the real script into a jsdom page built from markup shaped
// like /activity/. jsdom has no layout, so scrollIntoView is a counter.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const SCRIPT = fs.readFileSync(path.join(__dirname, "..", "assets", "js", "activity.js"), "utf8");

// x is the week's column in the chart's 100-unit-wide viewBox, 8 units wide like the real ones.
const week = (start, total, x) => `
  <g class="wk" data-chamber="house" data-week="${start}" data-head="House · week of ${start}"
     data-total="${total}" data-kinds="passage:${total}"><title>Week of ${start}: ${total}</title>
    <rect class="hit" x="${x}" y="0" width="8" height="10"/></g>`;

const area = (chamber, total) => `
  <span class="area-line" title="Health, ${chamber}: ${total}" data-chamber="${chamber}" data-area="Health"
        data-head="Health · ${chamber}" data-total="${total}" data-kinds="passage:${total}"></span>`;

const PAGE = `
<main data-activity>
  <ul class="vol-key"><li><span class="swatch k-passage"></span>Passage</li></ul>
  <figure class="vol" data-list-scope>
    <svg role="img" viewBox="0 0 100 10">${week("2026-11-02", 1, 0)}${week("2026-11-09", 2, 10)}${week("2026-11-16", 0, 20)}</svg>
    <figcaption data-list></figcaption>
  </figure>
  <div data-list-scope>
    <ol class="areas" aria-hidden="true"><li>${area("house", 1)}${area("senate", 0)}</li></ol>
    <div data-list></div>
  </div>
</main>`;

const row = (w, r, a) => ({ u: `/votes/${r}/`, c: "house", w, a, k: "passage", d: "Nov. 9, 2026", r, q: "On Passage", t: `Bill ${r}`, s: "Passed" });
const VOTES = [row("2026-11-09", 3, "Health"), row("2026-11-09", 2, "Energy"), row("2026-11-02", 1, "Energy")];

function load(votes = VOTES) {
  const { window } = new JSDOM(`<!doctype html><body>${PAGE}</body>`, {
    url: "https://example.test/activity/",
    runScripts: "outside-only",
  });
  const page = { window, document: window.document, scrolls: 0 };
  window.Element.prototype.scrollIntoView = () => { page.scrolls++; };
  // The list data arrives when release() is called.
  const held = new Promise((resolve) => { page.release = resolve; });
  window.fetch = () => held.then(() => ({ ok: true, json: () => Promise.resolve({ votes: window.Array.from(votes) }) }));
  window.eval(SCRIPT);
  page.bars = [...window.document.querySelectorAll(".wk")];
  page.live = window.document.querySelector("[role=status]");
  page.panel = window.document.querySelector("figure [data-list]");
  page.settle = () => new Promise((resolve) => setTimeout(resolve, 0));
  // Past the announcement delay.
  page.heard = () => new Promise((resolve) => setTimeout(resolve, 150));
  page.press = (key, init = {}) => {
    const e = new window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init });
    window.document.activeElement.dispatchEvent(e);
    return e;
  };
  page.click = (target) => target.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  return page;
}

test("bars become labeled buttons, with one tab stop per chart", () => {
  const { document, bars } = load();
  assert.equal(document.querySelector("svg").getAttribute("role"), "group");
  assert.equal(document.querySelector(".areas").hasAttribute("aria-hidden"), false);
  assert.equal(bars[1].getAttribute("role"), "button");
  assert.equal(bars[1].getAttribute("aria-label"), "Week of 2026-11-09: 2");
  assert.deepEqual(bars.map((b) => b.getAttribute("tabindex")), ["-1", "-1", "0"]);
  const areas = [...document.querySelectorAll(".area-line")];
  assert.equal(areas[0].getAttribute("aria-label"), "Health, house: 1");
  assert.deepEqual(areas.map((b) => b.getAttribute("tabindex")), ["0", "-1"]);
  assert.equal(document.querySelector("title"), null);
});

test("a tap that misses every week lists the nearest one within reach", async () => {
  const { window, document, panel, release, settle } = load();
  const svg = document.querySelector("svg");
  // One viewBox unit is one pixel; week centers sit at 4, 14 and 24.
  svg.getBoundingClientRect = () => ({ left: 0, width: 100 });
  const tap = (clientX, target = svg) =>
    target.dispatchEvent(new window.MouseEvent("click", { bubbles: true, clientX }));

  tap(60); // 36px from the nearest week
  assert.equal(panel.textContent, "");

  tap(8); // between the first week and the second; the first is nearer
  assert.match(panel.textContent, /week of 2026-11-02/);
  release();
  await settle();

  tap(17, document.querySelector(".hit")); // on the first week's own rect: that week, not the nearest
  assert.match(panel.textContent, /week of 2026-11-02/);

  tap(17);
  assert.match(panel.textContent, /week of 2026-11-09/);
});

test("each bar controls its own chart's list panel", () => {
  const { document, bars, panel } = load();
  assert.ok(panel.id);
  bars.forEach((b) => assert.equal(b.getAttribute("aria-controls"), panel.id));
  const areaPanel = document.querySelector("div[data-list-scope] [data-list]");
  assert.notEqual(areaPanel.id, panel.id);
  document.querySelectorAll(".area-line").forEach((b) => assert.equal(b.getAttribute("aria-controls"), areaPanel.id));
});

test("a short status is announced, not the list", async () => {
  const { bars, panel, live, click, release, heard } = load();
  assert.equal(live.textContent, "");
  assert.equal(panel.contains(live), false);
  click(bars[1]);
  await heard();
  assert.equal(live.textContent, "House · week of 2026-11-09: Loading…");
  release();
  await heard();
  assert.equal(live.textContent, "House · week of 2026-11-09: 2 roll calls listed");
  click(bars[0]);
  await heard();
  assert.equal(live.textContent, "House · week of 2026-11-02: 1 roll call listed");
  // The same bar again: cleared, then announced again.
  click(bars[0]);
  assert.equal(live.textContent, "");
  await heard();
  assert.equal(live.textContent, "House · week of 2026-11-02: 1 roll call listed");
  click(bars[2]);
  await heard();
  assert.equal(live.textContent, "House · week of 2026-11-16: No roll calls");
  click(panel.querySelector("button"));
  assert.equal(live.textContent, "");
});

test("a list that loads after Close isn't announced", async () => {
  const { bars, panel, live, click, release, heard } = load();
  click(bars[1]);
  click(panel.querySelector("button"));
  release();
  await heard();
  assert.equal(live.textContent, "");
});

test("arrow keys, Home and End move between bars and stop at the ends", () => {
  const { document, bars, press } = load();
  bars[2].focus();
  press("ArrowLeft");
  assert.equal(document.activeElement, bars[1]);
  assert.deepEqual(bars.map((b) => b.getAttribute("tabindex")), ["-1", "0", "-1"]);
  press("Home");
  assert.equal(press("ArrowUp").defaultPrevented, true);
  assert.equal(document.activeElement, bars[0]);
  press("ArrowDown");
  assert.equal(document.activeElement, bars[1]);
  press("End");
  press("ArrowRight");
  assert.equal(document.activeElement, bars[2]);
  // Browser shortcuts (Alt+Left goes back) are left alone.
  assert.equal(press("ArrowLeft", { altKey: true }).defaultPrevented, false);
  assert.equal(document.activeElement, bars[2]);
});

test("a bar focused by key shows its counts; one focused by pointer doesn't", () => {
  const { window, document, bars, press } = load();
  const tip = document.querySelector(".vol-tip");
  bars[2].focus();
  assert.equal(tip.hidden, true);
  press("ArrowLeft");
  assert.equal(tip.hidden, false);
  assert.match(tip.textContent, /2 roll calls.*Press Enter/);
  bars[1].blur();
  assert.equal(tip.hidden, true);
  bars[0].dispatchEvent(new window.MouseEvent("mousedown", { bubbles: true }));
  bars[0].focus();
  assert.equal(tip.hidden, true);
});

for (const [name, key] of [["Enter", "Enter"], ["Space", " "]]) {
  test(`${name} lists a bar's roll calls, and Escape closes the list`, async () => {
    const { document, bars, panel, press, release, settle } = load();
    bars[1].focus();
    assert.equal(press(key).defaultPrevented, true);
    release();
    await settle();
    assert.deepEqual([...panel.querySelectorAll("a .t")].map((t) => t.textContent), ["Bill 3", "Bill 2"]);
    assert.equal(bars[1].getAttribute("aria-expanded"), "true");
    panel.querySelector("a").focus();
    press("Escape");
    assert.equal(panel.textContent, "");
    assert.equal(bars[1].getAttribute("aria-expanded"), "false");
    assert.equal(document.activeElement, bars[1]);
  });
}

test("Escape on another bar closes its own chart's list and keeps focus; another chart's list stays", () => {
  const { document, bars, panel, press } = load();
  bars[1].focus();
  press("Enter");
  const area = document.querySelector(".area-line");
  area.focus();
  press("Escape");
  assert.notEqual(panel.textContent, "");
  assert.equal(document.activeElement, area);
  bars[0].focus();
  assert.notEqual(panel.textContent, "");
  press("Escape");
  assert.equal(panel.textContent, "");
  assert.equal(document.activeElement, bars[0]);
});

test("Escape hides a focused bar's counts", () => {
  const { document, bars, press } = load();
  bars[2].focus();
  press("ArrowLeft");
  assert.equal(document.querySelector(".vol-tip").hidden, false);
  press("Escape");
  assert.equal(document.querySelector(".vol-tip").hidden, true);
  assert.equal(document.activeElement, bars[1]);
});

test("a held Enter doesn't list again", () => {
  const { bars, panel, press } = load();
  bars[1].focus();
  press("Enter");
  const head = panel.firstChild;
  assert.equal(press("Enter", { repeat: true }).defaultPrevented, true);
  assert.equal(panel.firstChild, head);
  press("Enter");
  assert.notEqual(panel.firstChild, head);
});

test("policy area bars move by arrow key and list their area", async () => {
  const { document, live, press, release, settle, heard } = load();
  const [house, senate] = document.querySelectorAll(".area-line");
  const panel = document.querySelector("div[data-list-scope] [data-list]");
  house.focus();
  press("ArrowDown");
  assert.equal(document.activeElement, senate);
  press("ArrowUp");
  press("Enter");
  release();
  await settle();
  assert.deepEqual([...panel.querySelectorAll("a .t")].map((t) => t.textContent), ["Bill 3"]);
  await heard();
  assert.equal(live.textContent, "Health · house: 1 roll call listed");
});

test("Close puts focus back on the bar, scrolling to it only after a key", () => {
  for (const key of [false, true]) {
    const { document, bars, panel, click, press } = load();
    click(bars[1]);
    const button = panel.querySelector("button");
    const focus = bars[1].focus;
    let options;
    bars[1].focus = function (o) { options = o; focus.call(this, o); };
    button.focus();
    if (key) press("Enter");
    click(button);
    assert.equal(panel.textContent, "");
    assert.equal(document.activeElement, bars[1]);
    assert.equal(options.preventScroll, !key);
  }
});

test("the loaded list scrolls into view unless the reader has scrolled", async () => {
  for (const moved of [false, true]) {
    const page = load();
    page.click(page.bars[1]);
    assert.equal(page.scrolls, 1);
    if (moved) Object.defineProperty(page.window, "scrollY", { value: 400 });
    page.release();
    await page.settle();
    assert.equal(page.panel.querySelectorAll("li").length, 2);
    assert.equal(page.scrolls, moved ? 1 : 2);
  }
});

test("a list that can't be built says so", async () => {
  // A row that passes the filter but breaks while its line is built.
  const broken = { ...VOTES[0] };
  Object.defineProperty(broken, "t", { get() { throw new Error("bad row"); } });
  const { bars, panel, live, click, release, settle, heard } = load([broken]);
  click(bars[1]);
  release();
  await settle();
  assert.match(panel.textContent, /The list couldn't be loaded/);
  assert.equal(panel.querySelector("ul"), null);
  await heard();
  assert.match(live.textContent, /The list couldn't be loaded/);
});
