// The home page's floor band: each [data-live-from] line shows from that time
// (a chamber's convening, with its Eastern offset) for HOURS hours. The site
// is rebuilt hourly, so once a chamber adjourns the next build moves the time
// to its next convening; HOURS only caps a line if the data stops updating.
// Re-checked each minute, so an open page shows a line when its time comes.
// A tab-filtered line keeps its hidden attribute; CSS shows only lines that
// are live and not hidden, and hides the band when none is.
(function () {
  "use strict";

  var HOURS = 14;

  function update() {
    var now = Date.now();
    document.querySelectorAll("[data-live-from]").forEach(function (el) {
      var from = Date.parse(el.dataset.liveFrom);
      var live = !isNaN(from) && now >= from && now < from + HOURS * 3600 * 1000;
      el.classList.toggle("is-live", live);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    update();
    setInterval(update, 60 * 1000);
  });
})();
