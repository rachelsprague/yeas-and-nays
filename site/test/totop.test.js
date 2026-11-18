// Tests for assets/js/totop.js: run with `make jstest` (node --test).
// jsdom doesn't scroll, so each test sets scrollY itself and fires "scroll".
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const SCRIPT = fs.readFileSync(path.join(__dirname, "..", "assets", "js", "totop.js"), "utf8");

const LINK = `<a class="button totop" href="#top" data-totop hidden>Back to top</a>`;

function load(scrollY = 0) {
  const dom = new JSDOM(`<!doctype html><body>${LINK}</body>`, {
    url: "https://example.test/votes/119/house/2025/1/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  Object.defineProperty(window, "innerHeight", { value: 800, configurable: true });
  Object.defineProperty(window, "scrollY", { value: scrollY, writable: true, configurable: true });
  window.eval(SCRIPT);
  return window;
}

function scrollTo(window, y) {
  window.scrollY = y;
  window.dispatchEvent(new window.Event("scroll"));
  return new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
}

test("hidden at the top of the page", () => {
  const { document } = load();
  assert.equal(document.querySelector("[data-totop]").hidden, true);
});

test("shown once two screens down, hidden again back near the top", async () => {
  const window = load();
  const link = window.document.querySelector("[data-totop]");
  await scrollTo(window, 1599);
  assert.equal(link.hidden, true);
  await scrollTo(window, 1600);
  assert.equal(link.hidden, false);
  await scrollTo(window, 200);
  assert.equal(link.hidden, true);
});

test("rechecks on resize, when a screen gets taller without a scroll", async () => {
  const window = load(1700);
  const link = window.document.querySelector("[data-totop]");
  assert.equal(link.hidden, false);
  Object.defineProperty(window, "innerHeight", { value: 1000, configurable: true });
  window.dispatchEvent(new window.Event("resize"));
  await new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
  assert.equal(link.hidden, true);
});

test("shown on load when the page opens already scrolled down", () => {
  const { document } = load(5000);
  assert.equal(document.querySelector("[data-totop]").hidden, false);
});

test("does nothing on a page without the link", () => {
  const dom = new JSDOM(`<!doctype html><body></body>`, { runScripts: "outside-only" });
  assert.doesNotThrow(() => dom.window.eval(SCRIPT));
});
