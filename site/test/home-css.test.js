// Tests for the home page's CSS in assets/css/site.css: run with `make jstest`.
// jsdom resolves selectors (:has, :not) but not media queries, so these cover
// the rules that apply at every width: the floor band and the module rows.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const CSS = fs.readFileSync(path.join(__dirname, "..", "assets", "css", "site.css"), "utf8");
const SCRIPT = fs.readFileSync(path.join(__dirname, "..", "assets", "js", "filters.js"), "utf8");

function page(body) {
  const { window } = new JSDOM(`<!doctype html><style>${CSS}</style><body>${body}</body>`, { runScripts: "outside-only" });
  return {
    window,
    show: (selector) => window.getComputedStyle(window.document.querySelector(selector)).display,
  };
}

const live = (id, attrs = "") => `<p class="live-line is-live" id="${id}" ${attrs}>In session</p>`;
const idle = (id, attrs = "") => `<p class="live-line" id="${id}" ${attrs}>Scheduled</p>`;

test("a live line shows, and so does the band holding it", () => {
  const { show } = page(`<div class="live-band" id="band">${live("line")}</div>`);
  assert.equal(show("#line"), "flex");
  assert.equal(show("#band"), "flex");
});

test("a line that isn't live stays hidden, and the band with it", () => {
  const { show } = page(`<div class="live-band" id="band">${idle("line")}</div>`);
  assert.equal(show("#line"), "none");
  assert.equal(show("#band"), "none");
});

test("a live line a chamber tab hides leaves the band hidden", () => {
  const { show } = page(`<div class="live-band" id="band">${live("line", "hidden")}</div>`);
  assert.equal(show("#line"), "none");
  assert.equal(show("#band"), "none");
});

test("the band shows while any one of its lines is live and not hidden", () => {
  const { show } = page(`<div class="live-band" id="band">${live("senate", "hidden")}${live("house")}</div>`);
  assert.equal(show("#senate"), "none");
  assert.equal(show("#house"), "flex");
  assert.equal(show("#band"), "flex");
});

const row = (inner) => `<div class="modules three" id="row">${inner}</div>`;
const mod = (id, attrs = "") => `<section id="${id}" ${attrs}>${id}</section>`;

test("a row whose modules are all hidden is hidden, rule and all", () => {
  const { show } = page(row(mod("a", "hidden") + mod("b", "hidden")));
  assert.equal(show("#row"), "none");
  assert.equal(show("#a"), "none");
});

test("a row with a module shown stays in the page", () => {
  const { show } = page(row(mod("a", "hidden") + mod("b")));
  assert.equal(show("#row"), "grid");
  assert.equal(show("#b"), "flex");
});

test("the gap above a module (under its rule) appears only once a module is shown before it", () => {
  const { window } = page(row(mod("a", "hidden") + mod("b") + mod("c")));
  const top = (id) => window.getComputedStyle(window.document.getElementById(id)).paddingTop;
  assert.equal(top("b"), "0");
  assert.equal(top("c"), "12px");
});

test("each chamber tab hides the modules with no rows for it, and the row follows", async () => {
  const body = `
    <div data-filter-scope>
      <button type="button" data-tab="chamber" data-value="all" aria-pressed="true">All</button>
      <button type="button" data-tab="chamber" data-value="house" aria-pressed="false">House</button>
      <button type="button" data-tab="chamber" data-value="senate" aria-pressed="false">Senate</button>
      ${row(
        mod("both", `data-row data-chamber="senate house"`) +
          mod("senate-only", `data-row data-chamber="senate"`) +
          mod("house-only", `data-row data-chamber="house"`)
      )}
      <div class="modules two" id="solo">${mod("solo-senate", `data-row data-chamber="senate"`)}</div>
    </div>`;
  const { window, show } = page(body);
  const ready = new Promise((resolve) => window.document.addEventListener("DOMContentLoaded", resolve));
  window.eval(SCRIPT);
  await ready;
  const click = (value) => window.document.querySelector(`[data-value="${value}"]`).click();
  const shown = () => ["both", "senate-only", "house-only"].filter((id) => show("#" + id) !== "none");

  assert.deepEqual(shown(), ["both", "senate-only", "house-only"]);
  click("house");
  assert.deepEqual(shown(), ["both", "house-only"]);
  assert.equal(show("#solo"), "none");
  click("senate");
  assert.deepEqual(shown(), ["both", "senate-only"]);
  assert.equal(show("#solo"), "grid");
  click("all");
  assert.deepEqual(shown(), ["both", "senate-only", "house-only"]);
});
