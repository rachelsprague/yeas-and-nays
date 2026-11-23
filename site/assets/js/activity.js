// Floor activity charts. Every bar (a week, or an area's House or Senate
// line) carries data-head, data-total and data-kinds ("passage:4,…").
// Hovering a bar shows those counts in a box by the pointer; clicking it lists
// its roll calls in the [data-list] panel of its [data-list-scope], linked to
// their vote pages, from /activity/rollcalls.json (fetched on the first click).
// By keyboard, each chart is one tab stop: arrow keys, Home and End move between
// its bars, Enter or Space lists a bar's roll calls, and Escape closes the list.
// Everything from the data is written as text, never HTML. Without JS each bar
// keeps its title, and the tables under the charts have every count.
(function () {
  var page = document.querySelector("[data-activity]");
  if (!page) return;

  // Kind labels, from the legend.
  var labels = {};
  page.querySelectorAll(".vol-key li").forEach(function (li) {
    var swatch = li.querySelector(".swatch");
    var key = swatch && (swatch.className.match(/\bk-(\w+)/) || [])[1];
    if (key) labels[key] = li.textContent.trim();
  });

  // Bars become buttons, labeled with their counts. The chart's own image role
  // and the area list's aria-hidden would hide them, so those go.
  page.querySelectorAll(".vol svg[role=img]").forEach(function (svg) { svg.setAttribute("role", "group"); });
  page.querySelectorAll(".areas[aria-hidden]").forEach(function (ol) { ol.removeAttribute("aria-hidden"); });
  page.querySelectorAll("[data-list-scope]").forEach(function (scope) {
    var bars = scope.querySelectorAll("[data-head]");
    bars.forEach(function (bar) {
      var title = bar.querySelector("title");
      var summary = title ? title.textContent : bar.getAttribute("title");
      bar.setAttribute("role", "button");
      bar.setAttribute("aria-label", summary || bar.getAttribute("data-head"));
      bar.setAttribute("aria-expanded", "false");
      bar.setAttribute("tabindex", "-1");
    });
    // Tab lands on the latest week, or the first area.
    var start = bars[0] && bars[0].hasAttribute("data-week") ? bars[bars.length - 1] : bars[0];
    if (start) start.setAttribute("tabindex", "0");
  });

  // The box replaces the browser's own tooltip.
  page.querySelectorAll(".wk title").forEach(function (t) { t.remove(); });
  page.querySelectorAll(".area-line[title]").forEach(function (el) { el.removeAttribute("title"); });

  var tip = document.createElement("div");
  tip.className = "vol-tip small nums";
  tip.hidden = true;
  document.body.appendChild(tip);

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function rollCalls(n) { return n + " roll call" + (n === 1 ? "" : "s"); }

  function barAt(target) {
    return target.closest ? target.closest("[data-head]") : null;
  }

  var byKey = false; // whether the last input was a key press

  function showTip(bar, e) {
    tip.textContent = "";
    tip.appendChild(el("strong", null, bar.getAttribute("data-head")));
    var total = +bar.getAttribute("data-total");
    tip.appendChild(el("div", null, total ? rollCalls(total) : "No roll calls"));
    (bar.getAttribute("data-kinds") || "").split(",").forEach(function (pair) {
      if (!pair) return;
      var kv = pair.split(":");
      var line = el("div", "tip-kind");
      line.appendChild(el("span", "swatch k-" + kv[0]));
      line.appendChild(el("span", null, (labels[kv[0]] || kv[0]) + " " + kv[1]));
      tip.appendChild(line);
    });
    if (total) tip.appendChild(el("div", "muted", byKey ? "Press Enter to list them" : "Click to list them"));
    tip.hidden = false;
    moveTip(e);
  }

  // At the pointer, or a focused bar's top left corner.
  function moveTip(e) {
    var x = e.clientX + 14, y = e.clientY + 14;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    if (x + w > window.innerWidth - 8) x = e.clientX - w - 14;
    if (y + h > window.innerHeight - 8) y = e.clientY - h - 14;
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = Math.max(8, y) + "px";
  }

  var current = null;
  function hover(bar, e) {
    if (current && current !== bar) current.classList.remove("hover");
    current = bar;
    if (bar) { bar.classList.add("hover"); showTip(bar, e); } else { tip.hidden = true; }
  }

  page.addEventListener("mouseover", function (e) { byKey = false; hover(barAt(e.target), e); });
  // A click hides the box; moving on within the same bar brings it back.
  page.addEventListener("mousemove", function (e) {
    var bar = barAt(e.target);
    if (bar && (bar !== current || tip.hidden)) hover(bar, e);
    else if (current) moveTip(e);
  });
  page.addEventListener("mouseleave", function () { hover(null); });
  // Focusing a bar can scroll it into view: the box stays with it.
  window.addEventListener("scroll", function () {
    if (byKey && current && current === document.activeElement) moveTip(corner(current));
    else hover(null);
  }, { passive: true });

  function corner(bar) {
    var r = bar.getBoundingClientRect();
    return { clientX: r.left, clientY: r.top };
  }

  document.addEventListener("keydown", function () { byKey = true; }, true);
  document.addEventListener("mousedown", function () { byKey = false; }, true);
  page.addEventListener("focusin", function (e) {
    var bar = barAt(e.target);
    if (!bar) return;
    bar.closest("[data-list-scope]").querySelectorAll('[data-head][tabindex="0"]').forEach(function (b) {
      b.setAttribute("tabindex", "-1");
    });
    bar.setAttribute("tabindex", "0");
    if (byKey) hover(bar, corner(bar));
  });
  page.addEventListener("focusout", function (e) { if (barAt(e.target)) hover(null); });

  var votes = null;
  function loadVotes() {
    if (!votes) {
      votes = fetch("/activity/rollcalls.json")
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) {
          if (!Array.isArray(d && d.votes)) throw new Error("no votes");
          return d.votes;
        });
      votes.catch(function () { votes = null; }); // let a later click try again
    }
    return votes;
  }

  // One list open at a time. Each click (and Close) starts a new request
  // number, so a list that finishes loading after another click is dropped.
  var open = null; // { bar, panel }
  var request = 0;

  // refocus: also put focus back on the list's bar (Close and Escape).
  function closeList(refocus) {
    request++;
    if (!open) return;
    var bar = open.bar;
    open.panel.textContent = "";
    bar.classList.remove("on");
    bar.setAttribute("aria-expanded", "false");
    open = null;
    // By key the page scrolls to the bar, so focus is never off screen.
    if (refocus) bar.focus({ preventScroll: !byKey });
  }

  function list(bar) {
    var panel = bar.closest("[data-list-scope]").querySelector("[data-list]");
    closeList();
    var mine = request;
    open = { bar: bar, panel: panel };
    bar.classList.add("on");
    bar.setAttribute("aria-expanded", "true");

    var total = +bar.getAttribute("data-total");
    var head = el("div", "vol-list-head");
    head.appendChild(el("strong", "small", bar.getAttribute("data-head") + " · " + rollCalls(total)));
    var close = el("button", "linkish small", "Close");
    close.type = "button";
    close.addEventListener("click", function () { closeList(true); });
    head.appendChild(close);
    panel.appendChild(head);
    // The area list sits under every area's row: bring it into view.
    panel.scrollIntoView({ block: "nearest" });
    if (!total) return;
    var scrolled = window.scrollY;

    var status = el("p", "small muted", "Loading…");
    panel.appendChild(status);
    var chamber = bar.getAttribute("data-chamber");
    var week = bar.getAttribute("data-week");
    var area = bar.getAttribute("data-area");
    loadVotes().then(function (all) {
      if (mine !== request) return; // another click or Close since
      var rows = all.filter(function (v) {
        return v.c === chamber && (week ? v.w === week : v.a === area);
      });
      var ul = el("ul", "ruled thin vol-votes");
      rows.forEach(function (v) {
        var li = el("li", "vote-item");
        var a = el("a", "headline-link");
        a.href = v.u;
        var kicker = el("span", "kicker muted nums");
        kicker.appendChild(el("span", "swatch k-" + v.k));
        kicker.appendChild(document.createTextNode(" Roll " + v.r + " · " + v.d + " · " + (labels[v.k] || "")));
        a.appendChild(kicker);
        if (v.q) a.appendChild(el("span", "small soft", v.q));
        a.appendChild(el("span", "t", v.t));
        a.appendChild(el("span", "small soft nums", v.s));
        li.appendChild(a);
        ul.appendChild(li);
      });
      status.remove();
      panel.appendChild(ul);
      // Not if the reader has scrolled while it loaded.
      if (window.scrollY === scrolled) panel.scrollIntoView({ block: "nearest" });
    }).catch(function () {
      if (mine === request) status.textContent = "The list couldn't be loaded. The tables below have every count.";
    });
  }

  page.addEventListener("click", function (e) {
    var bar = barAt(e.target);
    if (!bar) return;
    tip.hidden = true;
    list(bar);
  });

  page.addEventListener("keydown", function (e) {
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    var bar = barAt(e.target);
    if (e.key === "Escape") {
      // Closes only this chart's list, and moves focus only out of the list.
      tip.hidden = true;
      var scope = e.target.closest("[data-list-scope]");
      if (open && scope && scope.contains(open.panel)) closeList(open.panel.contains(e.target));
      return;
    }
    if (!bar) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (e.repeat) return;
      tip.hidden = true;
      list(bar);
      return;
    }
    var bars = Array.from(bar.closest("[data-list-scope]").querySelectorAll("[data-head]"));
    var i = bars.indexOf(bar);
    if (e.key === "ArrowRight" || e.key === "ArrowDown") i++;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") i--;
    else if (e.key === "Home") i = 0;
    else if (e.key === "End") i = bars.length - 1;
    else return;
    e.preventDefault();
    if (bars[i]) bars[i].focus();
  });
})();
