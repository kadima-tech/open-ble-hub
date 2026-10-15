// Bathroom Hub: progressive enhancements only. Every page works without this file.
(function () {
  "use strict";

  // Confirm destructive forms.
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  // Person pickers save as soon as they change.
  document.querySelectorAll("select[data-autosubmit]").forEach(function (select) {
    select.addEventListener("change", function () { select.form.submit(); });
  });

  // Close the profile switcher when clicking elsewhere.
  document.addEventListener("click", function (event) {
    document.querySelectorAll("details.switcher[open]").forEach(function (menu) {
      if (!menu.contains(event.target)) menu.removeAttribute("open");
    });
  });

  // Pairing countdown.
  document.querySelectorAll("[data-countdown]").forEach(function (el) {
    var left = parseInt(el.dataset.countdown, 10);
    var timer = setInterval(function () {
      left -= 1;
      el.textContent = Math.max(0, left);
      if (left <= 0) { clearInterval(timer); window.location.reload(); }
    }, 1000);
  });

  // Reload when the hub reports something new, unless the person is typing.
  if (document.body.dataset.poll) {
    var version = null;
    setInterval(function () {
      fetch("/api/status", { cache: "no-store" })
        .then(function (response) { return response.json(); })
        .then(function (status) {
          var active = document.activeElement;
          var typing = active && /^(INPUT|SELECT|TEXTAREA)$/.test(active.tagName);
          var menuOpen = document.querySelector("details[open]");
          if (version !== null && status.version !== version && !typing && !menuOpen) window.location.reload();
          version = status.version;
        })
        .catch(function () {});
    }, 4000);
  }
})();
