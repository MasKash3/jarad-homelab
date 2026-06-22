const CACHE_NAME = "jarad-2026.06.22.3";
const ASSETS = [
  "./",
  "./index.html",
  "./styles.css?v=2026.06.22.3",
  "./js/error-handler.js?v=2026.06.22.3",
  "./js/api.js?v=2026.06.22.3",
  "./js/auth.js?v=2026.06.22.3",
  "./js/config.js?v=2026.06.22.3",
  "./js/empty-state.js?v=2026.06.22.3",
  "./js/utils.js?v=2026.06.22.3",
  "./app.js?v=2026.06.22.3",
  "./manifest.webmanifest",
  "./icons/icon-192.svg",
  "./icons/icon-512.svg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  const isStaticAsset = ASSETS.some((asset) => {
    const assetUrl = new URL(asset, self.location.origin);
    return assetUrl.pathname === url.pathname;
  });
  if (!isStaticAsset && event.request.mode !== "navigate") return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (!isStaticAsset) return response;
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      })
      .catch(() => caches.match(event.request).then((cached) => cached || caches.match("./index.html")))
  );
});
