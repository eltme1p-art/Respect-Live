// لوحة الأوامر (Ctrl+K): بحث في الصفحات وقنواتك والإجراءات
import { S, isLogged, isOwner, canDiscord, ttOn, load, KIND, handleOf } from '../core/api.js?v=__BUILD__';
import { html, raw, $, ic, esc, avatar } from '../core/dom.js?v=__BUILD__';
import { sheet } from '../core/ui.js?v=__BUILD__';
import { navigate } from '../core/router.js?v=__BUILD__';
import { setScheme, scheme } from '../core/theme.js?v=__BUILD__';

const norm = s => String(s || '').toLowerCase().replace(/[أإآ]/g, 'ا').replace(/ة/g, 'ه').replace(/ى/g, 'ي').replace(/[@\s_.-]/g, '');

function staticItems() {
  const P = (t, href, icn, k = '') => ({ t, k: t + ' ' + k, icn, go: () => navigate(href), sec: 'الصفحات' });
  const A = (t, icn, fn, k = '') => ({ t, k: t + ' ' + k, icn, go: fn, sec: 'إجراءات' });
  const out = [P('الرئيسية', '/', 'home', 'home'), P('على الهواء', '/live', 'signal', 'live مباشر'), P('كيك', '/kick', 'kick', 'kick'), P('يوتيوب', '/youtube', 'yt', 'youtube'),
    P('X (تويتر)', '/x', 'tw', 'twitter x تويتر'), P('تيليجرام', '/telegram', 'tg', 'telegram'), P('الأخبار', '/news', 'megaphone', 'news')];
  if (ttOn()) out.push(P('تيك توك', '/tiktok', 'tt', 'tiktok'));
  if (canDiscord()) out.push(P('ديسكورد', '/discord', 'dc', 'discord'));
  if (isLogged()) {
    out.push(P('التنبيهات', '/notifications', 'bell', 'notifications اشعارات'), P('سجل الإرسال', '/activity', 'activity', 'log سجل'), P('حسابي', '/account', 'user', 'account'));
    out.push(A('إرسال رسالة لقنواتي', 'send', () => window.__rl.openCompose(), 'send ارسال'));
    out.push(A('إضافة قناة كيك', 'plus', () => navigate('/kick?add=1'), 'add kick'), A('إضافة قناة يوتيوب', 'plus', () => navigate('/youtube?add=1'), 'add youtube'),
      A('توثيق قناة تيليجرام', 'shieldOk', () => navigate('/telegram?verify=1'), 'verify telegram'));
  } else out.push(P('تسجيل الدخول', '/login', 'login', 'login'));
  out.push(A(scheme() === 'light' ? 'الوضع الداكن' : 'الوضع الفاتح', scheme() === 'light' ? 'moon' : 'sun', () => setScheme(scheme() === 'light' ? 'dark' : 'light'), 'theme dark light مظهر'));
  if (isOwner()) {
    [['المستخدمون', 'users', 'users'], ['القنوات المقترحة', 'defaults', 'plus'], ['إعدادات الموقع', 'settings', 'cog'], ['النظام والنسخ الاحتياطي', 'system', 'server'],
     ['المظهر', 'appearance', 'palette'], ['الإحصائيات', 'stats', 'chart'], ['الأمان', 'security', 'lock'], ['الاقتراحات', 'suggestions', 'msg'], ['إدارة الأخبار', 'news', 'news'], ['X API', 'x', 'tw'], ['Groq AI', 'ai', 'ai']]
      .forEach(([t, s, i]) => out.push({ t, k: t + ' admin ' + s, icn: i, go: () => navigate('/admin/' + s), sec: 'الإدارة' }));
  }
  return out;
}

async function channelItems() {
  if (!isLogged()) return [];
  const out = [];
  const kinds = ['kick', 'yt', 'tw', 'tg'].concat(ttOn() ? ['tt'] : []);
  await Promise.all(kinds.map(async k => {
    try {
      const r = await load('ch:' + k, '/api/channels/' + k + (isOwner() ? '?mine=1' : ''), 60000);
      (r.rows || []).forEach(c => out.push({ t: c.name || handleOf(k, c), sub: KIND[k].name + '  ' + handleOf(k, c), k: (c.name || '') + ' ' + handleOf(k, c) + ' ' + KIND[k].name, av: c.avatar, kind: k, sec: 'قنواتك',
        go: () => navigate(KIND[k].path + '?focus=' + c.id) }));
    } catch (e) {}
  }));
  return out;
}

export async function open() {
  if (document.querySelector('.pal-in')) return;
  let items = staticItems(), sel = 0, shown = [];
  sheet({
    size: 'wide', x: false,
    body: html`<div class="pal-in">${ic('search')}<input placeholder="ابحث عن صفحة أو قناة أو إجراء…" autocomplete="off" spellcheck="false" aria-label="بحث"></div><div class="pal-list" role="listbox"></div>
      <div class="hint" style="margin-top:10px;text-align:center">${ic('keyboard')} استخدم الأسهم للتنقل وEnter للفتح</div>`,
    onMount: ({ root, close }) => {
      const inp = $('input', root), list = $('.pal-list', root);
      const paint = () => {
        const qv = norm(inp.value);
        shown = (qv ? items.filter(x => norm(x.k).includes(qv) || norm(x.t).includes(qv)) : items.filter(x => x.sec !== 'قنواتك').slice(0, 14)).slice(0, 40);
        sel = Math.min(sel, Math.max(0, shown.length - 1));
        let last = '';
        list.innerHTML = shown.length ? shown.map((x, i) => {
          const h = x.sec !== last ? '<div class="pal-sec">' + esc(x.sec) + '</div>' : ''; last = x.sec;
          return h + html`<button role="option" data-i="${i}" class="${i === sel ? 'on' : ''}">${x.kind ? avatar(x.av, x.t, 'xs') : html`<span class="pi sm ${x.icn === 'kick' || x.icn === 'yt' || x.icn === 'tw' || x.icn === 'tt' || x.icn === 'tg' || x.icn === 'dc' ? x.icn : 'mu'}">${ic(x.icn)}</span>`}
            <span class="row-tx"><b>${x.t}</b>${x.sub ? html`<small class="ltr" style="text-align:start">${x.sub}</small>` : ''}</span></button>`.s;
        }).join('') : '<div class="empty" style="padding:24px"><p>لا نتائج — جرّب كلمة أخرى</p></div>';
      };
      const go = i => { const x = shown[i]; if (!x) return; close(true); setTimeout(() => x.go(), 30); };
      inp.addEventListener('input', () => { sel = 0; paint(); });
      inp.addEventListener('keydown', e => {
        if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(shown.length - 1, sel + 1); paint(); list.querySelector('.on')?.scrollIntoView({ block: 'nearest' }); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(0, sel - 1); paint(); list.querySelector('.on')?.scrollIntoView({ block: 'nearest' }); }
        else if (e.key === 'Enter') { e.preventDefault(); go(sel); }
      });
      list.addEventListener('click', e => { const b = e.target.closest('[data-i]'); if (b) go(+b.dataset.i); });
      paint();
      setTimeout(() => inp.focus(), 60);
      channelItems().then(ch => { items = items.concat(ch); paint(); });
    },
  });
}
