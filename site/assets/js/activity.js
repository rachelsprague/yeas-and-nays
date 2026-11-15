// Floor activity chart: hovering or tapping a week names its roll calls in
// the caption under the chart and marks the week. Leaving the chart puts back
// the latest week. Without JS each week's title shows on hover instead.
(function () {
  document.querySelectorAll("[data-volume]").forEach(function (root) {
    var svg = root.querySelector("svg");
    var caption = root.querySelector("[data-caption]");
    var current = null;

    function show(week) {
      if (current) current.classList.remove("on");
      current = week;
      if (week) week.classList.add("on");
      caption.textContent = week ? week.getAttribute("data-summary") : caption.getAttribute("data-default");
    }

    function weekAt(target) {
      return target.closest ? target.closest(".wk") : null;
    }

    svg.addEventListener("mouseover", function (e) { show(weekAt(e.target)); });
    svg.addEventListener("mouseleave", function () { show(null); });
    svg.addEventListener("click", function (e) { show(weekAt(e.target)); });
  });
})();
