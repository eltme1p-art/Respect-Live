// قوالب HTML آمنة (كل قيمة تُهرَّب تلقائياً إلا ما يُغلَّف بـ raw)
import { icon } from './icons.js?v=__BUILD__';

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);

class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = s => new Raw(String(s ?? ''));
const val = v => {
  if (v == null || v === false || v === true) return '';
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(val).join('');
  return esc(v);
};
export function html(strings, ...vals) {
  let out = '';
  for (let i = 0; i < strings.length; i++) { out += strings[i]; if (i < vals.length) out += val(vals[i]); }
  return new Raw(out);
}
export const ic = (n, c) => raw(icon(n, c));
export function render(el, tpl) { if (el) el.innerHTML = tpl instanceof Raw ? tpl.s : esc(tpl); return el; }
export function frag(tpl) { const t = document.createElement('template'); t.innerHTML = tpl instanceof Raw ? tpl.s : esc(tpl); return t.content; }

export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
export function on(root, ev, sel, fn) {
  const h = e => { const t = e.target.closest(sel); if (t && root.contains(t)) fn(e, t); };
  root.addEventListener(ev, h);
  return () => root.removeEventListener(ev, h);
}

// ─── تنسيق ───
const nf = new Intl.NumberFormat('en-US');
export const num = n => nf.format(+n || 0);
export const compact = n => { n = +n || 0; if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M'; if (n >= 1e4) return Math.round(n / 1e3) + 'K'; if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, '') + 'K'; return String(n); };
export function ago(ts) {
  if (!ts) return '';
  const d = Math.floor(Date.now() / 1000) - ts;
  if (d < 45) return 'الآن';
  if (d < 3600) { const m = Math.max(1, Math.round(d / 60)); return m === 1 ? 'قبل دقيقة' : m === 2 ? 'قبل دقيقتين' : m <= 10 ? 'قبل ' + m + ' دقائق' : 'قبل ' + m + ' دقيقة'; }
  if (d < 86400) { const h = Math.round(d / 3600); return h === 1 ? 'قبل ساعة' : h === 2 ? 'قبل ساعتين' : h <= 10 ? 'قبل ' + h + ' ساعات' : 'قبل ' + h + ' ساعة'; }
  if (d < 604800) { const x = Math.round(d / 86400); return x === 1 ? 'أمس' : x === 2 ? 'قبل يومين' : 'قبل ' + x + ' أيام'; }
  return new Date(ts * 1000).toLocaleDateString('ar-EG-u-nu-latn', { day: 'numeric', month: 'long' });
}
export const date = ts => ts ? new Date(ts * 1000).toLocaleDateString('ar-EG-u-nu-latn', { year: 'numeric', month: 'long', day: 'numeric' }) : '—';
export const time = ts => ts ? new Date(ts * 1000).toLocaleTimeString('ar-EG-u-nu-latn', { hour: 'numeric', minute: '2-digit' }) : '';
export function dayLabel(ts) {
  const d = new Date(ts * 1000), t = new Date();
  const k = x => x.getFullYear() + '-' + x.getMonth() + '-' + x.getDate();
  if (k(d) === k(t)) return 'اليوم';
  const y = new Date(t); y.setDate(t.getDate() - 1);
  if (k(d) === k(y)) return 'أمس';
  return d.toLocaleDateString('ar-EG-u-nu-latn', { weekday: 'long', day: 'numeric', month: 'long' });
}
export const bytes = n => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.round((n || 0) / 1024) + ' KB';
export function dur(s) { s = +s || 0; const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return d ? d + ' يوم ' + h + ' س' : h ? h + ' س ' + m + ' د' : m + ' د'; }
export const plain = s => String(s || '').replace(/<[^>]+>/g, '');
export const initial = s => (String(s || '?').trim().charAt(0) || '?').toUpperCase();

// عرض نص تيليجرام (HTML محدود) بأمان: نسمح فقط بالوسوم التي يدعمها تيليجرام
export function tgHtml(s) {
  const allowed = /^(b|strong|i|em|u|ins|s|strike|del|code|pre|a|tg-spoiler|blockquote|br)$/i;
  return esc(s).replace(/&lt;(\/?)([a-z-]+)((?:\s+href=&quot;[^&]*&quot;)?)\s*\/?&gt;/gi, (m, sl, tag, attr) => {
    if (!allowed.test(tag)) return m;
    if (tag.toLowerCase() === 'a' && !sl) { const h = (attr.match(/href=&quot;([^&]*)&quot;/) || [])[1] || '#'; return /^https?:/i.test(h) ? '<a href="' + h + '" target="_blank" rel="noopener">' : '<a>'; }
    return '<' + sl + tag.toLowerCase() + '>';
  });
}

export function avatar(src, name, cls = '') {
  return html`<span class="av ${cls}">${src ? html`<img src="${src}" alt="" loading="lazy" decoding="async" onerror="this.remove()">` : initial(name)}</span>`;
}
export function debounce(fn, ms = 200) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
export const sleep = ms => new Promise(r => setTimeout(r, ms));

// ─── لون القناة من صورتها (بدل غطاء فارغ) ───
const _cv = new Map(); let _store = null;
const ls = { get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }, del(k) { try { localStorage.removeItem(k); } catch (e) {} } };
export { ls };
export function hashColor(s) { let h = 0; for (const ch of String(s || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return 'hsl(' + (h % 360) + ' 55% 42%)'; }
function pick(im) {
  const n = 24, cv = document.createElement('canvas'); cv.width = cv.height = n;
  const cx = cv.getContext('2d', { willReadFrequently: true }); cx.drawImage(im, 0, 0, n, n);
  const d = cx.getImageData(0, 0, n, n).data; const B = Array.from({ length: 24 }, () => ({ w: 0, r: 0, g: 0, b: 0 }));
  let tw = 0, ar = 0, ag = 0, ab = 0, an = 0;
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] < 128) continue;
    const r = d[i], g = d[i + 1], b = d[i + 2]; ar += r; ag += g; ab += b; an++;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), dd = mx - mn, v = mx / 255, s = mx ? dd / mx : 0;
    if (s < .25 || v < .2) continue;
    let h = mx === r ? ((g - b) / dd) % 6 : mx === g ? (b - r) / dd + 2 : (r - g) / dd + 4; h = (h * 60 + 360) % 360;
    const w = s * s * (.4 + v), k = B[Math.min(23, Math.floor(h / 15))]; k.w += w; k.r += r * w; k.g += g * w; k.b += b * w; tw += w;
  }
  if (!an) return null;
  let best = null; B.forEach(x => { if (!best || x.w > best.w) best = x; });
  let r, g, b;
  if (best && best.w > 0 && tw > an * .02) { r = best.r / best.w; g = best.g / best.w; b = best.b / best.w; } else { r = ar / an; g = ag / an; b = ab / an; }
  if (Math.max(r, g, b) < 30) { r = 30; g = 40; b = 64; }
  return 'rgb(' + (r | 0) + ',' + (g | 0) + ',' + (b | 0) + ')';
}
export function tone(el, src, seed) {
  if (!el) return;
  const set = c => el.style.setProperty('--cv', c);
  if (!_store) { try { _store = JSON.parse(ls.get('rl_cv', '{}')) || {}; } catch (e) { _store = {}; } }
  if (!src) return set(hashColor(seed));
  if (_store[src]) return set(_store[src]);
  set(hashColor(seed));
  let p = _cv.get(src);
  if (!p) {
    p = new Promise(res => { const im = new Image(); if (!src.startsWith('/')) im.crossOrigin = 'anonymous'; im.decoding = 'async'; im.onload = () => { try { res(pick(im)); } catch (e) { res(null); } }; im.onerror = () => res(null); im.src = src; })
      .then(c => { if (c) { _store[src] = c; const ks = Object.keys(_store); if (ks.length > 400) ks.slice(0, 120).forEach(k => delete _store[k]); ls.set('rl_cv', JSON.stringify(_store)); } return c; });
    _cv.set(src, p);
  }
  p.then(c => c && set(c));
}
