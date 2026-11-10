// Groq AI
import { api, post } from '../../core/api.js?v=__BUILD__';
import { html, raw, render, $, ic } from '../../core/dom.js?v=__BUILD__';
import { ok, bad, confirm, errorBox, busy, toast } from '../../core/ui.js?v=__BUILD__';
import { head, card } from './_lib.js?v=__BUILD__';

const MODELS = [['llama-3.3-70b-versatile', 'Llama 3.3 70B — الأدق'], ['llama-3.1-8b-instant', 'Llama 3.1 8B — الأسرع'], ['gemma2-9b-it', 'Gemma 2 9B']];
export default {
  async render(ctx) {
    ctx.setTitle('Groq AI');
    let st; try { st = await api('/api/ai/status'); } catch (e) { return render(ctx.root, errorBox(e)); }
    render(ctx.root, html`${head('ai')}
      <div class="callout ${st.available ? 'ok' : 'warn'}" style="margin-bottom:14px">${ic(st.available ? 'okc' : 'warn')}<div>${st.available ? 'Groq يعمل بنموذج ' + st.model + (st.source === 'env' ? ' (المفتاح من متغيرات الخادم)' : '') : 'لم يُضف مفتاح Groq بعد. يُستخدم لإعادة صياغة رسائل ديسكورد وتحسين الرسائل اليدوية.'}</div></div>
      ${card('الإعداد', 'key', html`<label class="field"><span>API Key</span><input type="password" data-key class="ltr" placeholder="gsk_…" ${st.source === 'env' ? raw('disabled') : ''}><small>من console.groq.com/keys</small></label>
        <label class="field"><span>النموذج</span><select data-model>${MODELS.map(([v, l]) => html`<option value="${v}" ${st.model === v ? raw('selected') : ''}>${l}</option>`)}</select></label>`,
        html`<div class="hstack"><button class="btn pri grow" data-save>${ic('check')} حفظ</button>${st.source === 'db' ? html`<button class="btn danger icon" data-clr aria-label="حذف">${ic('trash')}</button>` : ''}</div>`)}
      ${card('تجربة', 'sparkle', html`<label class="field"><span>نص للتجربة</span><textarea data-t rows="3">بدأ البث الآن على كيك، تعال شوف!</textarea></label><div data-out></div>`, html`<button class="btn soft block" data-run ${st.available ? '' : raw('disabled')}>${ic('sparkle')} أعد الصياغة</button>`)}`);
    ctx.root.addEventListener('click', async e => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.matches('[data-save]')) return busy(b, async () => { const body = { model: $('[data-model]', ctx.root).value }; const k = $('[data-key]', ctx.root).value.trim(); if (k) body.api_key = k; try { await post('/api/admin/groq', body); ok('حُفظ'); ctx.rerender(); } catch (x) { bad(x); } });
      if (b.matches('[data-clr]')) { if (!await confirm('', { title: 'حذف مفتاح Groq؟', ok: 'حذف', danger: true })) return; try { await post('/api/admin/groq', { api_key: '' }); ctx.rerender(); } catch (x) { bad(x); } }
      if (b.matches('[data-run]')) return busy(b, async () => { try { const r = await post('/api/ai/rewrite', { text: $('[data-t]', ctx.root).value }); $('[data-out]', ctx.root).innerHTML = html`<div class="callout" style="margin-top:4px">${ic('sparkle')}<div style="white-space:pre-wrap">${r.text}</div></div>`.s; } catch (x) { bad(x); } });
    });
  },
};
