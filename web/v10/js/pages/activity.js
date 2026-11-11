// سجل الإرسال: كل ما وصل لقنواتك في تيليجرام، من أي مصدر
import { api, isOwner } from '../core/api.js?v=__BUILD__';
import { html, render, ic, ago, num, plain, dayLabel, time } from '../core/dom.js?v=__BUILD__';
import { empty, skelList, errorBox } from '../core/ui.js?v=__BUILD__';

export const SRC = {
  kick: { n: 'كيك', i: 'kick', c: 'kick' }, yt: { n: 'يوتيوب', i: 'yt', c: 'yt' }, tw: { n: 'X', i: 'tw', c: 'tw' }, tt: { n: 'تيك توك', i: 'tt', c: 'tt' },
  dc: { n: 'ديسكورد', i: 'dc', c: 'dc' }, manual: { n: 'إرسال يدوي', i: 'send', c: 'violet' },
};

export default {
  async render(ctx) {
    let src = ctx.query.get('source') || '', all = false, data = null, err = null;
    const paint = () => {
      if (!ctx.alive()) return;
      const rows = data ? data.rows : null;
      let last = '';
      render(ctx.root, html`
        <header class="page-head"><span class="pi">${ic('activity')}</span><div><h1>سجل الإرسال</h1><p>${data ? (data.total ? num(data.ok) + ' وصلت' + (data.failed ? '، و' + num(data.failed) + ' لم تصل' : '') + ' من آخر ' + num(data.total) + ' رسالة' : 'لا شيء بعد') : 'كل ما أرسله البوت لقنواتك.'}</p></div>
          ${isOwner() ? html`<div class="acts"><button class="btn ${all ? 'soft' : 'ghost'}" data-all>${ic('users')} ${all ? 'كل المستخدمين' : 'قنواتي'}</button></div>` : ''}</header>
        <div class="chips" style="margin-bottom:16px">${[['', 'الكل'], ...Object.entries(SRC).map(([k, v]) => [k, v.n])].map(([k, t]) => html`<button class="chip ${src === k ? 'on' : ''}" data-s="${k}">${k ? ic(SRC[k].i) : ''}${t}</button>`)}</div>
        ${err ? errorBox(err, true) : !rows ? skelList(6) : !rows.length ? empty('inbox', 'لا يوجد إرسال بعد', 'عندما يبث أحد أو ينشر جديداً، تظهر هنا كل رسالة وصلت لقنواتك — ومتى فشلت ولماذا.', html`<a class="btn soft" href="/telegram">${ic('tg')} قنواتي في تيليجرام</a>`)
          : html`<div class="tl">${rows.map(m => { const s = SRC[m.source] || SRC.manual; const d = dayLabel(m.ts); const head = d !== last ? html`<div class="tl-day">${d}</div>` : ''; last = d;
            return html`${head}<div class="item">${m.image ? html`<img class="thumb" src="${m.image}" alt="" loading="lazy" onerror="this.remove()">` : html`<span class="pi ${s.c}">${ic(s.i)}</span>`}
              <div class="item-tx"><b>${m.source_name || s.n}</b><p>${plain(m.text).slice(0, 240)}</p>
              <div class="hstack" style="margin-top:8px;gap:6px"><span class="tag">${ic(s.i)} ${s.n}</span><span class="tag">${ic('tg')} ${m.tg_name || ''}</span>${m.ok ? html`<span class="tag ok">${ic('check')} وصلت</span>` : html`<span class="tag bad">${ic('warn')} لم تصل</span>`}<span class="mu" style="font-size:var(--fs-0)">${time(m.ts)}</span>${m.url ? html`<a class="link" style="font-size:var(--fs-0)" href="${m.url}" target="_blank" rel="noopener">فتح المصدر</a>` : ''}</div></div></div>`; })}</div>
          ${data.failed ? html`<div class="callout warn" style="margin-top:16px">${ic('info')}<div><b>لماذا تفشل بعض الرسائل؟</b><br>غالباً لأن البوت لم يعد مشرفاً في القناة، أو أُزيلت صلاحية النشر. أعد إضافته كمشرف ثم جرّب «إرسال تجريبي».</div></div>` : ''}`}`);
    };
    const reload = async () => { try { data = await api('/api/me/deliveries?source=' + encodeURIComponent(src) + (all ? '&all=1' : '')); err = null; } catch (e) { err = e; } paint(); };
    ctx.onRefresh(reload);
    ctx.root.addEventListener('click', e => {
      const c = e.target.closest('[data-s]'); if (c) { src = c.dataset.s; data = null; paint(); reload(); }
      if (e.target.closest('[data-all]')) { all = !all; data = null; paint(); reload(); }
      if (e.target.closest('[data-retry]')) reload();
    });
    paint(); await reload();
  },
};
