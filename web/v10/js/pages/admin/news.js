// إدارة الأخبار
import { api, post, patch, del, upload, pickFile, drop } from '../../core/api.js?v=__BUILD__';
import { html, raw, render, $, ic, ago } from '../../core/dom.js?v=__BUILD__';
import { sheet, confirm, menu, ok, bad, toast, empty, skelList, errorBox } from '../../core/ui.js?v=__BUILD__';
import { head } from './_lib.js?v=__BUILD__';
import { newsCard } from '../news.js?v=__BUILD__';

export default {
  async render(ctx) {
    ctx.setTitle('الأخبار');
    let rows = null, err = null;
    const paint = () => { if (!ctx.alive()) return; render(ctx.root, html`${head('news', html`<button class="btn pri" data-add>${ic('plus')} خبر جديد</button>`)}
      ${err ? errorBox(err, true) : !rows ? skelList(3) : !rows.length ? empty('megaphone', 'لم تنشر أخباراً بعد', 'الخبر يظهر لكل المستخدمين في صفحة الأخبار، ونافذة عند دخولهم.', html`<button class="btn pri" data-add>${ic('plus')} أول خبر</button>`)
        : html`<div class="stack" style="max-width:760px">${rows.map(n => html`<div style="position:relative;${n.enabled ? '' : 'opacity:.55'}">${newsCard({ ...n, is_read: true })}<button class="btn sm icon" data-id="${n.id}" style="position:absolute;top:12px;inset-inline-end:12px" aria-label="خيارات">${ic('more')}</button></div>`)}</div>`}`); };
    const reload = async () => { try { rows = (await api('/api/admin/news')).rows; err = null; } catch (e) { err = e; } drop('news'); paint(); };
    ctx.root.addEventListener('click', async e => {
      if (e.target.closest('[data-add]')) return edit(null, reload);
      const b = e.target.closest('[data-id]'); if (!b) return; const n = rows.find(x => x.id === +b.dataset.id);
      menu([{ icon: 'edit', label: 'تعديل', fn: () => edit(n, reload) }, { icon: n.enabled ? 'eyeOff' : 'eye', label: n.enabled ? 'إخفاء' : 'نشر', fn: async () => { await patch('/api/admin/news/' + n.id, { enabled: !n.enabled }); reload(); } },
        '-', { icon: 'trash', label: 'حذف', danger: true, fn: async () => { if (await confirm('', { title: 'حذف الخبر؟', ok: 'حذف', danger: true })) { await del('/api/admin/news/' + n.id); ok('حُذف'); reload(); } } }], { title: n.title });
    });
    ctx.onRefresh(reload); paint(); await reload();
  },
};

function edit(n, reload) {
  let img = (n && n.image) || '';
  return sheet({ title: n ? 'تعديل الخبر' : 'خبر جديد', size: 'wide',
    body: html`<label class="field"><span>العنوان</span><input name="t" value="${n ? n.title : ''}" maxlength="200" autofocus></label>
      <label class="field"><span>النوع</span><select name="k">${[['news', 'خبر'], ['update', 'تحديث'], ['maintenance', 'صيانة'], ['warning', 'تنبيه مهم']].map(([v, l]) => html`<option value="${v}" ${n && n.kind === v ? raw('selected') : ''}>${l}</option>`)}</select></label>
      <label class="field"><span>النص</span><textarea name="b" rows="6" maxlength="4000">${n ? n.body : ''}</textarea></label>
      <div class="field"><span>صورة (اختياري)</span><div class="imgbox" data-box>${img ? html`<img src="${img}" alt="">` : 'بدون صورة'}</div><div class="hstack" style="margin-top:8px"><button type="button" class="btn sm soft" data-up>${ic('upload')} رفع</button><button type="button" class="btn sm ghost" data-clr>${ic('x')} إزالة</button></div></div>
      ${n ? '' : html`<label class="row" style="padding-inline:0"><span class="row-tx"><b>إرسال إشعار للأجهزة</b><small>لمن فعّل إشعارات المتصفح</small></span><span class="switch"><input type="checkbox" name="push"><i></i></span></label>`}`,
    actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: n ? 'حفظ' : 'نشر', kind: 'pri', handler: async ({ root }) => {
      const body = { title: $('[name=t]', root).value.trim(), kind: $('[name=k]', root).value, body: $('[name=b]', root).value.trim(), image: img };
      if (!body.title) { toast('اكتب عنواناً', 'bad'); return false; }
      if (n) await patch('/api/admin/news/' + n.id, body); else await post('/api/admin/news', { ...body, push: $('[name=push]', root).checked });
      ok(n ? 'حُفظ الخبر' : 'نُشر الخبر'); reload();
    } }],
    onMount: ({ root }) => root.addEventListener('click', async e => {
      if (e.target.closest('[data-up]')) { const f = await pickFile(); if (!f) return; try { img = (await upload(f)).url; $('[data-box]', root).innerHTML = '<img src="' + img + '" alt="">'; } catch (x) { bad(x); } }
      if (e.target.closest('[data-clr]')) { img = ''; $('[data-box]', root).textContent = 'بدون صورة'; }
    }) });
}
