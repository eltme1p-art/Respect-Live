// Service Worker — تثبيت سريع، كاش ذكي، وإشعارات
const PWA = '__PWA__' === '1';
const V = 'rl-__BUILD__';
const SHELL = ['/', '/assets/css/app.css?v=__BUILD__', '/assets/js/app.js?v=__BUILD__'];

self.addEventListener('install', e => {
  self.skipWaiting();
  if (PWA) e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).catch(() => {}));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith('rl-') && k !== V && k !== 'rl-img').map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const r = e.request;
  if (!PWA || r.method !== 'GET') return;
  const u = new URL(r.url);
  if (u.origin !== location.origin) return;
  // صفحات التطبيق: الشبكة أولاً، والكاش عند انقطاع الاتصال
  if (r.mode === 'navigate') {
    e.respondWith(fetch(r).then(res => { if (res.ok) caches.open(V).then(c => c.put('/', res.clone())); return res; }).catch(() => caches.match('/')));
    return;
  }
  // ملفات الواجهة (مختومة بالإصدار): الكاش أولاً
  if (u.pathname.startsWith('/assets/')) {
    e.respondWith(caches.open(V).then(c => c.match(r).then(h => h || fetch(r).then(res => { if (res.ok) c.put(r, res.clone()); return res; }))));
    return;
  }
  // الصور: من الكاش فوراً ثم تُحدّث
  if (u.pathname.startsWith('/api/image/')) {
    e.respondWith(caches.open('rl-img').then(c => c.match(r).then(h => h || fetch(r).then(res => { if (res.ok) c.put(r, res.clone()); return res; }))));
  }
});

self.addEventListener('push', e => {
  let d = {};
  try { d = e.data.json(); } catch (x) { d = { title: 'تنبيه', body: e.data ? e.data.text() : '' }; }
  const o = { body: d.body || '', icon: '/favicon.ico', badge: '/favicon.ico', image: d.image || undefined, tag: d.tag || undefined, renotify: !!d.tag, dir: 'rtl', lang: 'ar', data: { url: d.url || '/notifications' } };
  e.waitUntil(Promise.all([
    self.registration.showNotification(d.title || 'تنبيه', o),
    self.clients.matchAll({ type: 'window' }).then(cs => cs.forEach(c => c.postMessage({ t: 'push' }))),
  ]));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(cs => {
    const same = cs.find(c => new URL(c.url).origin === location.origin);
    if (url.startsWith('/') && same) { same.focus(); same.navigate ? same.navigate(url) : 0; return; }
    return self.clients.openWindow(url);
  }));
});
