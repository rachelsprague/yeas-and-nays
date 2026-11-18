// Tests for assets/js/filters.js: run with `make jstest` (node --test).
// Each test loads the real script into a jsdom page built from markup shaped
// like the site's, then waits for DOMContentLoaded so its own setup runs.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const SCRIPT = fs.readFileSync(path.join(__dirname, "..", "assets", "js", "filters.js"), "utf8");

async function load(body, query = "") {
  const dom = new JSDOM(`<!doctype html><body>${body}</body>`, {
    url: "https://example.test/members/" + query,
    runScripts: "outside-only",
  });
  const { window } = dom;
  const ready = new Promise((resolve) => window.document.addEventListener("DOMContentLoaded", resolve));
  window.eval(SCRIPT);
  await ready;
  return window;
}

function choose(window, select, value) {
  select.value = value;
  select.dispatchEvent(new window.Event("change"));
}

function visible(document) {
  return [...document.querySelectorAll("[data-row]")].filter((r) => !r.hidden).map((r) => r.id);
}

// The /members/ directory: Show select (current/former) and a state filter,
// with the count's total following the Show select.
const MEMBERS = `
<div data-filter-scope>
  <select data-filter="state" name="state">
    <option value="">All</option><option value="KY">Kentucky</option><option value="OH">Ohio</option>
  </select>
  <select data-filter="status" name="status">
    <option value="current" selected>Current members</option><option value="former">Former members</option>
  </select>
  <p data-count data-noun="members" data-count-of="status">3 members</p>
  <ul>
    <li data-row id="c1" data-status="current" data-state="KY"></li>
    <li data-row id="c2" data-status="current" data-state="OH"></li>
    <li data-row id="c3" data-status="current" data-state="OH"></li>
    <li data-row id="f1" data-status="former" data-state="KY"></li>
    <li data-row id="f2" data-status="former" data-state="OH"></li>
  </ul>
  <p data-empty hidden>No members match.</p>
</div>`;

test("count total follows the Show select, not every row", async () => {
  const { document } = await load(MEMBERS);
  const count = document.querySelector("[data-count]");
  assert.equal(count.textContent, "3 members");
  assert.deepEqual(visible(document), ["c1", "c2", "c3"]);

  choose(document.defaultView, document.querySelector('[data-filter="status"]'), "former");
  assert.equal(count.textContent, "2 members");
  assert.deepEqual(visible(document), ["f1", "f2"]);
});

test("count reads 'Showing x of n' with n from the Show select", async () => {
  const window = await load(MEMBERS);
  const { document } = window;
  const count = document.querySelector("[data-count]");
  const state = document.querySelector('[data-filter="state"]');

  choose(window, state, "OH");
  assert.equal(count.textContent, "Showing 2 of 3 members");

  choose(window, document.querySelector('[data-filter="status"]'), "former");
  assert.equal(count.textContent, "Showing 1 of 2 members");
  assert.deepEqual(visible(document), ["f2"]);
});

test("count and rows follow filters prefilled from the query string", async () => {
  const { document } = await load(MEMBERS, "?status=former&state=KY");
  assert.equal(document.querySelector("[data-count]").textContent, "Showing 1 of 2 members");
  assert.deepEqual(visible(document), ["f1"]);
});

test("empty message shows only when nothing matches", async () => {
  const window = await load(MEMBERS);
  const { document } = window;
  const empty = document.querySelector("[data-empty]");
  assert.equal(empty.hidden, true);

  // A state no row has: every row hides, the count is 0 of the Show total.
  const state = document.querySelector('[data-filter="state"]');
  state.insertAdjacentHTML("beforeend", '<option value="WY">Wyoming</option>');
  choose(window, state, "WY");
  assert.equal(empty.hidden, false);
  assert.equal(document.querySelector("[data-count]").textContent, "Showing 0 of 3 members");
});

test("without data-count-of the count's total is every row", async () => {
  const window = await load(MEMBERS.replace(' data-count-of="status"', ""));
  const count = window.document.querySelector("[data-count]");
  assert.equal(count.textContent, "Showing 3 of 5 members");
});

test("data-count-of naming a missing select counts every row", async () => {
  // /members/ with no former members renders no Show select.
  const window = await load(MEMBERS.replace(/<select data-filter="status"[\s\S]*?<\/select>/, ""));
  const { document } = window;
  const count = document.querySelector("[data-count]");
  assert.equal(count.textContent, "5 members");

  choose(window, document.querySelector('[data-filter="state"]'), "KY");
  assert.equal(count.textContent, "Showing 2 of 5 members");
});

