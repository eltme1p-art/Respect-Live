// هيكل التطبيق: الإقلاع، الشريط العلوي، التنقل، الشارات، السحب للتحديث
import { S, api, isLogged, isOwner, canDiscord, canWrite, ttOn, listen, put } from './core/api.js?v=__BUILD__';
import { html, raw, render, $, $$, ic, avatar, ls, esc } from './core/dom.js?v=__BUILD__';
import { toast, sheet, haptic } from './core/ui.js?v=__BUILD__';
import { initTheme, applyTheme, applyBlur, applyFeatures, uiMode, setLite, deviceWeak } from './core/theme.js?v=__BUILD__';
import { initRouter, show, navigate, setHooks, currentRoute, currentCtx, NAV_ORDER, prefetch, loadMod } from './core/router.js?v=__BUILD__';

const root = document.documentElement;
initTheme();

// ─── الشارات (تنبيهات/أخبار) ───
export function setBadges() {
  $$('[data-badge="notif"]').forEach(b => { b.textContent = S.unread > 99 ? '99+' : S.unread; b.hidden = !S.unread; });
  $$('[data-badge="news"]').forEach(b => { b.textContent = S.newsUnread; b.hidden = !S.newsUnread; });
  if ('setAppBadge' in navigator) { try { S.unread ? navigator.setAppBadge(S.unread) : navigator.clearAppBadge(); } catch (e) {} }
}
export async function refreshCounts() {
  if (!isLogged()) return;
  try { const r = await api('/api/notifs?count=1', { noAuthRedirect: true }); S.unread = r.unread || 0; setBadges(); } catch (e) {}
}
window.__rl = { setBadges, refreshCounts };

// ─── الهيكل ───
const TABS = () => [
  { k: 'home', href: '/', icon: 'home', t: 'الرئيسية' },
  { k: 'plat', href: '/platforms', icon: 'grid', t: 'المنصات' },
  { k: 'tg', href: '/telegram', icon: 'tg', t: 'تيليجرام' },
  { k: 'notif', href: '/notifications', icon: 'bell', t: 'التنبيهات', badge: 'notif' },
  { k: 'me', href: '/account', icon: 'user', t: isLogged() ? 'حسابي' : 'دخول' },
];

function brand() {
  const b = S.boot;
  return html`<a class="brand" href="/" aria-label="${b.site_name || 'Respect Live'}"><span class="brand-logo">${b.site_logo ? html`<img src="${b.site_logo}" alt="">` : ic('logo')}</span><span class="brand-name">${b.site_name || 'Respect Live'}</span></a>`;
}

function sidebar() {
  const L = (href, icn, t, extra = '') => html`<a class="side-link" href="${href}" data-nav-path="${href}">${ic(icn)}<span>${t}</span>${extra}</a>`;
  const u = S.me && S.me.user;
  return html`<nav class="sidebar blur" aria-label="التنقل">
    ${brand()}
    ${L('/', 'home', 'الرئيسية')}
    ${L('/live', 'signal', 'على الهواء')}
    <div class="side-sec">المنصات</div>
    ${L('/kick', 'kick', 'كيك')}${L('/youtube', 'yt', 'يوتيوب')}${L('/x', 'tw', 'X')}${ttOn() ? L('/tiktok', 'tt', 'تيك توك') : ''}${canDiscord() ? L('/discord', 'dc', 'ديسكورد') : ''}
    <div class="side-sec">التوصيل</div>
    ${L('/telegram', 'tg', 'تيليجرام')}${isLogged() ? L('/activity', 'activity', 'سجل الإرسال') : ''}
    <div class="side-sec">أنت</div>
    ${isLogged() ? L('/notifications', 'bell', 'التنبيهات', raw('<span class="badge" data-badge="notif" hidden></span>')) : ''}
    ${L('/news', 'megaphone', 'الأخبار', raw('<span class="badge" data-badge="news" hidden></span>'))}
    ${isOwner() ? L('/admin', 'shield', 'لوحة الإدارة') : ''}
    <div class="side-foot">${u ? html`<a class="side-link" href="/account" data-nav-path="/account" style="height:56px">${avatar(u.avatar, u.display || u.username, 'sm')}<span class="row-tx"><b>${u.display || u.username}</b><small class="ltr">@${u.username}</small></span></a>`
      : L('/login', 'login', 'تسجيل الدخول')}</div>
  </nav>`;
}

