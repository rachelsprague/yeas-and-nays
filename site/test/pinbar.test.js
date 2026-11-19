// Tests for assets/js/pinbar.js: run with `make jstest` (node --test).
// Loads filters.js then pinbar.js, as the layout does. jsdom has no layout,
// so each test sets where the filters and the list's end are on screen.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const JS = path.join(__dirname, "..", "assets", "js");
const FILTERS = fs.readFileSync(path.join(JS, "filters.js"), "utf8");
const PINBAR = fs.readFileSync(path.join(JS, "pinbar.js"), "utf8");

// A vote page's roll call: name search and two selects.
const ROLL = `
<section id="scope" data-filter-scope>
  <p data-count data-noun="members" aria-live="polite">3 members</p>
  <div id="src" class="filters" data-pinbar>
    <div class="q"><label for="rc-q">Member name</label><input id="rc-q" type="search" data-filter="name"></div>
    <div><label for="rc-party">Party</label><select id="rc-party" data-filter="party">
      <option value="">All</option><option>D</option><option>R</option></select></div>
    <div><label for="rc-pos">Vote</label><select id="rc-pos" data-filter="position">
      <option value="">All</option><option>Yea</option><option>Nay</option></select></div>
  </div>
  <table><tbody>
    <tr data-row id="a" data-name="adams" data-party="D" data-position="Yea"></tr>
    <tr data-row id="b" data-name="baker" data-party="R" data-position="Yea"></tr>
    <tr data-row id="c" data-name="clark" data-party="R" data-position="Nay"></tr>
  </tbody></table>
</section>`;

// /votes/: search plus chamber tabs, together in the marked row.
const VOTES = `
<main id="scope" data-filter-scope>
  <div id="src" class="head-row" data-pinbar>
    <div class="filters"><div class="q"><label for="v-q">Filter</label><input id="v-q" type="search" data-filter="text"></div></div>
    <div class="tabs js-only" role="group" aria-label="Filter by chamber">
      <button type="button" data-tab="chamber" data-value="all" aria-pressed="true">All</button>
      <button type="button" data-tab="chamber" data-value="house" aria-pressed="false">House</button>
      <button type="button" data-tab="chamber" data-value="senate" aria-pressed="false">Senate</button>
    </div>
  </div>
  <p data-count data-noun="votes">2 votes</p>
  <ul>
    <li data-row id="h" data-text="h.r. 1" data-chamber="house"></li>
    <li data-row id="s" data-text="s. 2" data-chamber="senate"></li>
  </ul>
</main>`;

// /members/: the Show select defaults to "current", which isn't a filter set.
const MEMBERS = `
<main id="scope" data-filter-scope>
  <section id="src" class="filters" data-pinbar>
    <div class="q"><label for="m-q">Filter by name or state</label><input id="m-q" name="q" data-filter="search"></div>
    <div><label for="m-status">Show</label><select id="m-status" name="status" data-filter="status">
      <option value="current" selected>Current members</option><option value="former">Former members</option></select></div>
  </section>
  <p data-count data-noun="members" data-count-of="status">1 members</p>
  <ul>
    <li data-row id="c1" data-search="kentucky" data-status="current"></li>
    <li data-row id="f1" data-search="ohio" data-status="former"></li>
  </ul>
</main>`;

