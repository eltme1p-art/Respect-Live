// X API
import { api, post } from '../../core/api.js?v=__BUILD__';
import { html, raw, render, $, ic, num, ago } from '../../core/dom.js?v=__BUILD__';
import { ok, bad, confirm, errorBox, busy, toast } from '../../core/ui.js?v=__BUILD__';
import { head, card } from './_lib.js?v=__BUILD__';

export default {
  async render(ctx) {
    ctx.setTitle('X API');
    let s; try { s = await api('/api/admin/twitter'); } catch (e) { return render(ctx.root, errorBox(e)); }
    const pct = s.daily_cap > 0 ? Math.min(100, s.reads_today / s.daily_cap * 100) : 0;
    const state = !s.configured ? ['warn', 'لم يُضف مفتاح بعد — لن تُجلب تغريدات'] : s.paused ? ['bad', 'الجلب متوقف مؤقتاً بسبب حد الطلبات'] : s.last_error ? ['bad', s.last_error] : ['ok', 'يعمل' + (s.last_ok ? ' — آخر جلب ناجح ' + ago(s.last_ok) : '')];
    render(ctx.root, html`${head('x')}
      <div class="callout ${state[0]}" style="margin-bottom:14px">${ic(state[0] === 'ok' ? 'okc' : 'warn')}<div>${state[1]}</div></div>
      ${card('المفتاح والجلب', 'key', html`
        <label class="field"><span>Bearer Token ${s.source === 'env' ? '(من متغيرات الخادم)' : s.key_hint ? '— الحالي ' + s.key_hint : ''}</span><input type="password" data-key class="ltr" autocomplete="off" placeholder="الصق المفتاح هنا" ${s.source === 'env' ? raw('disabled') : ''}></label>
        <div class="grid2"><label class="field"><span>كل كم نفحص الحساب</span><select data-int>${[[120, 'دقيقتان'], [300, '5 دقائق (مقترح)'], [600, '10 دقائق'], [900, '15 دقيقة'], [1800, '30 دقيقة']].map(([v, l]) => html`<option value="${v}" ${s.interval === v ? raw('selected') : ''}>${l}</option>`)}</select></label>
          <label class="field"><span>الحد اليومي للتغريدات المقروءة</span><input type="number" data-cap value="${s.daily_cap}" min="0"><small>حماية للرصيد — 0 بلا حد</small></label></div>
        ${s.daily_cap ? html`<div class="hstack" style="margin-bottom:14px"><div class="meter grow ${pct >= 100 ? 'full' : pct >= 80 ? 'warn' : ''}"><i style="width:${pct}%"></i></div><span class="num mu" style="font-size:var(--fs-1)">${num(s.reads_today)} / ${num(s.daily_cap)} اليوم</span></div>` : ''}
        <dl class="kv" style="margin-bottom:14px"><dt>الحسابات المضافة</dt><dd>${num(s.accounts)}</dd><dt>حسابات فريدة يُجلب لها</dt><dd>${num(s.unique_accounts)}</dd></dl>`,
        html`<div class="hstack"><button class="btn pri grow" data-save>${ic('check')} حفظ</button><button class="btn" data-test>${ic('refresh')} اختبار الاتصال</button>${s.source === 'db' ? html`<button class="btn danger icon" data-clr aria-label="حذف المفتاح">${ic('trash')}</button>` : ''}</div>`)}
      ${card('كيف أحصل على المفتاح؟', 'info', html`<div class="steps">${['ادخل console.x.com وأنشئ تطبيقاً', 'من Keys and Tokens انسخ Bearer Token', 'الصقه هنا ثم احفظ واختبر'].map((t, i) => html`<div class="step"><span class="n">${i + 1}</span><span class="row-tx"><b>${t}</b></span></div>`)}</div>
        <p class="hint" style="margin-top:12px">X API بالدفع حسب الاستخدام. النظام يجلب الجديد فقط، ويشارك الطلب الواحد بين كل من أضاف نفس الحساب.</p>`)}`);
    const body = () => { const b = { interval: $('[data-int]', ctx.root).value, daily_cap: $('[data-cap]', ctx.root).value }; const k = $('[data-key]', ctx.root).value.trim(); if (k) b.api_key = k; return b; };
    ctx.root.addEventListener('click', async e => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.matches('[data-save]')) return busy(b, async () => { try { await post('/api/admin/twitter', body()); ok('حُفظ'); ctx.rerender(); } catch (x) { bad(x); } });
      if (b.matches('[data-test]')) return busy(b, async () => { try { await post('/api/admin/twitter', body()); const r = await post('/api/admin/twitter', { test: true }); r.ok ? ok(r.detail) : toast(r.error, 'bad'); } catch (x) { bad(x); } });
      if (b.matches('[data-clr]')) { if (!await confirm('سيتوقف جلب التغريدات لكل المستخدمين.', { title: 'حذف المفتاح؟', ok: 'حذف', danger: true })) return; try { await post('/api/admin/twitter', { api_key: '' }); ok('حُذف المفتاح'); ctx.rerender(); } catch (x) { bad(x); } }
    });
  },
};
