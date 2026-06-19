// commonplace — service worker: cache static assets for offline use
const CACHE = "commonplace-v1";
const PRECACHE = [
  "/static/style.css",
  "/static/themes.css",
  "/static/logo-32.png",
  "/static/logo-128.png",
  "/static/manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  // Only cache same-origin GET requests for static assets
  const url = new URL(event.request.url);
  if (
    event.request.method === "GET" &&
    url.origin === self.location.origin &&
    url.pathname.startsWith("/static/")
  ) {
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request).then((r) => {
        const clone = r.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, clone));
        return r;
      }))
    );
  }
});
