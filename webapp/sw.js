const VERSION = 'v6';
const SHELL = `shell-${VERSION}`;
const DATA  = `data-${VERSION}`;
const RT    = `runtime-${VERSION}`;

const PRECACHE = ['/', '/manifest.webmanifest', '/icon.svg'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(SHELL)
      .then(c => c.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(n => !n.endsWith(VERSION)).map(n => caches.delete(n)));
    await self.clients.claim();
  })());
});

self.addEventListener('message', (e) => {
  if (e.data === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  if (url.pathname.startsWith('/_vercel/')) return;

  if (req.mode === 'navigate') {
    e.respondWith(networkFirstNav(req));
    return;
  }

  if (url.origin === location.origin && url.pathname.startsWith('/data/')) {
    e.respondWith(swr(req, DATA));
    return;
  }

  if (/fonts\.(googleapis|gstatic)\.com|cdn\.jsdelivr\.net/.test(url.host)) {
    e.respondWith(cacheFirst(req, RT));
    return;
  }

  if (url.origin === location.origin) {
    e.respondWith(cacheFirst(req, SHELL));
    return;
  }
});

async function networkFirstNav(req) {
  try {
    const res = await fetch(req);
    if (res.ok) {
      const cache = await caches.open(SHELL);
      cache.put('/', res.clone());
    }
    return res;
  } catch {
    const cache = await caches.open(SHELL);
    return (await cache.match('/')) || new Response('offline', { status: 503 });
  }
}

async function swr(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  const network = fetch(req).then(res => {
    if (res.ok) cache.put(req, res.clone());
    return res;
  }).catch(() => null);
  return cached || (await network) || new Response('offline', { status: 503 });
}

async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  if (cached) return cached;
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch {
    return new Response('offline', { status: 503 });
  }
}