function topbar() {
  const logged = isLogged();
  return html`<header class="topbar blur" id="topbar"><div class="topbar-in">
    <button class="tbtn back" id="tbBack" hidden aria-label="رجوع">${ic('back')}</button>
    <div id="tbBrand">${brand()}</div>
    <div class="top-title clip" id="tbTitle" hidden></div>
    <div class="top-acts">
      <button class="tbtn" id="tbSearch" aria-label="بحث (Ctrl+K)" title="بحث — Ctrl+K">${ic('search')}</button>
      ${logged ? html`<button class="tbtn" id="tbSend" aria-label="إرسال رسالة" title="إرسال رسالة">${ic('send')}</button>` : ''}
      <a class="tbtn" href="/news" aria-label="الأخبار" title="الأخبار">${ic('megaphone')}<span class="badge" data-badge="news" hidden></span></a>
      ${logged ? '' : html`<a class="btn pri sm" href="/login">${ic('login')}دخول</a>`}
    </div></div></header>`;
}

function banners() {
  const b = S.boot, out = [];
  const mnt = S.me ? S.me.maintenance : b.maintenance;
  if (mnt && !isOwner()) out.push(html`<div class="banner mnt" role="status">${ic('wrench')}<div><b>${(S.me && S.me.maintenance_title) || b.maintenance_title || 'صيانة مؤقتة'}</b> ${(S.me && S.me.maintenance_text) || b.maintenance_text || 'التصفح متاح، والإضافة والإرسال متوقفان مؤقتاً.'}</div></div>`);
  if (b.announce_bar && ls.get('rl_ann_x', '') !== b.announce_bar) out.push(html`<div class="banner ann" id="annBar">${ic('megaphone')}<div class="grow">${b.announce_bar}</div><button class="x tbtn" style="width:30px;height:30px" aria-label="إخفاء" id="annX">${ic('x')}</button></div>`);
  return out;
}

export function renderShell() {
  const app = document.getElementById('app');
  const tabs = TABS();
  render(app, html`
    <div class="shell">
      ${sidebar()}
      <div class="main">
        <div id="banners">${banners()}</div>
        <div id="offline" class="banner off" hidden>${ic('wifiOff')} لا يوجد اتصال — نعرض آخر بيانات محفوظة</div>
        ${topbar()}
        <main id="view" tabindex="-1"></main>
      </div>
    </div>
    <nav class="tabbar blur" id="tabbar" style="--n:${tabs.length}" aria-label="التنقل الرئيسي">
      <div class="lens"></div>
      ${tabs.map(t => html`<a class="tab" href="${t.href}" data-tab="${t.k}" aria-label="${t.t}">${ic(t.icon)}<span>${t.t}</span>${t.badge ? raw('<span class="badge" data-badge="' + t.badge + '" hidden></span>') : ''}</a>`)}
    </nav>
    <div class="ptr" id="ptr">${ic('refresh')}</div>`);
  $('#tbSearch').onclick = () => openPalette();
  const sb = $('#tbSend'); if (sb) sb.onclick = () => openCompose();
  $('#tbBack').onclick = () => { const r = currentRoute(); navigate((r && r.back) || '/'); };
  const ax = $('#annX'); if (ax) ax.onclick = () => { ls.set('rl_ann_x', S.boot.announce_bar); $('#annBar').remove(); };
  $$('#tabbar .tab').forEach(t => t.addEventListener('click', () => haptic()));
  setBadges();
}

