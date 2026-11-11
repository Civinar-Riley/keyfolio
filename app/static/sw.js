/* Keyfolio Service Worker：静态资源 cache-first，API 永远走网络。 */
const CACHE = "keyfolio-v1";
const PRECACHE = [
  "/",
  "/css/app.css",
  "/js/app.js",
  "/js/api.js",
  "/js/bus.js",
  "/js/views/auth.js",
  "/js/views/channels.js",
  "/js/views/dashboard.js",
  "/js/views/quickadd.js",
  "/js/views/export.js",
  "/js/views/settings.js",
  "/vendor/vue.esm-browser.prod.js",
  "/vendor/chart.umd.js",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.pathname.startsWith("/api")) return;
  // network-first：本地服务在线时永远拿最新代码，离线时回退缓存
  event.respondWith(
    fetch(event.request)
      .then((resp) => {
        if (resp && resp.ok) {
          const copy = resp.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        }
        return resp;
      })
      .catch(() =>
        caches.match(event.request).then((hit) => hit || Response.error())
      )
  );
});
