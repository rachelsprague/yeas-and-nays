// Tests for assets/js/live-floor.js: run with `make jstest` (node --test).
// Each test sets the page's clock and runs the minute check itself.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const SCRIPT = fs.readFileSync(path.join(__dirname, "..", "assets", "js", "live-floor.js"), "utf8");

const FROM = "2026-11-16T15:00:00-05:00";
const START = Date.parse(FROM);
const HOUR = 3600 * 1000;

const line = (from, attrs = "") => `<p class="live-line" data-live-from="${from}" ${attrs}>Line</p>`;

// Resolves once DOMContentLoaded has run the script's first check.
async function load(now, body = line(FROM)) {
  const dom = new JSDOM(`<!doctype html><body>${body}</body>`, { runScripts: "outside-only" });
  const { window } = dom;
  const page = { document: window.document, now, timers: [] };
  window.Date.now = () => page.now;
  window.setInterval = (fn, ms) => page.timers.push({ fn, ms });
  const ready = new Promise((resolve) => window.addEventListener("DOMContentLoaded", resolve));
  window.eval(SCRIPT);
  await ready;
  page.live = () => [...page.document.querySelectorAll("p")].map((el) => el.classList.contains("is-live"));
  return page;
}

test("not live before its time", async () => {
  assert.deepEqual((await load(START - 1)).live(), [false]);
});

test("live from its time, which carries an Eastern offset", async () => {
  assert.deepEqual((await load(Date.UTC(2026, 10, 16, 20, 0))).live(), [true]);
});

test("live until 14 hours after its time", async () => {
  assert.deepEqual((await load(START + 14 * HOUR - 1)).live(), [true]);
  assert.deepEqual((await load(START + 14 * HOUR)).live(), [false]);
});

test("rechecked each minute: an open page shows a line, then drops it", async () => {
  const page = await load(START - 1);
  assert.deepEqual(page.timers.map((t) => t.ms), [60 * 1000]);
  page.now = START;
  page.timers[0].fn();
  assert.deepEqual(page.live(), [true]);
  page.now = START + 14 * HOUR;
  page.timers[0].fn();
  assert.deepEqual(page.live(), [false]);
});

test("each line goes by its own time; one that isn't a time never shows", async () => {
  const page = await load(START, line(FROM) + line("2026-11-17T12:00:04-05:00") + line("not a time") + line(""));
  assert.deepEqual(page.live(), [true, false, false, false]);
});

test("a tab-hidden line is marked live but stays hidden", async () => {
  const page = await load(START, line(FROM, "hidden"));
  assert.deepEqual(page.live(), [true]);
  assert.equal(page.document.querySelector("p").hidden, true);
});