// A member page's policy-area bars: spans that filters.js upgrades to tab
// buttons, an "All areas" button, more areas inside a details, and bill rows.
const AREAS = `
<span data-button data-tab="area" data-value="outside">Outside any scope</span>
<section data-filter-scope>
  <button type="button" data-tab="area" data-value="all" aria-pressed="true">All areas</button>
  <ul>
    <li><span class="m-area" data-button data-tab="area" data-value="health">
      <span class="small nums"><span>Health</span><span>2</span></span>
      <span class="area-top-bar" aria-hidden="true"><span style="width: 67%"></span></span>
    </span></li>
  </ul>
  <details data-open-on-filter>
    <summary>1 more area</summary>
    <ul><li><span class="m-area" data-button data-tab="area" data-value="taxation">Taxation 1</span></li></ul>
  </details>
  <p data-count data-noun="bills">3 bills</p>
  <ul>
    <li data-row id="b1" data-area="health"></li>
    <li data-row id="b2" data-area="health"></li>
    <li data-row id="b3" data-area="taxation"></li>
  </ul>
</section>`;

test("span[data-button] becomes a button with its attributes and children", async () => {
  const { document } = await load(AREAS);
  assert.equal(document.querySelectorAll("section span[data-button]").length, 0);

  const b = document.querySelector('section [data-value="health"]');
  assert.equal(b.tagName, "BUTTON");
  assert.equal(b.type, "button");
  assert.equal(b.className, "m-area");
  assert.equal(b.dataset.tab, "area");
  assert.equal(b.getAttribute("aria-pressed"), "false");
  assert.equal(b.hasAttribute("data-button"), false);
  assert.equal(b.querySelector(".nums").textContent, "Health2");
  assert.equal(b.querySelector(".area-top-bar").getAttribute("aria-hidden"), "true");
  assert.equal(b.parentElement.tagName, "LI");

  const t = document.querySelector('section [data-value="taxation"]');
  assert.equal(t.tagName, "BUTTON");
  assert.equal(t.closest("details") !== null, true);
});

test("span[data-button] outside a filter scope stays a span", async () => {
  const { document } = await load(AREAS);
  const outside = document.querySelector('[data-value="outside"]');
  assert.equal(outside.tagName, "SPAN");
  assert.equal(outside.hasAttribute("data-button"), true);
});

test("an upgraded bar filters rows like a tab and opens details", async () => {
  const { document } = await load(AREAS);
  const all = document.querySelector('[data-value="all"]');
  const health = document.querySelector('[data-value="health"]');
  const taxation = document.querySelector('[data-value="taxation"]');
  const details = document.querySelector("details");
  const count = document.querySelector("[data-count]");
  assert.equal(details.open, false);

  taxation.click();
  assert.deepEqual(visible(document), ["b3"]);
  assert.equal(count.textContent, "Showing 1 of 3 bills");
  assert.equal(taxation.getAttribute("aria-pressed"), "true");
  assert.equal(health.getAttribute("aria-pressed"), "false");
  assert.equal(all.getAttribute("aria-pressed"), "false");
  assert.equal(details.open, true);

  all.click();
  assert.deepEqual(visible(document), ["b1", "b2", "b3"]);
  assert.equal(count.textContent, "3 bills");
  assert.equal(taxation.getAttribute("aria-pressed"), "false");
  assert.equal(all.getAttribute("aria-pressed"), "true");
});

// The home page: chamber tabs over every module. Each lead vote shows only
// for its tab, lists show their first n rows for the chosen chamber, and a
// "More recent votes" row skips the tab whose lead vote it already is.
const HOME = `
<main data-filter-scope>
  <button type="button" data-tab="chamber" data-value="all" aria-pressed="true">All</button>
  <button type="button" data-tab="chamber" data-value="house" aria-pressed="false">House</button>
  <button type="button" data-tab="chamber" data-value="senate" aria-pressed="false">Senate</button>
  <div id="lead-all" data-show-when="chamber:all"></div>
  <div id="lead-house" data-show-when="chamber:house" hidden></div>
  <div id="lead-senate" data-show-when="chamber:senate" hidden></div>
  <ul id="close" data-limit="2">
    <li data-row id="c1" data-chamber="house"></li>
    <li data-row id="c2" data-chamber="senate"></li>
    <li data-row id="c3" data-chamber="house" hidden></li>
    <li data-row id="c4" data-chamber="house" hidden></li>
  </ul>
  <ul id="more" data-limit="2">
    <li data-row id="m1" data-chamber="house" data-skip-when="chamber:all chamber:house" hidden></li>
    <li data-row id="m2" data-chamber="senate" data-skip-when="chamber:senate"></li>
    <li data-row id="m3" data-chamber="house"></li>
    <li data-row id="m4" data-chamber="senate" hidden></li>
  </ul>
  <section id="soon" data-row data-chamber="senate">
    <ul data-limit="1">
      <li data-row id="s1" data-chamber="senate"></li>
      <li data-row id="s2" data-chamber="senate" hidden></li>
    </ul>
  </section>
</main>`;

