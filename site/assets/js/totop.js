// Back-to-top link: shown once the reader is two screens down, so short pages
// never show it. The link itself is a plain #top anchor (the browser scrolls
// to the top, and the next Tab starts from there); this only shows and hides
// it, rechecking on resize too, since rotating a phone changes a screen.
(function () {
  "use strict";

  var link = document.querySelector("[data-totop]");
  if (!link) return;

  var queued = false;
  function update() {
    queued = false;
    link.hidden = window.scrollY < window.innerHeight * 2;
  }
  function queue() {
    if (!queued) { queued = true; window.requestAnimationFrame(update); }
  }

  window.addEventListener("scroll", queue, { passive: true });
  window.addEventListener("resize", queue);
  update();
})();
