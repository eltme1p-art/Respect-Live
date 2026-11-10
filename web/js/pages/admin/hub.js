// لوحة الإدارة: نظرة سريعة + الأقسام
import { S, api } from '../../core/api.js?v=__BUILD__';
import { html, render, ic, num } from '../../core/dom.js?v=__BUILD__';
import { errorBox } from '../../core/ui.js?v=__BUILD__';
import { SECTIONS } from './_lib.js?v=__BUILD__';

export default {
  async render(ctx) {
    let s = null, err = null;
    const paint = () => {
      if (!ctx.alive()) return;
      const svc = s ? [['Telegram', s.has_telegram, s.tg_bot ? '@' + s.tg_bot : ''], ['Discord', s.discord_ready, s.has_discord ? (s.discord_ready ? 'متصل' : 'غير متصل') : 'بدون توكن'], ['X API', s.has_twitter, ''], ['Push', s.has_push, ''], ['Groq', s.has_groq, '']] : [];
      render(ctx.root, html`<header class="page-head"><span class="pi violet">${ic('shield')}</span><div><h1>لوحة الإدارة</h1><p>أهلاً ${S.me.user.display || S.me.user.username}${s && s.maintenance ? '  — وضع الصيانة مفعّل' : ''}</p></div></header>
        ${err ? errorBox(err, true) : ''}
        ${s ? html`<div class="statrow">
          <a class="stat" href="/admin/users"><b>${num(s.users_total)}</b><small>مستخدم، ${num(s.users_active_24h)} نشط اليوم</small></a>
          <a class="stat" href="/live"><b style="color:var(--air)">${num(s.kick_live + (s.tt_live || 0))}</b><small>على الهواء الآن</small></a>
          <a class="stat" href="/admin/stats"><b>${num(s.sent_24h)}</b><small>تنبيه وصل خلال 24 ساعة${s.failed_24h ? '، ' + num(s.failed_24h) + ' لم يصل' : ''}</small></a>
          <div class="stat"><b>${num(s.kick_total + s.yt_total + s.tw_total + (s.tt_total || 0))}</b><small>قناة مراقَبة</small></div></div>
          <div class="hstack" style="margin-top:12px;gap:6px">${svc.map(([n, on, x]) => html`<span class="tag ${on ? 'ok' : 'warn'}"><span class="dot ${on ? 'ok' : 'warn'}"></span>${n}${x ? ' ' + x : ''}</span>`)}</div>` : html`<div class="statrow">${[1, 2, 3, 4].map(() => html`<div class="skel" style="height:76px;border-radius:var(--r-row)"></div>`)}</div>`}
        <div class="sec"><div class="adm-grid">${SECTIONS.map(x => html`<a class="adm-card" href="/admin/${x.s}"><span class="pi">${ic(x.i)}</span><span><b>${x.n}</b><small>${x.d}</small></span>${x.badge && s && s[x.badge] ? html`<span class="badge">${s[x.badge]}</span>` : ''}</a>`)}
          <button class="adm-card" onclick="window.__rl.openCompose()" style="text-align:start"><span class="pi ok">${ic('send')}</span><span><b>رسالة جماعية</b><small>لقنوات تيليجرام أو تنبيه داخل الموقع</small></span></button></div></div>`);
    };
    const reload = async () => { try { s = await api('/api/admin/stats'); err = null; } catch (e) { err = e; } paint(); };
    ctx.onRefresh(reload); paint(); await reload();
  },
};
