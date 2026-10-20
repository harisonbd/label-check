/* Label Check — service worker.
   Keeps the app files and the ingredient database on the phone so the app opens without internet.
   When you change any app file or the database, raise the version number below. */
const VERSION = 'label-check-v9';
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
  event.waitUntil(caches.open(VERSION).then(c => c.addAll(FILES.map(f => new Request(f, { cache: 'reload' })))).then(() => self.skipWaiting()));
});

// Reader files (ocr/) are not in FILES: they come only when you first use "Read text" (about 4 MB).
// They never change under the same name, so a new VERSION takes them over from the old cache.
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = (await caches.keys()).filter(k => k !== VERSION);
    const now = await caches.open(VERSION);
    for (const k of keys) {
      const old = await caches.open(k);
      for (const req of await old.keys()) {
        if (new URL(req.url).pathname.includes('/ocr/')) await now.put(req, await old.match(req));
      }
      await caches.delete(k);
    }
    await self.clients.claim();
  })());
});

// App files: answer from the phone at once, then update the copy in the background.
// Database files (data/) and reader files (ocr/): answer from the phone only; data/ changes only with a new
// VERSION, ocr/ only with a new folder name (saves mobile data).
// Product lookups (other websites) are not touched here.
self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  const isData = url.pathname.includes('/data/') || url.pathname.includes('/ocr/');
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
