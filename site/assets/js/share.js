// Share button (_includes/share.html): opens the device's share sheet with
// the Web Share API where there is one, and otherwise copies the page's link
// to the clipboard. No third-party share widgets. Fails soft: a clipboard
// error only logs.
(function () {
  "use strict";

  var buttons = document.querySelectorAll("[data-share]");

  Array.prototype.forEach.call(buttons, function (button) {
    // Neither (an old browser, or a page not served over https): a button
    // that does nothing is worse than none.
    if (!navigator.share && !navigator.clipboard) {
      button.remove();
      return;
    }

    // The include's status line, so screen readers hear "Link copied" too.
    var status = button.nextElementSibling;
    if (status && !status.hasAttribute("data-share-status")) status = null;
    var label = button.textContent;
    var copied = false;

    button.addEventListener("click", function () {
      var title = button.getAttribute("data-share-title") || document.title;
      var url = button.getAttribute("data-share-url") || window.location.href;

      if (navigator.share) {
        // Rejects with AbortError when the reader closes the share sheet;
        // nothing to do.
        navigator.share({ title: title, url: url }).catch(function () {});
        return;
      }

      // Not disabled while it says so: that would drop keyboard focus.
      if (copied) return;
      navigator.clipboard.writeText(url).then(function () {
        copied = true;
        button.textContent = "Link copied";
        if (status) status.textContent = "Link copied";
        setTimeout(function () {
          copied = false;
          button.textContent = label;
          if (status) status.textContent = "";
        }, 2000);
      }, function (err) {
        console.error("Couldn't copy the link:", err);
      });
    });
  });
})();
