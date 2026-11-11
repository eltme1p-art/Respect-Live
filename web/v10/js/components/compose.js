// إرسال رسالة يدوية لقنوات تيليجرام (والمستخدمين للمالك) مع معاينة حيّة
import { S, api, post, upload, pickFile, isOwner } from '../core/api.js?v=__BUILD__';
import { html, raw, $, $$, ic, avatar, tgHtml, esc } from '../core/dom.js?v=__BUILD__';
import { sheet, toast, bad, ok } from '../core/ui.js?v=__BUILD__';

export function tgPreview(text, image, btn) {
  return html`<div class="tgp"><div class="tgp-h">${ic('tg')} معاينة الرسالة في تيليجرام</div><div class="tgp-msg">${image ? html`<img src="${image}" alt="" onerror="this.remove()">` : ''}<div class="tgp-tx">${raw(tgHtml(text || '…'))}</div></div>${btn ? html`<div class="tgp-btn">${btn}</div>` : ''}</div>`;
}

export async function open(pre = {}) {
  let data;
  try { data = await api('/api/send/prefill'); } catch (e) { return bad(e); }
  const tgs = data.tgs || [], users = data.users || [];
  const pick = (attr, x, title, sub) => html`<button type="button" class="pick" data-${raw(attr)}="${x.id}">${avatar(x.avatar, title, 'sm')}<span class="row-tx"><b class="clip">${title}</b><small class="clip ltr" style="text-align:start">${sub || ''}</small></span><span class="ck">${ic('check')}</span></button>`;
  let image = pre.image || '';
  sheet({
    title: 'إرسال رسالة', sub: 'تصل الرسالة فوراً لقنواتك المختارة في تيليجرام', size: 'xwide',
    body: html`<div class="grid2" style="gap:18px;align-items:start;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr)" data-cols>
      <div>
        <label class="field"><span>نص الرسالة</span><textarea name="text" rows="6" maxlength="4000" placeholder="اكتب رسالتك… يمكنك استخدام <b>عريض</b> و<i>مائل</i>">${pre.text || ''}</textarea></label>
        <div class="vars"><button type="button" data-wrap="b"><b>B</b></button><button type="button" data-wrap="i"><i>I</i></button><button type="button" data-wrap="u"><u>U</u></button><button type="button" data-wrap="code">code</button>
          ${S.me && S.me.has_groq ? html`<button type="button" data-ai style="direction:rtl">${ic('sparkle')} حسّن الصياغة</button>` : ''}</div>
        <div class="field"><span>صورة (اختياري)</span><div class="hstack"><button type="button" class="btn sm soft" data-up>${ic('image')} رفع صورة</button><button type="button" class="btn sm ghost" data-clr hidden>${ic('x')} إزالة</button><input class="input grow" name="image" placeholder="أو الصق رابط صورة https://…" value="${image}" style="height:34px;font-size:13px"></div></div>
        <div class="grid2"><label class="field"><span>نص الزر</span><input name="btn_text" maxlength="60" placeholder="مثال: شاهد الآن"></label><label class="field"><span>رابط الزر</span><input name="btn_url" class="ltr" placeholder="https://…" inputmode="url"></label></div>
        <div class="field"><span>قنوات تيليجرام</span>
          <div class="chips" data-mode="tg" style="margin-bottom:10px"><button type="button" class="chip" data-m="none">بدون</button><button type="button" class="chip on" data-m="all">كل قنواتي (${tgs.length})</button><button type="button" class="chip" data-m="pick">أختار</button></div>
          <div class="picks" data-list="tg" hidden>${tgs.length ? tgs.map(t => pick('tg', t, t.name || t.username, t.username || (t.added_by ? '@' + t.added_by : ''))) : html`<div class="hint">لا توجد قنوات موثقة بعد</div>`}</div></div>
        ${isOwner() && users.length ? html`<div class="field"><span>تنبيه داخل الموقع للمستخدمين</span>
          <div class="chips" data-mode="us" style="margin-bottom:10px"><button type="button" class="chip on" data-m="none">بدون</button><button type="button" class="chip" data-m="all">الجميع (${users.length})</button><button type="button" class="chip" data-m="pick">أختار</button></div>
          <div class="picks cols" data-list="us" hidden>${users.map(u => pick('us', u, u.display || u.username, '@' + u.username))}</div>
          <input name="title" class="input" placeholder="عنوان التنبيه (افتراضي: رسالة من الإدارة)" style="margin-top:10px" maxlength="120"></div>` : ''}
      </div>
      <div style="position:sticky;top:0" data-prev></div></div>`,
    actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: 'إرسال', icon: 'send', kind: 'pri', handler: submit }],
    onMount: ({ root }) => {
      if (innerWidth < 760) root.querySelector('[data-cols]').style.gridTemplateColumns = '1fr';
      const ta = $('[name=text]', root), imgIn = $('[name=image]', root), prev = $('[data-prev]', root);
      const paint = () => { prev.innerHTML = tgPreview(ta.value, imgIn.value.trim(), $('[name=btn_text]', root).value.trim()).s; $('[data-clr]', root).hidden = !imgIn.value; };
      root.addEventListener('input', paint);
      paint();
      root.addEventListener('click', async e => {
        const ch = e.target.closest('.chip[data-m]');
        if (ch) { const g = ch.parentElement; $$('.chip', g).forEach(x => x.classList.toggle('on', x === ch)); const list = $('[data-list="' + g.dataset.mode + '"]', root); if (list) list.hidden = ch.dataset.m !== 'pick'; return; }
        const pk = e.target.closest('.pick'); if (pk) { pk.classList.toggle('on'); return; }
        const w = e.target.closest('[data-wrap]');
        if (w) { const t = w.dataset.wrap, s = ta.selectionStart, en = ta.selectionEnd, v = ta.value; ta.value = v.slice(0, s) + '<' + t + '>' + v.slice(s, en) + '</' + t + '>' + v.slice(en); ta.focus(); ta.selectionStart = s + t.length + 2; ta.selectionEnd = en + t.length + 2; paint(); return; }
        if (e.target.closest('[data-up]')) { const f = await pickFile(); if (!f) return; const b = e.target.closest('[data-up]'); b.setAttribute('aria-busy', 'true'); try { const r = await upload(f); imgIn.value = r.url; paint(); } catch (x) { bad(x); } b.removeAttribute('aria-busy'); return; }
        if (e.target.closest('[data-clr]')) { imgIn.value = ''; paint(); return; }
        const ai = e.target.closest('[data-ai]');
        if (ai) { if (!ta.value.trim()) return toast('اكتب نصاً أولاً', 'bad'); ai.setAttribute('aria-busy', 'true'); try { const r = await post('/api/ai/rewrite', { text: ta.value }); ta.value = r.text; paint(); } catch (x) { bad(x); } ai.removeAttribute('aria-busy'); }
      });
    },
  });

  async function submit({ root }) {
    const g = n => ($('[name=' + n + ']', root) || {}).value?.trim() || '';
    const mode = k => ($('[data-mode="' + k + '"] .chip.on', root) || {}).dataset?.m || 'none';
    const ids = k => $$('[data-list="' + k + '"] .pick.on', root).map(x => +x.dataset[k]);
    const body = { text: g('text'), image: g('image'), btn_text: g('btn_text'), btn_url: g('btn_url'), title: g('title'), tg: { mode: mode('tg'), ids: ids('tg') }, users: { mode: mode('us'), ids: ids('us') } };
    if (!body.text && !body.image) { toast('اكتب نصاً أو أضف صورة', 'bad'); return false; }
    if (body.tg.mode === 'none' && body.users.mode === 'none') { toast('اختر إلى أين تُرسل الرسالة', 'bad'); return false; }
    if (body.tg.mode === 'pick' && !body.tg.ids.length && body.users.mode === 'none') { toast('اختر قناة واحدة على الأقل', 'bad'); return false; }
    if (body.btn_url && !body.btn_text) body.btn_text = 'فتح الرابط';
    const r = (await post('/api/send', body)).result || {};
    const parts = [];
    if (r.tg_sent || r.tg_failed) parts.push('وصلت إلى ' + r.tg_sent + ' قناة' + (r.tg_failed ? '، وفشلت ' + r.tg_failed : ''));
    if (r.users) parts.push('وتنبيه لـ ' + r.users + ' مستخدم');
    if (r.tg_failed && !r.tg_sent) toast('تعذّر الإرسال — تأكد أن البوت ما زال مشرفاً في القنوات', 'bad'); else ok(parts.join(' ') || 'أُرسلت');
    return true;
  }
}
