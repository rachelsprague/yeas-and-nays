// Share button (_includes/share.html): opens the device's share sheet with
// the Web Share API where there is one, and otherwise copies the page's link
// to the clipboard. No third-party share widgets. Fails soft: a clipboard
// error only logs.
(function () {
  "use strict";

  var buttons = document.querySelectorAll("[data-share]");

  Array.prototype.forEach.call(buttons, function (button) {
    button.addEventListener("click", function () {
      var title = button.getAttribute("data-share-title") || document.title;
      var url = button.getAttribute("data-share-url") || window.location.href;

      if (navigator.share) {
        // Rejects with AbortError when the reader closes the share sheet;
        // nothing to do.
        navigator.share({ title: title, url: url }).catch(function () {});
        return;
      }

      if (!navigator.clipboard) return;
      navigator.clipboard.writeText(url).then(function () {
        var label = button.textContent;
        button.textContent = "Link copied";
        button.disabled = true;
        setTimeout(function () {
          button.textContent = label;
          button.disabled = false;
        }, 2000);
      }, function (err) {
        console.error("Couldn't copy the link:", err);
      });
    });
  });
})();
