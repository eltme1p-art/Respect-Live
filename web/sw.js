// Service Worker — يجعل الموقع يعمل كتطبيق حقيقي:
//  • الهيكل (الصفحة) يُفتح فوراً من التخزين ثم يُحدَّث في الخلفية (stale-while-revalidate)
//  • الخطوط والصور تُخزَّن على الجهاز (لا إعادة تحميل، وتعمل بلا إنترنت)
//  • لا skipWaiting ولا clients.claim → لا يتبدّل شيء أثناء الاستخدام ولا إعادة تحميل مفاجئة
//  • إذا نزل تحديث جديد نُخبر الصفحة برسالة، والمستخدم هو من يقرر متى يحدّث
const SHELL = 'rl-shell', FONTS = 'rl-fonts', IMG = 'rl-img';
const KEEP = [SHELL, FONTS, IMG];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(c => c.add(new Request('/', { cache: 'reload' }))).catch(() => {}));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith('rl-') && !KEEP.includes(k)).map(k => caches.delete(k)))));
});

async function tell(msg) {
  const cs = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  cs.forEach(c => c.postMessage(msg));
}

// صفحة التطبيق: من الكاش فوراً، وتُحدَّث بالخلفية؛ إن اختلفت عن المخزّنة نُخبر الصفحة
async function shell(req) {
  const cache = await caches.open(SHELL);
  const cached = await cache.match('/');
  const net = fetch(new Request('/', { cache: 'no-cache', credentials: 'same-origin' })).then(async res => {
    if (res && res.ok) {
      const copy = res.clone();
      if (cached) {
        try {
          const [a, b] = await Promise.all([cached.clone().text(), res.clone().text()]);
          if (a !== b) tell({ t: 'update' });
        } catch (x) {}
      }
      await cache.put('/', copy);
    }
    return res;
  }).catch(() => null);
  if (cached) { net.catch(() => {}); return cached; }
  const res = await net;
  return res || new Response('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body style="background:#030508;color:#fff;font-family:sans-serif;display:grid;place-items:center;height:100vh;margin:0"><div style="text-align:center"><h2>لا يوجد اتصال</h2><p>افتح التطبيق مرة واحدة وأنت متصل ليُحفظ على جهازك.</p></div>', { status: 503, headers: { 'content-type': 'text/html; charset=utf-8' } });
}

// الأصول الثابتة: من الكاش أولاً، وإن لم توجد تُجلب وتُحفظ
async function cacheFirst(req, name) {
  const c = await caches.open(name);
  const h = await c.match(req);
  if (h) return h;
  const res = await fetch(req);
  if (res && (res.ok || res.type === 'opaque')) c.put(req, res.clone());
  return res;
}
// الخطوط: من الكاش فوراً مع تحديث بالخلفية
async function swr(req, name) {
  const c = await caches.open(name);
  const h = await c.match(req);
  const net = fetch(req).then(res => { if (res && (res.ok || res.type === 'opaque')) c.put(req, res.clone()); return res; }).catch(() => null);
  return h || (await net) || Response.error();
}

self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.method !== 'GET') return;
  const u = new URL(r.url);
  if (u.hostname === 'fonts.googleapis.com') { e.respondWith(swr(r, FONTS)); return; }
  if (u.hostname === 'fonts.gstatic.com') { e.respondWith(cacheFirst(r, FONTS)); return; }
  if (u.origin !== location.origin) return;
  if (r.mode === 'navigate') {
    if (u.pathname.startsWith('/api/')) return;
    e.respondWith(shell(r));
    return;
  }
  if (u.pathname.startsWith('/api/image/')) { e.respondWith(cacheFirst(r, IMG)); return; }
  if (u.pathname === '/favicon.ico' || u.pathname === '/manifest.json' || u.pathname.startsWith('/assets/')) { e.respondWith(swr(r, SHELL)); }
});

self.addEventListener('push', e => {
  let d = {};
  try { d = e.data.json(); } catch (x) { d = { title: 'تنبيه', body: e.data ? e.data.text() : '' }; }
  const o = { body: d.body || '', icon: '/favicon.ico', badge: '/favicon.ico', image: d.image || undefined, tag: d.tag || undefined, renotify: !!d.tag, dir: 'rtl', lang: 'ar', data: { url: d.url || '/notifications' } };
  e.waitUntil(Promise.all([
    self.registration.showNotification(d.title || 'تنبيه', o),
    tell({ t: 'push' }),
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
