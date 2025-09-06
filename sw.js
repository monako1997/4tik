// اسم الكاش
const CACHE_NAME = '4tikpro-v1';

// الملفات الثابتة اللي نخزنها في الكاش
const ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png'
  // 👉 أضف هنا أي ملفات ثابتة ثانية (مثلاً /script.js أو /style.css) لو عندك
];

// مرحلة التنصيب: نخزن الملفات في الكاش
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

// مرحلة التفعيل: نحذف أي كاش قديم
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// جلب الملفات: نحاول من النت أولاً، وإذا فشل نرجع من الكاش
self.addEventListener('fetch', (event) => {
  const req = event.request;

  // فقط طلبات GET
  if (req.method !== 'GET') return;

  event.respondWith(
    fetch(req)
      .then((res) => {
        const resClone = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(req, resClone));
        return res;
      })
      .catch(() => caches.match(req).then((cached) => cached || caches.match('/index.html')))
  );
});