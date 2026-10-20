/* Label Check — service worker.
   Keeps the app files and the ingredient database on the phone so the app opens without internet.
   When you change any app file or the database, raise the version number below. */
const VERSION = 'label-check-v7';
const FILES = [
  './',
  'index.html',
  'style.css',
  'i18n.js',
  'db.js',
  'app.js',
  'manifest.json',
  'icon-192.png',
  'icon-512.png',
  'data/db-meta.json',
  'data/db-cosmetics.json',
  'data/db-food.json',
  'data/products.json'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(VERSION).then(c => c.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// App files: answer from the phone at once, then update the copy in the background.
// Database files (data/): answer from the phone only; they change only with a new VERSION (saves mobile data).
// Product lookups (other websites) are not touched here.
self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  const isData = url.pathname.includes('/data/');
  event.respondWith(
    caches.open(VERSION).then(async cache => {
      const cached = await cache.match(req, { ignoreSearch: true });
      if (cached && isData) return cached;
      const network = fetch(req)
        .then(res => { if (res && res.ok) cache.put(req, res.clone()); return res; })
        .catch(() => cached);
      return cached || network;
    })
  );
});
