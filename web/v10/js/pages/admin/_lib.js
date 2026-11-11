// أدوات مشتركة لصفحات الإدارة: نماذج إعدادات موحّدة
import { api, post } from '../../core/api.js?v=__BUILD__';
import { html, raw, $, $$, ic } from '../../core/dom.js?v=__BUILD__';
import { ok, bad } from '../../core/ui.js?v=__BUILD__';

export const SECTIONS = [
  { s: 'users', i: 'users', n: 'المستخدمون', d: 'الحسابات والحدود والحظر' },
  { s: 'stats', i: 'chart', n: 'الإحصائيات', d: 'نشاط الإرسال والاستخدام' },
  { s: 'system', i: 'server', n: 'النظام', d: 'الصيانة، المهام، النسخ الاحتياطي' },
  { s: 'settings', i: 'cog', n: 'الإعدادات', d: 'الحدود، القوالب، القناة الرسمية' },
  { s: 'appearance', i: 'palette', n: 'المظهر', d: 'الألوان، الشعار، الضبابية، الميزات' },
  { s: 'defaults', i: 'sparkle', n: 'القنوات المقترحة', d: 'قنوات جاهزة يضيفها المستخدمون بضغطة' },
  { s: 'news', i: 'megaphone', n: 'الأخبار', d: 'إعلانات تظهر لكل المستخدمين' },
  { s: 'suggestions', i: 'msg', n: 'الاقتراحات', d: 'رسائل المستخدمين', badge: 'suggestions_unread' },
  { s: 'x', i: 'tw', n: 'X API', d: 'مفتاح الجلب والحد اليومي' },
  { s: 'ai', i: 'ai', n: 'Groq AI', d: 'إعادة صياغة رسائل ديسكورد' },
  { s: 'security', i: 'lock', n: 'الأمان', d: 'سجل الدخول والأحداث' },
];

// f: {k, t, type: text|textarea|code|number|switch|select|color, hint, opts:[[v,label]], ph, ltr}
export function fields(list, v) {
  return list.map(f => {
    const val = v[f.k] ?? f.def ?? '';
    if (f.type === 'switch') return html`<label class="row" style="padding-inline:0"><span class="row-tx"><b>${f.t}</b>${f.hint ? html`<small>${f.hint}</small>` : ''}</span><span class="switch"><input type="checkbox" data-k="${f.k}" data-t="switch" ${String(val) === '1' || val === true ? raw('checked') : ''}><i></i></span></label>`;
    const lab = html`<span>${f.t}</span>`;
    const hint = f.hint ? html`<small>${f.hint}</small>` : '';
    if (f.type === 'textarea' || f.type === 'code') return html`<label class="field">${lab}<textarea data-k="${f.k}" rows="${f.rows || 3}" class="${f.type === 'code' ? 'code' : ''}" placeholder="${f.ph || ''}">${val}</textarea>${hint}</label>`;
    if (f.type === 'select') return html`<label class="field">${lab}<select data-k="${f.k}">${f.opts.map(([o, l]) => html`<option value="${o}" ${String(val) === String(o) ? raw('selected') : ''}>${l}</option>`)}</select>${hint}</label>`;
    return html`<label class="field">${lab}<input data-k="${f.k}" type="${f.type === 'number' ? 'number' : f.type === 'color' ? 'color' : 'text'}" value="${val}" placeholder="${f.ph || ''}" class="${f.ltr ? 'ltr' : ''}" ${f.type === 'number' ? raw('inputmode="numeric" min="0"') : ''}>${hint}</label>`;
  });
}
export function collect(root) {
  const out = {};
  $$('[data-k]', root).forEach(el => { out[el.dataset.k] = el.dataset.t === 'switch' ? (el.checked ? '1' : '0') : el.value; });
  return out;
}
export const card = (title, iconName, body, foot) => html`<section class="card pad-l" style="margin-bottom:14px"><div class="sec-h" style="margin-bottom:14px">${iconName ? html`<span class="pi sm">${ic(iconName)}</span>` : ''}<h2 style="font-size:var(--fs-3)">${title}</h2></div>${body}${foot || ''}</section>`;
export async function saveSettings(body, msg = 'حُفظت الإعدادات') {
  try { await post('/api/settings', body); ok(msg); return true; } catch (e) { bad(e); return false; }
}
export function head(sec, extra) {
  const S = SECTIONS.find(x => x.s === sec) || { n: 'لوحة الإدارة', i: 'shield', d: '' };
  return html`<header class="page-head"><span class="pi violet">${ic(S.i)}</span><div><h1>${S.n}</h1><p>${S.d}</p></div>${extra ? html`<div class="acts">${extra}</div>` : ''}</header>`;
}
