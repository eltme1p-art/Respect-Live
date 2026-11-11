// القنوات المقترحة: قنوات جاهزة يضيفها المستخدمون بضغطة
import { api, post, patch, del, KIND, ttOn } from '../../core/api.js?v=__BUILD__';
import { html, render, $, ic, avatar, num } from '../../core/dom.js?v=__BUILD__';
import { sheet, prompt, confirm, menu, ok, bad, toast, empty, skelList, errorBox } from '../../core/ui.js?v=__BUILD__';
import { head } from './_lib.js?v=__BUILD__';

const KINDS = () => ['kick', 'yt', 'tw'].concat(ttOn() ? ['tt'] : []).concat(['tg']);
export default {
  async render(ctx) {
    ctx.setTitle('القنوات المقترحة');
    let rows = null, err = null, kind = 'kick';
    const paint = () => {
      if (!ctx.alive()) return;
      const list = rows ? rows.filter(r => r.kind === kind) : [];
      render(ctx.root, html`${head('defaults', html`<button class="btn" data-bulk>${ic('copy')} إضافة جماعية</button><button class="btn pri" data-add>${ic('plus')} إضافة</button>`)}
        <nav class="seg" style="margin-bottom:16px">${KINDS().map(k => html`<button class="${kind === k ? 'on' : ''}" data-k="${k}" style="--c:var(--${k === 'tw' ? 'x' : k})">${ic(k)}<span>${KIND[k].name}</span>${rows ? html`<span class="mu num">${num(rows.filter(r => r.kind === k).length)}</span>` : ''}</button>`)}</nav>
        ${err ? errorBox(err, true) : !rows ? skelList(5) : !list.length ? empty(kind, 'لا مقترحات لـ ' + KIND[kind].name, 'أضف قنوات مشهورة ليختارها المستخدمون بضغطة بدلاً من كتابتها.', html`<button class="btn pri" data-add>${ic('plus')} إضافة</button>`)
          : html`<div class="group">${list.map(r => html`<button class="row" data-id="${r.id}">${avatar(r.avatar, r.name, 'sm')}<span class="row-tx"><b class="clip">${r.name || r.identifier}</b><small class="clip ltr" style="text-align:start">${r.alias && r.alias !== r.identifier ? r.alias + '  ' : ''}${r.identifier}</small></span><span class="row-end">${r.enabled ? '' : html`<span class="tag">مخفية</span>`}${ic('more')}</span></button>`)}</div>`}`);
    };
    const reload = async () => { try { rows = (await api('/api/admin/default-channels')).rows; err = null; } catch (e) { err = e; } paint(); };
    ctx.onRefresh(reload);
    ctx.root.addEventListener('click', async e => {
      const k = e.target.closest('[data-k]'); if (k) { kind = k.dataset.k; return paint(); }
      if (e.target.closest('[data-retry]')) return reload();
      if (e.target.closest('[data-add]')) return sheet({ title: 'اقتراح ' + KIND[kind].name, size: 'sm',
        body: html`<label class="field"><span>المعرّف</span><input name="id" class="ltr" placeholder="${KIND[kind].ph || '@channel'}" autofocus></label><label class="field"><span>الاسم (اختياري)</span><input name="nm" placeholder="يُجلب تلقائياً"></label>`,
        actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: 'إضافة', kind: 'pri', handler: async ({ root }) => { await post('/api/admin/default-channels', { kind, identifier: $('[name=id]', root).value.trim(), name: $('[name=nm]', root).value.trim() }); ok('أُضيفت'); reload(); } }] });
      if (e.target.closest('[data-bulk]')) return sheet({ title: 'إضافة جماعية — ' + KIND[kind].name, size: 'wide',
        body: html`<label class="field"><span>سطر لكل قناة</span><textarea name="t" rows="10" class="code" placeholder="xqc&#10;trainwreckstv | اسم مخصص"></textarea><small>حتى 100 سطر. يمكنك إضافة اسم بعد علامة |</small></label>`,
        actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: 'إضافة الكل', kind: 'pri', handler: async ({ root }) => { const r = await post('/api/admin/default-channels/bulk', { kind, text: $('[name=t]', root).value }); ok('أُضيف ' + r.added + (r.failed ? '، وتعذّر ' + r.failed : '')); if (r.errors.length) setTimeout(() => toast(r.errors.slice(0, 3).join(' — '), 'info', { ms: 7000 }), 600); reload(); } }] });
      const rr = e.target.closest('[data-id]'); if (!rr) return;
      const r = rows.find(x => x.id === +rr.dataset.id);
      menu([
        { icon: 'edit', label: 'تغيير الاسم', fn: async () => { const v = await prompt({ title: 'الاسم', value: r.name }); if (v) { try { await patch('/api/admin/default-channels/' + r.id, { name: v }); reload(); } catch (x) { bad(x); } } } },
        { icon: r.enabled ? 'eyeOff' : 'eye', label: r.enabled ? 'إخفاء من المقترحات' : 'إظهار في المقترحات', fn: async () => { try { await patch('/api/admin/default-channels/' + r.id, { enabled: !r.enabled }); reload(); } catch (x) { bad(x); } } },
        '-', { icon: 'trash', label: 'حذف', danger: true, fn: async () => { if (await confirm('لن تُحذف من حسابات من أضافها.', { title: 'حذف المقترح؟', ok: 'حذف', danger: true })) { try { await del('/api/admin/default-channels/' + r.id); reload(); } catch (x) { bad(x); } } } },
      ], { title: r.name || r.identifier });
    });
    paint(); await reload();
  },
};
