// PPL 2026 Service Worker — Production Grade
// PART 6: Reliable PWA caching
// - Static assets: Cache-first (instant load)
// - HTML pages: Network-first (always fresh)
// - API calls: Never cached (always live)
// - SSE stream: Never intercepted (must stay open)

const CACHE_NAME = "ppl2026-cache-v3";

const STATIC_ASSETS = [
  "/manifest.json",
  "/icons/icon-192.png",
  "/icons/icon-512.png"
];

// Install: pre-cache only static assets (not index.html — use network-first for HTML)
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// Activate: clean up old caches
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys
          .filter(k => k !== CACHE_NAME)
          .map(k => caches.delete(k))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);

  // Never intercept non-GET requests
  if (event.request.method !== "GET") return;

  // CRITICAL: Never cache or intercept API calls or SSE stream
  // This prevents stale data and keeps SSE connections alive
  if (url.pathname.startsWith("/api/")) return;

  // For HTML navigation requests: Network-first, fallback to cache
  // This ensures the app always loads the latest HTML
  if (event.request.mode === "navigate" || url.pathname === "/" || url.pathname.endsWith(".html")) {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => caches.match(event.request).then(cached => cached || caches.match("/")))
    );
    return;
  }

  // For static assets (icons, manifest): Cache-first for instant load
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;

      return fetch(event.request)
        .then(response => {
          if (!response || response.status !== 200) return response;

          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, clone);
          });

          return response;
        })
        .catch(() => caches.match("/"));
    })
  );
});
