window.addEventListener("error", (event) => {
  document.documentElement.dataset.appError = event.message;
});

window.addEventListener("unhandledrejection", (event) => {
  document.documentElement.dataset.appError = event.reason?.message || "Unhandled startup error";
});
