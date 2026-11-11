// اقتراحات المستخدمين
import { api, patch, del } from '../../core/api.js?v=__BUILD__';
import { html, render, ic, avatar, ago } from '../../core/dom.js?v=__BUILD__';
import { confirm, ok, bad, empty, skelList, errorBox } from '../../core/ui.js?v=__BUILD__';
import { head } from './_lib.js?v=__BUILD__';

export default {
  async render(ctx) {
    ctx.setTitle('الاقتراحات');
    let d = null, err = null, only = false;
    const paint = () => { if (!ctx.alive()) return; const rows = d ? d.rows.filter(s => !only || !s.is_read) : null;
      render(ctx.root, html`${head('suggestions')}<div class="chips" style="margin-bottom:14px"><button class="chip ${only ? '' : 'on'}" data-o="0">الكل</button><button class="chip ${only ? 'on' : ''}" data-o="1">غير المقروءة<span class="n">${d ? d.unread : ''}</span></button></div>
        ${err ? errorBox(err, true) : !rows ? skelList(4) : !rows.length ? empty('msg', 'لا اقتراحات', 'يصل هنا ما يرسله المستخدمون من صفحة حسابي.') : html`<div class="stack">${rows.map(s => html`<div class="card pad" style="${s.is_read ? '' : 'border-color:rgba(var(--ac-rgb),.35)'}"><div class="hstack" style="margin-bottom:10px">${avatar('', s.username, 'xs')}<b class="ltr" style="font-size:var(--fs-1)">@${s.username}</b><span class="mu" style="font-size:var(--fs-0)">${ago(s.ts)}</span>${s.is_read ? '' : html`<span class="tag ac">جديد</span>`}
          <span style="margin-inline-start:auto" class="hstack"><button class="btn sm ghost" data-r="${s.id}">${ic('check')} ${s.is_read ? 'غير مقروء' : 'تم'}</button><button class="btn sm ghost icon" data-d="${s.id}" aria-label="حذف">${ic('trash')}</button></span></div>
          <p style="white-space:pre-wrap;line-height:1.9;font-size:var(--fs-2);max-width:72ch">${s.text}</p></div>`)}</div>`}`); };
    const reload = async () => { try { d = await api('/api/admin/suggestions'); err = null; } catch (e) { err = e; } paint(); };
    ctx.root.addEventListener('click', async e => {
      const o = e.target.closest('[data-o]'); if (o) { only = o.dataset.o === '1'; return paint(); }
      const r = e.target.closest('[data-r]'); if (r) { const s = d.rows.find(x => x.id === +r.dataset.r); try { await patch('/api/admin/suggestions/' + s.id, { is_read: !s.is_read }); reload(); } catch (x) { bad(x); } }
      const dl = e.target.closest('[data-d]'); if (dl && await confirm('', { title: 'حذف الاقتراح؟', ok: 'حذف', danger: true })) { try { await del('/api/admin/suggestions/' + dl.dataset.d); ok('حُذف'); reload(); } catch (x) { bad(x); } }
    });
    ctx.onRefresh(reload); paint(); await reload();
  },
};