function syncChrome(route) {
  root.classList.toggle('bare', !!route.bare);
  const tb = $('#tabbar'); if (!tb) return;
  const idx = NAV_ORDER.indexOf(route.nav);
  tb.classList.toggle('none', idx < 0);
  tb.style.setProperty('--i', Math.max(0, idx));
  $$('.tab', tb).forEach(t => { const on = t.dataset.tab === route.nav; t.classList.toggle('on', on); on ? t.setAttribute('aria-current', 'page') : t.removeAttribute('aria-current'); });
  $$('.side-link').forEach(a => { const p = a.dataset.navPath; const on = p === location.pathname || (p === '/admin' && location.pathname.startsWith('/admin')); a.classList.toggle('on', on); on ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current'); });
  const home = route.p === '/';
  $('#tbBrand').hidden = !home;
  $('#tbTitle').hidden = home;
  $('#tbBack').hidden = !route.back;
  if (!home) $('#tbTitle').textContent = route.t || '';
  const fab = $('#fab'); if (fab) fab.remove();
}

function setTitle(t) {
  const el = $('#tbTitle'); if (el) el.textContent = t;
  document.title = t + ' — ' + (S.boot.site_name || 'Respect Live');
}

// ─── التحكم بالشريط العلوي عند التمرير ───
let ticking = false;
addEventListener('scroll', () => {
  if (ticking) return; ticking = true;
  requestAnimationFrame(() => { const t = $('#topbar'); if (t) t.classList.toggle('scrolled', scrollY > 6); ticking = false; });
}, { passive: true });

// ─── سحب للتحديث (جوال) ───
(function ptr() {
  let y0 = null, d = 0, active = false;
  addEventListener('touchstart', e => { if (scrollY > 0 || document.documentElement.style.overflow === 'hidden' || e.touches.length > 1) { y0 = null; return; } y0 = e.touches[0].clientY; d = 0; }, { passive: true });
  addEventListener('touchmove', e => {
    if (y0 == null || active) return;
    d = e.touches[0].clientY - y0;
    const p = $('#ptr'); if (!p) return;
    if (d > 8 && scrollY <= 0) { const k = Math.min(1, d / 90); p.style.opacity = k; p.style.transform = 'translateY(' + (Math.min(d, 110) * .6 - 40) + 'px) rotate(' + d * 3 + 'deg)'; }
  }, { passive: true });
  addEventListener('touchend', async () => {
    const p = $('#ptr'); if (y0 == null || !p) return; y0 = null;
    if (d > 90 && !active) {
      active = true; haptic(12); p.classList.add('spin'); p.style.transform = 'translateY(26px)';
      const ctx = currentCtx();
      try { if (ctx && ctx._refresh) await ctx._refresh(); else if (ctx) await ctx.rerender(); await refreshCounts(); } catch (e) {}
      p.classList.remove('spin'); active = false;
    }
    p.style.transition = 'transform .3s, opacity .3s'; p.style.opacity = 0; p.style.transform = 'translateY(-60px)';
    setTimeout(() => { p.style.transition = ''; }, 320);
  }, { passive: true });
})();

// ─── لوحة الأوامر والمرسل (تُحمّل عند الحاجة) ───
export async function openPalette() { const m = await import('./components/palette.js?v=__BUILD__'); m.open(); }
export async function openCompose(pre) { if (!canWrite()) return toast('الموقع في صيانة — الإرسال متوقف مؤقتاً', 'bad'); const m = await import('./components/compose.js?v=__BUILD__'); m.open(pre); }
window.__rl.openCompose = openCompose;
window.__rl.openPalette = openPalette;
addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); }
  else if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && !document.querySelector('.sheet-wrap')) {
    const s = document.querySelector('.page .search input'); if (s) { e.preventDefault(); s.focus(); }
  }
});

// ─── الإقلاع ───
async function loadMe() {
  try { S.me = await api('/api/me', { noAuthRedirect: true }); S.guest = false; }
  catch (e) { S.me = null; S.guest = true; if (e.status && e.status !== 401) console.warn(e); }
}

function hideSplash() { const s = $('#splash'); if (s) { s.classList.add('out'); setTimeout(() => s.remove(), 500); } }

async function boot() {
  const meP = loadMe();
  // نحمّل ملف الصفحة الحالية بالتوازي مع بيانات المستخدم
  const r0 = location.pathname;
  try { prefetch(r0); } catch (e) {}
  await meP;
  if (S.me && S.me.user.ui_mode && !uiMode()) setLite(S.me.user.ui_mode === 'lite');
  renderShell();
  setHooks({
    before: syncChrome, title: setTitle,
    fatal: () => render($('#view'), html`<div class="empty"><div class="ic">${ic('wifiOff')}</div><h3>تعذّر تحميل الصفحة</h3><p>تحقق من اتصالك ثم أعد المحاولة.</p><button class="btn soft" onclick="location.reload()">${ic('refresh')} إعادة التحميل</button></div>`),
    pageError: (ctx, e) => { if (ctx.alive()) render(ctx.root, html`<div class="empty"><div class="ic">${ic('warn')}</div><h3>حدث خطأ في هذه الصفحة</h3><p>${e.message || ''}</p><button class="btn soft" data-reload>${ic('refresh')} إعادة المحاولة</button></div>`); const b = ctx.root.querySelector('[data-reload]'); if (b) b.onclick = () => ctx.rerender(); },
  });
  initRouter();
  await show();
  hideSplash();
  if (isLogged()) afterLogin();
  // تحميل مسبق لباقي الصفحات وقت الفراغ
  const idle = window.requestIdleCallback || (f => setTimeout(f, 1200));
  idle(() => ['home', 'channels', 'telegram', 'notifications', 'account'].forEach(m => loadMod(m).catch(() => {})));
}

