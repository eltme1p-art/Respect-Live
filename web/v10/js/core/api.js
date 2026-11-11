// طبقة الاتصال + الحالة المشتركة + كاش (يعرض فوراً ثم يحدّث بالخلفية)

export class ApiError extends Error { constructor(msg, status, data) { super(msg); this.status = status; this.data = data || {}; } }

const bus = new EventTarget();
export const emit = (n, d) => bus.dispatchEvent(new CustomEvent(n, { detail: d }));
export const listen = (n, fn) => { const h = e => fn(e.detail); bus.addEventListener(n, h); return () => bus.removeEventListener(n, h); };

export async function api(path, opts = {}) {
  const o = { method: opts.method || 'GET', credentials: 'same-origin', headers: { accept: 'application/json' } };
  if (opts.body !== undefined) { o.headers['content-type'] = 'application/json'; o.body = JSON.stringify(opts.body); }
  if (opts.form) o.body = opts.form;
  const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), opts.timeout || 30000); o.signal = ctl.signal;
  let r;
  try { r = await fetch(path, o); }
  catch (e) { clearTimeout(t); throw new ApiError(navigator.onLine === false ? 'لا يوجد اتصال بالإنترنت' : e.name === 'AbortError' ? 'انتهت مهلة الاتصال — حاول مرة أخرى' : 'تعذّر الاتصال بالخادم', 0); }
  clearTimeout(t);
  if (opts.raw) return r;
  let j = {};
  try { j = await r.json(); } catch (e) {}
  if (!r.ok) {
    if (r.status === 401 && S.me && !opts.noAuthRedirect) emit('auth:lost');
    throw new ApiError(j.error || j.detail || ('خطأ ' + r.status), r.status, j);
  }
  return j;
}
export const post = (p, body) => api(p, { method: 'POST', body: body || {} });
export const patch = (p, body) => api(p, { method: 'PATCH', body: body || {} });
export const del = p => api(p, { method: 'DELETE' });
export async function upload(file, endpoint = '/api/upload', max = 2 * 1024 * 1024) {
  if (!file) throw new ApiError('لم تختر ملفاً', 400);
  if (file.size > max) throw new ApiError('الصورة أكبر من ' + Math.round(max / 1024 / 1024 * 10) / 10 + 'MB', 413);
  const fd = new FormData(); fd.append('file', file);
  return api(endpoint, { method: 'POST', form: fd, timeout: 60000 });
}
export function pickFile(accept = 'image/*') {
  return new Promise(res => { const i = document.createElement('input'); i.type = 'file'; i.accept = accept; i.onchange = () => res(i.files[0] || null); i.click(); });
}

// ─── الحالة المشتركة ───
export const S = {
  boot: window.__BOOT__ || {},
  me: null,
  guest: false,
  unread: 0,
  newsUnread: 0,
  pushOn: false,
  platform: 'kick',
};
export const isLogged = () => !!(S.me && S.me.user);
export const isOwner = () => isLogged() && S.me.user.role === 'owner';
export const canDiscord = () => isLogged() && (isOwner() || !!S.me.user.can_discord);
export const canWrite = () => isOwner() || !(S.me ? S.me.maintenance : S.boot.maintenance);
export const feat = k => !!(S.boot.features && S.boot.features[k]);
export const ttOn = () => !(S.boot.features && S.boot.features.tiktok_enabled === false);

// ─── كاش بسيط مع إعادة تحقق ───
const C = new Map();       // key -> {v, t, p}
export function peek(key) { const e = C.get(key); return e ? e.v : undefined; }
export function put(key, v) { C.set(key, { v, t: Date.now() }); emit('data:' + key, v); return v; }
export function drop(prefix) { for (const k of [...C.keys()]) if (k === prefix || k.startsWith(prefix)) C.delete(k); }
export async function load(key, url, maxAge = 15000) {
  const e = C.get(key);
  if (e && e.p) return e.p;
  if (e && Date.now() - e.t < maxAge) return e.v;
  const p = api(url).then(v => { C.set(key, { v, t: Date.now() }); emit('data:' + key, v); return v; })
    .catch(err => { const x = C.get(key); if (x) delete x.p; throw err; });
  C.set(key, { v: e ? e.v : undefined, t: e ? e.t : 0, p });
  try { return await p; } finally { const x = C.get(key); if (x) delete x.p; }
}
export const fresh = (key, url) => { drop(key); return load(key, url, 0); };

export const KIND = {
  kick: { name: 'كيك', path: '/kick', id: 'slug', ph: 'xqc', hint: 'اسم القناة كما في رابط kick.com، أو الصق الرابط كاملاً', btn: 'شاهد البث', live: true },
  yt: { name: 'يوتيوب', path: '/youtube', id: 'channel_id', ph: '@MrBeast', hint: 'اكتب @handle أو الصق رابط القناة', btn: 'شاهد الفيديو' },
  tw: { name: 'X', path: '/x', id: 'username', ph: '@username', hint: 'اكتب اليوزر أو الصق رابط الحساب. الحسابات المحمية لا يمكن متابعتها', btn: 'عرض التغريدة' },
  tt: { name: 'تيك توك', path: '/tiktok', id: 'slug', ph: '@username', hint: 'اكتب اليوزر أو الصق رابط الحساب — ننبهك عند بدء البث', btn: 'شاهد البث', live: true },
  tg: { name: 'تيليجرام', path: '/telegram', id: 'chat_id' },
  dc: { name: 'ديسكورد', path: '/discord' },
};
export const handleOf = (kind, r) => kind === 'yt' ? (r.handle || r.channel_id) : kind === 'tg' ? (r.username || r.chat_id) : '@' + (kind === 'tw' ? r.username : r.slug);
export const urlOf = (kind, r) => kind === 'kick' ? 'https://kick.com/' + r.slug : kind === 'tt' ? 'https://www.tiktok.com/@' + r.slug + (r.live ? '/live' : '') :
  kind === 'yt' ? (r.handle ? 'https://youtube.com/' + r.handle : 'https://youtube.com/channel/' + r.channel_id) : kind === 'tw' ? 'https://x.com/' + r.username :
  r.username ? 'https://t.me/' + String(r.username).replace('@', '') : '';
