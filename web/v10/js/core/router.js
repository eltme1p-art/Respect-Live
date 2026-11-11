// الموجّه: كل صفحة لها رابط حقيقي وملف مستقل يُحمّل عند الحاجة، مع انتقال سلس
import { S, isLogged, isOwner, canDiscord, emit } from './api.js?v=__BUILD__';
import { closeTopFromHistory, sheetOpen } from './ui.js?v=__BUILD__';
import { sleep } from './dom.js?v=__BUILD__';

const V = '?v=__BUILD__';
export const ROUTES = [
  { p: '/', m: 'home', t: 'الرئيسية', nav: 'home' },
  { p: '/live', m: 'live', t: 'على الهواء', nav: 'home', back: '/' },
  { p: '/kick', m: 'channels', t: 'كيك', nav: 'plat', kind: 'kick' },
  { p: '/youtube', m: 'channels', t: 'يوتيوب', nav: 'plat', kind: 'yt' },
  { p: '/x', m: 'channels', t: 'X', nav: 'plat', kind: 'tw' },
  { p: '/tiktok', m: 'channels', t: 'تيك توك', nav: 'plat', kind: 'tt' },
  { p: '/discord', m: 'discord', t: 'ديسكورد', nav: 'plat', need: 'discord' },
  { p: '/telegram', m: 'telegram', t: 'تيليجرام', nav: 'tg' },
  { p: '/activity', m: 'activity', t: 'سجل الإرسال', nav: 'tg', auth: true },
  { p: '/notifications', m: 'notifications', t: 'التنبيهات', nav: 'notif', auth: true },
  { p: '/news', m: 'news', t: 'الأخبار', nav: 'notif' },
  { p: '/account', m: 'account', t: 'حسابي', nav: 'me' },
  { p: '/login', m: 'login', t: 'تسجيل الدخول', bare: true },
  { p: '/register', m: 'login', t: 'حساب جديد', bare: true, mode: 'register' },
  { p: '/admin', m: 'admin/hub', t: 'لوحة الإدارة', nav: 'me', owner: true, back: '/account' },
  ...['users', 'defaults', 'x', 'suggestions', 'news', 'settings', 'system', 'appearance', 'ai', 'stats', 'security']
    .map(s => ({ p: '/admin/' + s, m: 'admin/' + s, t: '', nav: 'me', owner: true, back: '/admin', section: s })),
];
export const NAV_ORDER = ['home', 'plat', 'tg', 'notif', 'me'];

const mods = new Map();
export function loadMod(m) {
  if (!mods.has(m)) mods.set(m, import('../pages/' + m + '.js' + V).catch(e => { mods.delete(m); throw e; }));
  return mods.get(m);
}
export const prefetch = path => { const r = match(path); if (r) loadMod(r.route.m).catch(() => {}); };

export function match(path) {
  path = (path || '/').split('?')[0].split('#')[0].replace(/\/+$/, '') || '/';
  if (path === '/platforms') path = ({ kick: '/kick', yt: '/youtube', tw: '/x', tt: '/tiktok', dc: '/discord' })[S.platform] || '/kick';
  const route = ROUTES.find(r => r.p === path);
  return route ? { route, path } : null;
}

let current = null;       // { route, ctx, el }
let navId = 0;
let hooks = {};
export const currentRoute = () => current && current.route;
export const currentCtx = () => current && current.ctx;
export function setHooks(h) { hooks = h; }

const scrolls = new Map();
let key = (history.state && history.state.k) || Math.random().toString(36).slice(2);
try { history.replaceState({ ...(history.state || {}), k: key }, ''); } catch (e) {}
if ('scrollRestoration' in history) history.scrollRestoration = 'manual';

async function waitPop() { for (let i = 0; i < 25 && window.__rlSkipPop > 0; i++) await sleep(20); }

export async function navigate(to, o = {}) {
  if (window.__rlSkipPop > 0) await waitPop();
  const url = new URL(to, location.origin);
  if (url.origin !== location.origin) { location.href = to; return; }
  const target = url.pathname + url.search;
  if (!o.replace && !o.pop && target === location.pathname + location.search && current) { scrollTo({ top: 0, behavior: 'smooth' }); return; }
  scrolls.set(key, scrollY);
  if (!o.pop) {
    key = Math.random().toString(36).slice(2);
    try { history[o.replace ? 'replaceState' : 'pushState']({ k: key }, '', target); } catch (e) { location.href = target; return; }
  }
  await show(o);
}

function guard(m) {
  const r = m.route;
  if (r.bare && isLogged()) return '/';
  if ((r.auth || r.owner) && !isLogged()) return '/login?next=' + encodeURIComponent(location.pathname);
  if (r.owner && !isOwner()) return '/';
  if (r.need === 'discord' && !canDiscord()) return isLogged() ? '/kick' : '/login?next=/discord';
  if (!isLogged() && !S.boot.guest_mode && !r.bare) return '/login';
  return null;
}

