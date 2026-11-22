// Tests for assets/js/share.js: run with `make jstest` (node --test).
// jsdom has neither navigator.share nor navigator.clipboard, so each test
// stubs the one it needs.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const SCRIPT = fs.readFileSync(path.join(__dirname, "..", "assets", "js", "share.js"), "utf8");

const PAGE_URL = "https://example.test/votes/119/house/2025/1/";
const BUTTON = `<button type="button" class="share js-only" data-share data-share-title="Example vote" data-share-url="${PAGE_URL}">Share</button><span class="visually-hidden" role="status" data-share-status></span>`;

function load({ share, clipboard } = {}) {
  const dom = new JSDOM(`<!doctype html><title>Page · Yeas &amp; Nays</title><body>${BUTTON}</body>`, {
    url: PAGE_URL,
    runScripts: "outside-only",
  });
  const { window } = dom;
  if (share) Object.defineProperty(window.navigator, "share", { value: share, configurable: true });
  if (clipboard) Object.defineProperty(window.navigator, "clipboard", { value: clipboard, configurable: true });
  window.eval(SCRIPT);
  return window;
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

test("opens the share sheet with the page's title and link", async () => {
  const calls = [];
  const window = load({ share: (data) => { calls.push({ ...data }); return Promise.resolve(); } });
  window.document.querySelector("[data-share]").click();
  await tick();
  assert.deepEqual(calls, [{ title: "Example vote", url: PAGE_URL }]);
});

test("closing the share sheet isn't an error", async () => {
  const window = load({ share: () => Promise.reject(new window.DOMException("closed", "AbortError")) });
  const button = window.document.querySelector("[data-share]");
  button.click();
  await tick();
  assert.equal(button.textContent, "Share");
});

test("without a share sheet, copies the link and says so for two seconds", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const copied = [];
  const window = load({ clipboard: { writeText: (text) => { copied.push(text); return Promise.resolve(); } } });
  const button = window.document.querySelector("[data-share]");
  const status = window.document.querySelector("[data-share-status]");
  button.click();
  await tick();
  assert.deepEqual(copied, [PAGE_URL]);
  assert.equal(button.textContent, "Link copied");
  assert.equal(status.textContent, "Link copied");
  // Stays enabled, so keyboard focus stays on it; a second click meanwhile
  // doesn't copy again or restart the message.
  assert.equal(button.disabled, false);
  button.click();
  await tick();
  assert.equal(copied.length, 1);
  t.mock.timers.tick(2000);
  assert.equal(button.textContent, "Share");
  assert.equal(status.textContent, "");
});

test("a failed copy leaves the button as it was", async (t) => {
  const window = load({ clipboard: { writeText: () => Promise.reject(new Error("denied")) } });
  const logged = t.mock.method(window.console, "error", () => {});
  const button = window.document.querySelector("[data-share]");
  button.click();
  await tick();
  assert.equal(button.textContent, "Share");
  assert.equal(window.document.querySelector("[data-share-status]").textContent, "");
  assert.equal(logged.mock.callCount(), 1);
});

test("removed where there's neither a share sheet nor a clipboard", () => {
  const window = load();
  assert.equal(window.document.querySelector("[data-share]"), null);
});

test("falls back to the page's own title and address when the button names none", async () => {
  const calls = [];
  const window = load({ share: (data) => { calls.push({ ...data }); return Promise.resolve(); } });
  const button = window.document.querySelector("[data-share]");
  button.removeAttribute("data-share-title");
  button.removeAttribute("data-share-url");
  button.click();
  await tick();
  assert.deepEqual(calls, [{ title: "Page · Yeas & Nays", url: PAGE_URL }]);
});