async function load(body, query = "") {
  const dom = new JSDOM(`<!doctype html><body>${body}</body>`, {
    url: "https://example.test/" + query,
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  const ready = new Promise((resolve) => window.document.addEventListener("DOMContentLoaded", resolve));
  window.eval(FILTERS);
  window.eval(PINBAR);
  await ready;
  return window;
}

// Puts the filters' bottom edge and the list's end at these screen offsets,
// then scrolls so the bar rechecks.
function at(window, filtersBottom, listBottom) {
  const { document } = window;
  document.getElementById("src").getBoundingClientRect = () => ({ bottom: filtersBottom });
  document.getElementById("scope").getBoundingClientRect = () => ({ bottom: listBottom });
  window.dispatchEvent(new window.Event("scroll"));
  return new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
}

function bar(document) {
  return document.querySelector(".pinbar");
}

function choose(window, select, value) {
  select.value = value;
  select.dispatchEvent(new window.Event("change", { bubbles: true }));
}

function visible(document) {
  return [...document.querySelectorAll("[data-row]")].filter((r) => !r.hidden).map((r) => r.id);
}

test("one hidden bar right after the filters, with no ids or names copied", async () => {
  const { document } = await load(MEMBERS);
  const b = bar(document);
  assert.equal(document.querySelectorAll(".pinbar").length, 1);
  assert.equal(document.getElementById("src").nextElementSibling, b);
  assert.equal(b.hidden, true);
  assert.equal(b.querySelector("[name]"), null);
  assert.equal(b.querySelector("[data-filter]"), null);
  assert.deepEqual([...b.querySelectorAll("[id]")].map((e) => e.id), [b.querySelector(".pinbar-more").id]);
});

test("shown once the filters are above the screen, hidden at the list's end", async () => {
  const window = await load(ROLL);
  const b = bar(window.document);
  await at(window, 10, 2000);
  assert.equal(b.hidden, true);
  await at(window, -1, 2000);
  assert.equal(b.hidden, false);
  await at(window, -1500, 0);
  assert.equal(b.hidden, true);
  await at(window, 200, 2000);
  assert.equal(b.hidden, true);
});

test("slides up with the list's end, as a sticky bar would", async () => {
  const window = await load(ROLL);
  const b = bar(window.document);
  Object.defineProperty(b, "offsetHeight", { get: () => (b.hidden ? 0 : 60) });
  await at(window, -1500, 600);
  assert.equal(b.style.transform, "");
  await at(window, -1500, 45);
  assert.equal(b.hidden, false);
  assert.equal(b.style.transform, "translateY(-15px)");
  await at(window, -1500, 600);
  assert.equal(b.style.transform, "");
});

test("stays while focus is in it, though the list ended under it", async () => {
  const window = await load(ROLL);
  const { document } = window;
  await at(window, -1, 2000);
  const q = bar(document).querySelector(".pinbar-q");
  q.focus();
  await at(window, -1, -5);
  assert.equal(bar(document).hidden, false);
  assert.equal(bar(document).style.transform, "");
  q.blur();
  bar(document).dispatchEvent(new window.FocusEvent("focusout"));
  await new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
  assert.equal(bar(document).hidden, true);
});

test("stays while its panel is open, though nothing in it has focus", async () => {
  const window = await load(ROLL);
  const b = bar(window.document);
  await at(window, -1, 2000);
  b.querySelector(".pinbar-toggle").click();
  await at(window, 200, 2000);
  assert.equal(b.hidden, false);
  b.querySelector(".pinbar-toggle").click();
  await new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
  assert.equal(b.hidden, true);
});

test("scroll padding matches the bar while shown, so focus doesn't land under it", async () => {
  const window = await load(ROLL);
  const b = bar(window.document);
  const html = window.document.documentElement;
  Object.defineProperty(b, "offsetHeight", { get: () => (b.hidden ? 0 : 60) });
  await at(window, -1, 2000);
  assert.equal(html.style.scrollPaddingTop, "60px");
  await at(window, 200, 2000);
  assert.equal(html.style.scrollPaddingTop, "");
});

test("typing in the bar's search filters rows and fills the original box", async () => {
  const window = await load(ROLL);
  const { document } = window;
  const q = bar(document).querySelector(".pinbar-q");
  assert.equal(q.getAttribute("aria-label"), "Member name");
  q.value = "bak";
  q.dispatchEvent(new window.Event("input", { bubbles: true }));
  assert.equal(document.getElementById("rc-q").value, "bak");
  assert.deepEqual(visible(document), ["b"]);
  assert.equal(bar(document).querySelector(".pinbar-count").textContent, "Showing 1 of 3 members");
});

test("a select in the bar filters rows; the button and line name what's set", async () => {
  const window = await load(ROLL);
  const { document } = window;
  const b = bar(document);
  const [party, pos] = b.querySelectorAll(".pinbar-more select");
  assert.equal(party.getAttribute("aria-label"), "Party");
  choose(window, party, "R");
  choose(window, pos, "Yea");
  assert.equal(document.getElementById("rc-party").value, "R");
  assert.deepEqual(visible(document), ["b"]);
  assert.equal(b.querySelector(".pinbar-toggle").textContent, "Filters (2)");
  assert.equal(b.querySelector(".pinbar-count").textContent, "Showing 1 of 3 members · R · Yea");
});

test("a select's input event, which comes before change, doesn't undo the choice", async () => {
  const window = await load(ROLL);
  const { document } = window;
  const party = bar(document).querySelector(".pinbar-more select");
  party.value = "R";
  party.dispatchEvent(new window.Event("input", { bubbles: true }));
  party.dispatchEvent(new window.Event("change", { bubbles: true }));
  assert.equal(document.getElementById("rc-party").value, "R");
  assert.deepEqual(visible(document), ["b", "c"]);
});

test("a change to the original filters shows in the bar", async () => {
  const window = await load(ROLL);
  const { document } = window;
  choose(window, document.getElementById("rc-pos"), "Nay");
  const b = bar(document);
  assert.equal(b.querySelectorAll(".pinbar-more select")[1].value, "Nay");
  assert.equal(b.querySelector(".pinbar-toggle").textContent, "Filters (1)");
});

test("the Filters button opens and closes the other controls", async () => {
  const window = await load(ROLL);
  const b = bar(window.document);
  const toggle = b.querySelector(".pinbar-toggle");
  const more = b.querySelector(".pinbar-more");
  assert.equal(toggle.getAttribute("aria-controls"), more.id);
  assert.equal(more.classList.contains("is-open"), false);
  toggle.click();
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  assert.equal(more.classList.contains("is-open"), true);
  toggle.click();
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(more.classList.contains("is-open"), false);
});

test("the bar's tabs click the original tabs and follow their state", async () => {
  const window = await load(VOTES);
  const { document } = window;
  const b = bar(document);
  const copies = b.querySelectorAll(".pinbar-more button");
  assert.equal(b.querySelector(".pinbar-more .js-only"), null);
  copies[2].click();
  assert.deepEqual(visible(document), ["s"]);
  assert.equal(document.querySelector('[data-value="senate"]').getAttribute("aria-pressed"), "true");
  assert.deepEqual([...copies].map((c) => c.getAttribute("aria-pressed")), ["false", "false", "true"]);
  assert.equal(b.querySelector(".pinbar-count").textContent, "Showing 1 of 2 votes · Senate");
  document.querySelector('[data-value="all"]').click();
  assert.equal(copies[0].getAttribute("aria-pressed"), "true");
  assert.equal(b.querySelector(".pinbar-toggle").textContent, "Filters");
});

test("the copied tab group is named in text, not by the original's id", async () => {
  const { document } = await load(`
<main data-filter-scope>
  <div data-pinbar>
    <input data-filter="search">
    <span id="m-ch">Chamber</span>
    <div class="tabs" role="group" aria-labelledby="m-ch">
      <button type="button" data-tab="chamber" data-value="all" aria-pressed="true">All</button>
    </div>
  </div>
</main>`);
  const g = bar(document).querySelector(".pinbar-more .tabs");
  assert.equal(g.getAttribute("aria-labelledby"), null);
  assert.equal(g.getAttribute("aria-label"), "Chamber");
});

test("works without a count: the line names only what's set", async () => {
  const window = await load(`
<section data-filter-scope>
  <div data-pinbar>
    <input data-filter="name">
    <select data-filter="party"><option value="">All</option><option>D</option></select>
  </div>
  <ul><li data-row data-name="a" data-party="D"></li></ul>
</section>`);
  const b = bar(window.document);
  assert.equal(b.querySelector(".pinbar-count").textContent, "");
  choose(window, b.querySelector(".pinbar-more select"), "D");
  assert.equal(b.querySelector(".pinbar-count").textContent, "D");
});

test("a select left at its default isn't counted as set", async () => {
  const window = await load(MEMBERS);
  const b = bar(window.document);
  assert.equal(b.querySelector(".pinbar-toggle").textContent, "Filters");
  assert.equal(b.querySelector(".pinbar-count").textContent, "1 members");
  choose(window, b.querySelector(".pinbar-more select"), "former");
  assert.deepEqual(visible(window.document), ["f1"]);
  assert.equal(b.querySelector(".pinbar-count").textContent, "1 members · Former members");
});

test("the bar starts from filters prefilled by the query string", async () => {
  const window = await load(MEMBERS, "?q=ohio&status=former");
  const b = bar(window.document);
  assert.equal(b.querySelector(".pinbar-q").value, "ohio");
  assert.equal(b.querySelector(".pinbar-more select").value, "former");
});

test("the count line is hidden from screen readers; the original stays live", async () => {
  const { document } = await load(ROLL);
  assert.equal(bar(document).querySelector(".pinbar-count").getAttribute("aria-hidden"), "true");
  assert.equal(bar(document).querySelector("[aria-live]"), null);
});

test("no bar without a search box or outside a filter scope", async () => {
  const { document } = await load(`
    <div data-pinbar><input data-filter="name"></div>
    <section data-filter-scope><div data-pinbar><select data-filter="party"><option value="">All</option></select></div></section>`);
  assert.equal(document.querySelector(".pinbar"), null);
});
