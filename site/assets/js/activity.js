// Floor activity charts. Every bar (a week, or an area's House or Senate
// line) carries data-head, data-total and data-kinds ("passage:4,…").
// Hovering a bar shows those counts in a box by the pointer; clicking it lists
// its roll calls in the [data-list] panel of its [data-list-scope], linked to
// their vote pages, from /activity/rollcalls.json (fetched on the first click).
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
    if (total) tip.appendChild(el("div", "muted", "Click to list them"));
    tip.hidden = false;
    moveTip(e);
  }

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

  page.addEventListener("mouseover", function (e) { hover(barAt(e.target), e); });
  // A click hides the box; moving on within the same bar brings it back.
  page.addEventListener("mousemove", function (e) {
    var bar = barAt(e.target);
    if (bar && (bar !== current || tip.hidden)) hover(bar, e);
    else if (current) moveTip(e);
  });
  page.addEventListener("mouseleave", function () { hover(null); });
  window.addEventListener("scroll", function () { hover(null); }, { passive: true });

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

  function closeList() {
    request++;
    if (!open) return;
    open.panel.textContent = "";
    open.bar.classList.remove("on");
    open = null;
  }

  function list(bar) {
    var panel = bar.closest("[data-list-scope]").querySelector("[data-list]");
    closeList();
    var mine = request;
    open = { bar: bar, panel: panel };
    bar.classList.add("on");

    var total = +bar.getAttribute("data-total");
    var head = el("div", "vol-list-head");
    head.appendChild(el("strong", "small", bar.getAttribute("data-head") + " · " + rollCalls(total)));
    var close = el("button", "linkish small", "Close");
    close.type = "button";
    close.addEventListener("click", closeList);
    head.appendChild(close);
    panel.appendChild(head);
    // The area list sits under every area's row: bring it into view.
    panel.scrollIntoView({ block: "nearest" });
    if (!total) return;

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
      status.remove();
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
      panel.appendChild(ul);
      panel.scrollIntoView({ block: "nearest" });
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
})();
