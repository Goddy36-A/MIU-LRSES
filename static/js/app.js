// Apply Bootstrap classes to inputs rendered by Django's built-in auth forms.
document.querySelectorAll("form.styled-form").forEach(function (form) {
  form.querySelectorAll("input, select, textarea").forEach(function (el) {
    var t = el.getAttribute("type");
    if (t === "hidden" || t === "submit") return;
    if (t === "checkbox" || t === "radio") { el.classList.add("form-check-input"); return; }
    el.classList.add(el.tagName === "SELECT" ? "form-select" : "form-control");
  });
});

// Keep the unread-notification badge fresh (in-app only; this is not a browser/push notification).
(function () {
  var link = document.querySelector("[data-unread-url]");
  var badge = document.getElementById("unread-badge");
  if (!link || !badge || !window.fetch) return;
  function refresh() {
    if (document.hidden) return;
    fetch(link.getAttribute("data-unread-url"), { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.ok && (r.headers.get("content-type") || "").indexOf("json") > -1 ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        badge.textContent = data.unread;
        badge.hidden = data.unread === 0;
      })
      .catch(function () { /* offline or signed out: leave the badge as it is */ });
  }
  setInterval(refresh, 60000);
})();
