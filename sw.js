/* Label Check — service worker.
   Keeps the app files and the ingredient database on the phone so the app opens without internet.
   When you change any app file or the database, raise the version number below. */
const VERSION = 'label-check-v23';
const SHARE = 'lc-share';   // a photo shared to the app waits here until the page picks it up
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
    // Other apps on this website (Pocket Docs, Sun Launcher) share Cache Storage: touch only our own old caches.
    const keys = (await caches.keys()).filter(k => k.startsWith('label-check-') && k !== VERSION);
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
  // Gallery -> Share -> Label Check: keep the photo, then open "Read a label" with it.
  if (req.method === 'POST' && url.origin === self.location.origin && url.pathname.endsWith('/share-target')) {
    event.respondWith((async () => {
      try {
        const file = (await req.formData()).get('photo');
        if (file && file.size) {
          const c = await caches.open(SHARE);
          await c.put('shared-photo', new Response(file, { headers: { 'Content-Type': file.type || 'image/jpeg' } }));
        }
      } catch (e) { /* no photo: open the app normally */ }
      return Response.redirect(new URL('./?shared=1', self.registration.scope).href, 303);
    })());
    return;
  }
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
