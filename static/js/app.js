// Apply Bootstrap classes to inputs rendered by Django's built-in auth forms.
document.querySelectorAll("form.styled-form").forEach(function (form) {
  form.querySelectorAll("input, select, textarea").forEach(function (el) {
    var t = el.getAttribute("type");
    if (t === "hidden" || t === "submit") return;
    if (t === "checkbox" || t === "radio") { el.classList.add("form-check-input"); return; }
    el.classList.add(el.tagName === "SELECT" ? "form-select" : "form-control");
  });
});