export async function show(o = {}) {
  const my = ++navId;
  let m = match(location.pathname);
  if (!m) { history.replaceState({ k: key }, '', '/'); m = match('/'); }
  if (m.path !== location.pathname.replace(/\/+$/, '') && m.path !== '/') { try { history.replaceState(history.state, '', m.path + location.search); } catch (e) {} }
  const redir = guard(m);
  if (redir) { await navigate(redir, { replace: true }); return; }
  if (m.route.kind) S.platform = m.route.kind;
  if (m.route.p === '/discord') S.platform = 'dc';

  let mod;
  try { mod = (await loadMod(m.route.m)).default; }
  catch (e) { console.error(e); if (!o.retried) { mods.delete(m.route.m); return show({ ...o, retried: true }); } return hooks.fatal && hooks.fatal(e); }
  if (my !== navId) return;

  const prev = current;
  const fromIdx = prev ? NAV_ORDER.indexOf(prev.route.nav) : -1, toIdx = NAV_ORDER.indexOf(m.route.nav);
  let dir = '';
  if (prev && prev.route.bare !== m.route.bare) dir = '';
  else if (o.pop) dir = 'back';
  else if (fromIdx >= 0 && toIdx >= 0 && fromIdx !== toIdx) dir = toIdx > fromIdx ? 'fwd' : 'back';
  else if (prev && m.route.back === prev.route.p) dir = 'fwd';
  else if (prev && prev.route.back === m.route.p) dir = 'back';

  const cleanups = [];
  const el = document.createElement('section');
  el.className = 'page';
  const ctx = {
    root: el, route: m.route, path: m.path, query: new URLSearchParams(location.search), params: { kind: m.route.kind, mode: m.route.mode, section: m.route.section },
    alive: () => current && current.ctx === ctx,
    cleanup: fn => cleanups.push(fn),
    onRefresh: fn => { ctx._refresh = fn; },
    setTitle: t => hooks.title && hooks.title(t, m.route),
    rerender: () => Promise.resolve(mod.render(ctx)).catch(err => console.error(err)),
  };
  ctx._cleanups = cleanups;

  const restoreY = o.pop ? (scrolls.get(key) || 0) : 0;
  const swap = async () => {
    if (prev) { prev.ctx._cleanups.forEach(f => { try { f(); } catch (e) {} }); }
    if (hooks.before) hooks.before(m.route, prev && prev.route);
    const view = document.getElementById('view');
    if (!view) return;
    view.replaceChildren(el);
    current = { route: m.route, ctx, el };
    document.title = (m.route.t ? m.route.t + ' — ' : '') + (S.boot.site_name || 'Respect Live');
    let p;
    try { p = Promise.resolve(mod.render(ctx)); } catch (e) { p = Promise.reject(e); }
    p.catch(e => { console.error(e); hooks.pageError && hooks.pageError(ctx, e); });
    await Promise.race([p, sleep(m.route.bare ? 40 : 140)]);
    window.scrollTo(0, restoreY);
  };

  const root = document.documentElement;
  const canVT = document.startViewTransition && prev && !root.classList.contains('no-motion') && !matchMedia('(prefers-reduced-motion: reduce)').matches && document.visibilityState === 'visible';
  if (canVT) {
    root.dataset.nav = dir;
    try { const vt = document.startViewTransition(swap); await vt.updateCallbackDone; vt.finished.finally(() => { if (root.dataset.nav === dir) delete root.dataset.nav; }); }
    catch (e) { await swap(); }
  } else {
    await swap();
    if (prev && !root.classList.contains('no-motion')) el.classList.add('page-enter');
  }
  emit('route', m.route);
}

export function initRouter() {
  window.addEventListener('popstate', e => {
    if (window.__rlSkipPop > 0) { window.__rlSkipPop--; return; }
    if (sheetOpen()) { closeTopFromHistory(); return; }
    scrolls.set(key, scrollY);
    key = (e.state && e.state.k) || key;
    show({ pop: true });
  });
  document.addEventListener('click', e => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target.closest('a[href]');
    if (!a || a.target === '_blank' || a.hasAttribute('download') || a.dataset.native != null) return;
    const href = a.getAttribute('href');
    if (!href.startsWith('/') || href.startsWith('//') || href.startsWith('/api/') || href.startsWith('/assets/')) return;
    e.preventDefault();
    navigate(href);
  });
  const pf = e => { const a = e.target.closest && e.target.closest('a[href^="/"]'); if (a) prefetch(a.getAttribute('href')); };
  document.addEventListener('pointerover', pf, { passive: true });
  document.addEventListener('touchstart', pf, { passive: true });
}