function tab(document, value) {
  document.querySelector(`[data-tab="chamber"][data-value="${value}"]`).click();
}

function shown(document, selector) {
  return [...document.querySelectorAll(selector)].filter((el) => !el.hidden).map((el) => el.id);
}

test("data-limit shows at most n matching rows in each list", async () => {
  const { document } = await load(HOME);
  assert.deepEqual(shown(document, "#close [data-row]"), ["c1", "c2"]);

  // Rows past the limit for "all" fill in once the other chamber's rows drop out.
  tab(document, "house");
  assert.deepEqual(shown(document, "#close [data-row]"), ["c1", "c3"]);

  tab(document, "senate");
  assert.deepEqual(shown(document, "#close [data-row]"), ["c2"]);
});

test("data-limit counts each list on its own", async () => {
  const { document } = await load(HOME);
  // Two rows shown in #close don't use up #more's limit.
  assert.deepEqual(shown(document, "#more [data-row]"), ["m2", "m3"]);
});

test("a module that is a row itself hides with its tab, and its list keeps its limit", async () => {
  const { document } = await load(HOME);
  // The module isn't inside a limited list, so it doesn't count toward one.
  assert.deepEqual(shown(document, "#soon, #soon [data-row]"), ["soon", "s1"]);

  tab(document, "house");
  assert.equal(document.querySelector("#soon").hidden, true);

  tab(document, "senate");
  assert.deepEqual(shown(document, "#soon, #soon [data-row]"), ["soon", "s1"]);
});

test("data-show-when shows an element only while its tab is selected", async () => {
  const { document } = await load(HOME);
  assert.deepEqual(shown(document, "[data-show-when]"), ["lead-all"]);

  tab(document, "senate");
  assert.deepEqual(shown(document, "[data-show-when]"), ["lead-senate"]);

  tab(document, "all");
  assert.deepEqual(shown(document, "[data-show-when]"), ["lead-all"]);
});

test("data-skip-when hides a row for each tab it names, without using up the limit", async () => {
  const { document } = await load(HOME);
  // m1 skips "all": the next two rows fill the list.
  assert.deepEqual(shown(document, "#more [data-row]"), ["m2", "m3"]);

  // m1 skips "house" too, so m3 is the only House row left.
  tab(document, "house");
  assert.deepEqual(shown(document, "#more [data-row]"), ["m3"]);

  // m2 skips "senate": m4 takes its place.
  tab(document, "senate");
  assert.deepEqual(shown(document, "#more [data-row]"), ["m4"]);
});

// A vote page's full roll call: a name search box beside exact-match selects.
// The page writes data-name lowercased; names here are made up.
const ROLL_CALL = `
<section data-filter-scope>
  <p data-count data-noun="members">4 members</p>
  <input type="search" data-filter="name">
  <select data-filter="position">
    <option value="">All</option><option>Yea</option><option>Not Voting</option>
  </select>
  <table><tbody>
    <tr data-row id="r1" data-name="adams, pat" data-position="Yea"></tr>
    <tr data-row id="r2" data-name="mcadams, lee" data-position="Not Voting"></tr>
    <tr data-row id="r3" data-name="smith, jo" data-position="Yea"></tr>
    <tr data-row id="r4" data-position="Yea"></tr>
  </tbody></table>
</section>`;

function type(window, input, value) {
  input.value = value;
  input.dispatchEvent(new window.Event("input"));
}

test("search box matches a case-insensitive substring of the row's value", async () => {
  const window = await load(ROLL_CALL);
  const { document } = window;
  const q = document.querySelector('[data-filter="name"]');

  // Anywhere in the value, in any case; r4 has no data-name, so it hides.
  type(window, q, "ADAMS");
  assert.deepEqual(visible(document), ["r1", "r2"]);
  assert.equal(document.querySelector("[data-count]").textContent, "Showing 2 of 4 members");

  // Spaces around the query are ignored.
  type(window, q, "  Smith, J ");
  assert.deepEqual(visible(document), ["r3"]);

  // Cleared, every row is back and the count drops "Showing".
  type(window, q, "");
  assert.deepEqual(visible(document), ["r1", "r2", "r3", "r4"]);
  assert.equal(document.querySelector("[data-count]").textContent, "4 members");
});

test("a select matches the whole value, unlike the search box", async () => {
  const window = await load(ROLL_CALL);
  const { document } = window;
  const position = document.querySelector('[data-filter="position"]');
  position.insertAdjacentHTML("beforeend", "<option>Not</option>");

  choose(window, position, "Not");
  assert.deepEqual(visible(document), []);

  choose(window, position, "Not Voting");
  assert.deepEqual(visible(document), ["r2"]);

  // Search box and select together: both have to match.
  type(window, document.querySelector('[data-filter="name"]'), "adams");
  choose(window, position, "Yea");
  assert.deepEqual(visible(document), ["r1"]);
});