async function afterLogin() {
  refreshCounts();
  setInterval(() => { if (document.visibilityState === 'visible') refreshCounts(); }, 45000);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') refreshCounts(); });
  try { const n = await api('/api/news'); S.newsUnread = n.unread_count || 0; put('news', n); setBadges(); if (S.newsUnread && !sessionStorage.getItem('rl_news_seen')) setTimeout(() => newsPopup(n.rows.filter(x => !x.is_read)), 900); } catch (e) {}
  await askUiModeOnce();
  try { if (sessionStorage.getItem('rl_intro') === '1') { sessionStorage.removeItem('rl_intro'); if (S.me.login_anim && !root.classList.contains('lite')) { const a = await api('/api/login-anim'); if (a.enabled && a.code) { const m = await import('./components/intro.js?v=__BUILD__'); m.play(a.code, a.secs); } } } } catch (e) {}
  try { const w = sessionStorage.getItem('rl_welcome'); if (w) { sessionStorage.removeItem('rl_welcome'); setTimeout(() => toast(w, 'ok', { ms: 6000 }), 600); } } catch (e) {}
  if ('serviceWorker' in navigator) {
    try { const reg = await navigator.serviceWorker.ready; S.pushOn = !!(await reg.pushManager?.getSubscription()); } catch (e) {}
  }
}

async function askUiModeOnce() {
  if (uiMode() || !S.boot.ui_mode_prompt || (S.me.user.ui_mode)) return;
  const weak = deviceWeak();
  const v = await sheet({
    title: 'اختر طريقة العرض', sub: 'تختارها مرة واحدة لهذا الجهاز، وتقدر تغيّرها من «حسابي» متى شئت.', size: 'sm', dismiss: false, x: false,
    body: html`<div class="picks">
      <button class="pick ${weak ? '' : 'on'}" data-v="full"><span class="pi">${ic('sparkle')}</span><span class="row-tx"><b>الكامل${weak ? '' : ' (مقترح)'}</b><small>ضبابية وحركة ناعمة بين الصفحات</small></span><span class="ck">${ic('check')}</span></button>
      <button class="pick ${weak ? 'on' : ''}" data-v="lite"><span class="pi ok">${ic('bolt')}</span><span class="row-tx"><b>الخفيف${weak ? ' (مقترح لجهازك)' : ''}</b><small>أسرع وأقل استهلاكاً للبطارية</small></span><span class="ck">${ic('check')}</span></button></div>`,
    actions: [{ label: 'متابعة', kind: 'pri', handler: ({ root }) => root.querySelector('.pick.on').dataset.v }],
    onMount: ({ root }) => root.addEventListener('click', e => { const p = e.target.closest('.pick'); if (!p) return; root.querySelectorAll('.pick').forEach(x => x.classList.toggle('on', x === p)); }),
  });
  setLite(v === 'lite');
  api('/api/me/ui-mode', { method: 'POST', body: { mode: v || 'full' } }).catch(() => {});
}

async function newsPopup(rows) {
  if (!rows || !rows.length) return;
  try { sessionStorage.setItem('rl_news_seen', '1'); } catch (e) {}
  const { newsCard } = await import('./pages/news.js?v=__BUILD__');
  const r = await sheet({ title: rows.length === 1 ? 'إعلان جديد' : rows.length + ' إعلانات جديدة', size: 'wide', body: html`<div class="stack">${rows.slice(0, 4).map(n => newsCard(n))}</div>`,
    actions: [{ label: 'لاحقاً', kind: 'ghost', value: false }, { label: 'قرأتها', kind: 'pri', value: true }] });
  if (r) { try { await api('/api/news/read-all', { method: 'POST' }); S.newsUnread = 0; setBadges(); } catch (e) {} }
}

listen('auth:lost', () => { if (!S.me) return; S.me = null; S.guest = true; toast('انتهت الجلسة — سجّل دخولك من جديد', 'bad'); renderShell(); navigate('/login?next=' + encodeURIComponent(location.pathname), { replace: true }); });
listen('badges', setBadges);
listen('me:changed', () => { renderShell(); const r = currentRoute(); if (r) syncChrome(r); });
addEventListener('online', () => { const o = $('#offline'); if (o) o.hidden = true; });
addEventListener('offline', () => { const o = $('#offline'); if (o) o.hidden = false; });

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
  navigator.serviceWorker.addEventListener('message', e => { if (e.data && e.data.t === 'push') { refreshCounts(); window.dispatchEvent(new CustomEvent('rl:push')); } });
}

boot().catch(e => { console.error(e); hideSplash(); });
