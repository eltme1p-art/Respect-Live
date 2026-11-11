// الأخبار والإعلانات من الإدارة
import { S, api, post, load, peek, isLogged, emit } from '../core/api.js?v=__BUILD__';
import { html, render, ic, ago } from '../core/dom.js?v=__BUILD__';
import { empty, skelList, errorBox } from '../core/ui.js?v=__BUILD__';

const KIND = { news: ['خبر', 'ac', 'news'], update: ['تحديث', 'ok', 'sparkle'], maintenance: ['صيانة', 'warn', 'wrench'], warning: ['تنبيه مهم', 'bad', 'warn'] };
export function newsCard(n) {
  const k = KIND[n.kind] || KIND.news;
  return html`<article class="card" data-id="${n.id}" style="overflow:hidden;${n.is_read === false ? 'border-color:rgba(var(--ac-rgb),.35)' : ''}">
    ${n.image ? html`<img src="${n.image}" alt="" loading="lazy" style="width:100%;max-height:260px;object-fit:cover" onerror="this.remove()">` : ''}
    <div style="padding:16px 18px 18px"><div class="hstack" style="margin-bottom:8px"><span class="tag ${k[1]}">${ic(k[2])} ${k[0]}</span>${n.is_read === false ? html`<span class="tag ac">جديد</span>` : ''}<span class="mu" style="font-size:var(--fs-0);margin-inline-start:auto">${ago(n.created)}</span></div>
    <h3 style="font-size:var(--fs-4);font-weight:600;line-height:1.5">${n.title}</h3>${n.body ? html`<p style="margin-top:6px;color:var(--tx-2);font-size:var(--fs-2);line-height:1.9;white-space:pre-line;max-width:68ch">${n.body}</p>` : ''}</div></article>`;
}

export default {
  async render(ctx) {
    const paint = (d, err) => {
      if (!ctx.alive()) return;
      const rows = d ? d.rows : null;
      render(ctx.root, html`<header class="page-head"><span class="pi">${ic('megaphone')}</span><div><h1>الأخبار</h1><p>إعلانات وتحديثات الموقع</p></div></header>
        ${err ? errorBox(err, true) : !rows ? skelList(3) : !rows.length ? empty('megaphone', 'لا أخبار حالياً', 'ستظهر هنا إعلانات الإدارة والتحديثات الجديدة.') : html`<div class="stack" style="max-width:760px">${rows.map(newsCard)}</div>`}`);
    };
    const reload = async () => {
      try {
        const d = await load('news', '/api/news', 0); paint(d);
        if (isLogged() && d.unread_count) { await post('/api/news/read-all'); S.newsUnread = 0; emit('badges'); d.rows.forEach(n => { n.is_read = true; }); d.unread_count = 0; }
      } catch (e) { paint(peek('news'), peek('news') ? null : e); }
    };
    ctx.onRefresh(reload);
    paint(peek('news')); await reload();
  },
};
