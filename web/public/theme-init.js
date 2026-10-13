// Apply the saved theme before first paint (same key as src/lib/theme.ts).
(function () {
  var theme = null;
  try {
    theme = localStorage.getItem("mailalias-theme");
  } catch {
    // Storage blocked: fall back to the system preference.
  }
  var dark = theme === "dark" || (theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
  if (dark) document.documentElement.classList.add("dark");
})();
