// Tests for assets/js/district-map.js's ZIP code search: run with `make jstest`
// (node --test). jsdom has no SVG geometry, so each district's path gets a
// stub getBBox and the map has no city labels (they read a transform).
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
  "WY": { where: "Wyoming, At Large", places: [], more_places: 0, rep: null, senators: [] },
};

const LOOKUP = { congress: 120, districts: { "KY-1": "01001 40001 40002", "KY-2": "40002 40003", "WY": "82001" }, no_voting_member: "20001 00601" };

const PAGE = `
  <div class="zipfind">
    <form data-zip="/assets/maps/zip-120.json"><input id="f-zip"><button type="submit">Find</button></form>
    <div data-zip-note hidden></div>
  </div>
  <section data-dmap>
    <svg viewBox="0 0 1000 500">
      <g class="districts">
        <a href="/m/1/" data-seat="KY-1"><path d="M0 0l10 0 0 10z"/></a>
        <a href="/m/2/" data-seat="KY-2"><path d="M10 0l10 0 0 10z"/></a>
        <a href="/m/3/" data-seat="WY"><path d="M30 0l10 0 0 10z"/></a>
      </g>
    </svg>
    <div data-card><p class="soft">Choose a district on the map.</p></div>
    <script type="application/json" data-people>${JSON.stringify(PEOPLE)}</script>
  </section>`;

async function load(respond = () => ({ ok: true, json: async () => LOOKUP })) {
  const dom = new JSDOM(`<!doctype html><body>${PAGE}</body>`, {
    url: "https://example.test/find/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  window.fetched = [];
  window.fetch = async (url) => { window.fetched.push(url); return respond(); };
  window.SVGElement.prototype.getBBox = function () { return { x: 0, y: 0, width: 10, height: 10 }; };
  window.Element.prototype.scrollIntoView = () => {};
  const ready = new Promise((resolve) => window.document.addEventListener("DOMContentLoaded", resolve));
  window.eval(SCRIPT);
  await ready;
  return window;
}

async function search(window, zip) {
  const doc = window.document;
  doc.querySelector("#f-zip").value = zip;
  doc.querySelector("form[data-zip]").dispatchEvent(new window.Event("submit", { cancelable: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  return doc.querySelector("[data-zip-note]");
}

const seat = (window, s) => window.document.querySelector(`a[data-seat="${s}"]`);

test("a ZIP code in one district chooses it and shows its card", async () => {
  const window = await load();
  const note = await search(window, "40001");
  assert.equal(note.hidden, false);
  assert.equal(note.textContent, "ZIP code 40001 is in Kentucky, 1st District.");
  assert.ok(seat(window, "KY-1").classList.contains("on"));
  assert.match(window.document.querySelector("[data-card]").textContent, /Rep One/);
});

test("an at-large ZIP code names the state", async () => {
  const window = await load();
  assert.equal((await search(window, "82001")).textContent, "ZIP code 82001 is in Wyoming, At Large.");
});

test("a split ZIP code highlights every district and chooses none", async () => {
  const window = await load();
  const note = await search(window, "40002");
  assert.match(note.textContent, /^ZIP code 40002 is split between 2 districts\./);
  assert.ok(seat(window, "KY-1").classList.contains("zip"));
  assert.ok(seat(window, "KY-2").classList.contains("zip"));
  assert.equal(window.document.querySelectorAll("a.on").length, 0);
  assert.equal(window.document.querySelector("[data-card]").textContent, "Choose a district on the map.");
  const buttons = [...note.querySelectorAll(".zipseats button")].map((b) => b.textContent);
  assert.deepEqual(buttons, ["Kentucky, 1st District", "Kentucky, 2nd District"]);
  assert.equal(note.querySelector("a").href, "https://www.house.gov/representatives/find-your-representative");
});

test("a split ZIP code's buttons choose that district", async () => {
  const window = await load();
  const note = await search(window, "40002");
  note.querySelectorAll(".zipseats button")[1].click();
  assert.ok(seat(window, "KY-2").classList.contains("on"));
  assert.match(window.document.querySelector("[data-card]").textContent, /Rep Two/);
});

test("a split ZIP code clears an earlier choice, and a new search clears the highlight", async () => {
  const window = await load();
  await search(window, "40001");
  await search(window, "40002");
  assert.equal(seat(window, "KY-1").classList.contains("on"), false);
  await search(window, "40003");
  assert.equal(window.document.querySelectorAll("a.zip").length, 0);
  assert.ok(seat(window, "KY-2").classList.contains("on"));
});

test("a ZIP code with no tabulation area points to house.gov", async () => {
  const window = await load();
  const note = await search(window, "99999");
  assert.match(note.textContent, /^No ZIP Code Tabulation Area matches 99999\./);
  assert.equal(note.querySelector("a").href, "https://www.house.gov/representatives/find-your-representative");
  assert.equal(window.document.querySelectorAll("a.on, a.zip").length, 0);
});

test("ZIP codes keep their leading zeros", async () => {
  const window = await load();
  assert.equal((await search(window, "01001")).textContent, "ZIP code 01001 is in Kentucky, 1st District.");
  assert.match((await search(window, "00601")).textContent, /District of Columbia or a U\.S\. territory/);
  assert.match((await search(window, "1001")).textContent, /^Enter a five-digit ZIP code\./);
});

for (const [zip, kind] of [["99999", "no match"], ["00601", "no voting member"]]) {
  test(`a ${kind} search clears an earlier district's card`, async () => {
    const window = await load();
    await search(window, "40001");
    await search(window, zip);
    assert.equal(window.document.querySelectorAll("a.on").length, 0);
    assert.equal(window.document.querySelector("[data-card]").textContent, "Choose a district on the map.");
  });
}

test("a ZIP code where no member votes says so", async () => {
  const window = await load();
  assert.match((await search(window, "20001")).textContent, /District of Columbia or a U\.S\. territory/);
});

test("anything but five digits asks for a ZIP code without fetching", async () => {
  const window = await load();
  for (const zip of ["", "4000", "400011", "4000a"]) {
    assert.equal((await search(window, zip)).textContent, "Enter a five-digit ZIP code.");
  }
  assert.deepEqual(window.fetched, []);
});

test("the lookup is fetched once, then reused", async () => {
  const window = await load();
  await search(window, "40001");
  await search(window, " 40003 ");
  assert.deepEqual(window.fetched, ["/assets/maps/zip-120.json"]);
});

test("a failed lookup says so and is tried again on the next search", async () => {
  let ok = false;
  const window = await load(() => (ok ? { ok: true, json: async () => LOOKUP } : { ok: false, status: 503 }));
  assert.match((await search(window, "40001")).textContent, /^The ZIP code lookup didn't load\./);
  ok = true;
  assert.equal((await search(window, "40001")).textContent, "ZIP code 40001 is in Kentucky, 1st District.");
  assert.equal(window.fetched.length, 2);
});

test("zooms the map to the ZIP code's districts", async () => {
  const window = await load();
  await search(window, "40001");
  const box = window.document.querySelector("svg").getAttribute("viewBox").split(" ").map(Number);
  // The 10 x 10 district, as wide as the 2:1 map needs to show its height, with a margin.
  assert.deepEqual(box, [0, 0, 30, 15]);
});
