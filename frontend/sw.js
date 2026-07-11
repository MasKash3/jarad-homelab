const CACHE_NAME = "jarad-2026.07.11.2";
const ASSETS = [
  "./",
  "./index.html",
  "./styles.css?v=2026.07.11.2",
  "./js/error-handler.js?v=2026.07.11.2",
  "./js/api.js?v=2026.07.11.2",
  "./js/auth.js?v=2026.07.11.2",
  "./js/config.js?v=2026.07.11.2",
  "./js/empty-state.js?v=2026.07.11.2",
  "./js/utils.js?v=2026.07.11.2",
  "./app.js?v=2026.07.11.2",
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
  const scopePath = new URL(self.registration.scope).pathname;
  if (url.origin !== self.location.origin || !url.pathname.startsWith(scopePath) || url.pathname.startsWith("/api/")) return;

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
