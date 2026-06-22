// commonplace — service worker: cache static assets + push notifications
const CACHE = "commonplace-v2";
const PRECACHE = [
  "/static/style.css",
  "/static/themes.css",
  "/static/logo-32.png",
  "/static/logo-128.png",
  "/static/manifest.json",
];

// ── Install: precache static assets ──────────────────────────
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

// ── Activate: clean old caches ───────────────────────────────
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// ── Fetch: cache static assets ───────────────────────────────
self.addEventListener("fetch", (event) => {
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

// ── Push: receive and display notification ───────────────────
self.addEventListener("push", (event) => {
  let data = { title: "commonplace", body: "", icon: "/static/logo-128.png", url: "/review" };
  try {
    if (event.data) {
      data = Object.assign(data, event.data.json());
    }
  } catch (e) {
    // ignore malformed payload
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: data.icon,
      data: { url: data.url },
    })
  );
});

// ── Notification click: navigate to the intended page ────────
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data && event.notification.data.url
    ? event.notification.data.url
    : "/review";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      // Focus an existing tab if one is open on the target
      for (const client of clientList) {
        if (client.url === url && "focus" in client) {
          return client.focus();
        }
      }
      // Otherwise open a new tab
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});
