// مكونات الواجهة العامة: إشعارات، نوافذ، قوائم، تأكيد، حالات فارغة
import { html, raw, render, esc, $, $$, ic } from './dom.js?v=__BUILD__';
import { icon } from './icons.js?v=__BUILD__';
import { feat } from './api.js?v=__BUILD__';

export function haptic(ms = 8) { if (feat('feat_haptics') && navigator.vibrate) { try { navigator.vibrate(ms); } catch (e) {} } }

// ─── Toast ───
let toastBox;
export function toast(msg, kind = 'info', opts = {}) {
  if (!toastBox) { toastBox = document.createElement('div'); toastBox.className = 'toasts'; toastBox.setAttribute('role', 'status'); toastBox.setAttribute('aria-live', 'polite'); document.body.appendChild(toastBox); }
  const t = document.createElement('div');
  t.className = 'toast blur ' + kind;
  const ico = kind === 'ok' ? 'okc' : kind === 'bad' ? 'badc' : 'info';
  t.innerHTML = icon(ico) + '<span>' + esc(msg) + '</span>' + (opts.action ? '<button class="act" type="button">' + esc(opts.action.label) + '</button>' : '');
  if (opts.action) t.querySelector('.act').onclick = () => { opts.action.fn(); hide(); };
  while (toastBox.children.length > 2) toastBox.firstChild.remove();
  toastBox.appendChild(t);
  requestAnimationFrame(() => requestAnimationFrame(() => t.classList.add('on')));
  const hide = () => { t.classList.remove('on'); setTimeout(() => t.remove(), 350); };
  setTimeout(hide, opts.ms || (kind === 'bad' ? 5200 : 3400));
  if (kind === 'bad') haptic(20);
}
export const ok = m => toast(m, 'ok');
export const bad = e => toast((e && e.message) || String(e || 'حدث خطأ'), 'bad');

// ─── Sheets (نوافذ منبثقة: سفلية على الجوال، وسطية على الشاشات الكبيرة) ───
const stack = [];
export const sheetOpen = () => stack.length > 0;
export function closeTopFromHistory() {
  const top = stack[stack.length - 1];
  if (!top) return false;
  top.close(null, true);
  return true;
}

export function sheet(o = {}) {
  return new Promise(resolve => {
    const wrap = document.createElement('div');
    wrap.className = 'sheet-wrap';
    const size = o.size ? ' ' + o.size : '';
    const head = (o.title || o.sub) ? html`<div class="sheet-head"><div class="grow"><div class="sheet-title" id="sh-t">${o.title || ''}</div>${o.sub ? html`<div class="sheet-sub">${o.sub}</div>` : ''}</div>
      ${o.x !== false ? html`<button class="btn ghost icon sm x" type="button" data-x aria-label="إغلاق">${ic('x')}</button>` : ''}</div>` : '';
    const acts = (o.actions || []);
    wrap.innerHTML = html`<div class="sheet${size}" role="dialog" aria-modal="true" ${o.title ? raw('aria-labelledby="sh-t"') : ''}><div class="grab"></div>${head}
      <div class="sheet-body"></div>
      ${acts.length ? html`<div class="sheet-foot">${acts.map((a, i) => html`<button type="button" class="btn ${a.kind || ''}" data-a="${i}" ${a.disabled ? raw('disabled') : ''}>${a.icon ? ic(a.icon) : ''}${a.label}</button>`)}</div>` : ''}</div>`.s;
    const body = $('.sheet-body', wrap);
    if (o.body) body.innerHTML = String(o.body);
    document.body.appendChild(wrap);
    const prevFocus = document.activeElement;
    let done = false;
    const entry = { close, dismiss: o.dismiss !== false };
    stack.push(entry);
    try { history.pushState({ ...(history.state || {}), sheet: stack.length }, ''); entry.pushed = true; } catch (e) {}
    document.documentElement.style.overflow = 'hidden';
    requestAnimationFrame(() => requestAnimationFrame(() => wrap.classList.add('on')));

    function close(v, fromHistory) {
      if (done) return; done = true;
      const i = stack.indexOf(entry); if (i >= 0) stack.splice(i, 1);
      if (!stack.length) document.documentElement.style.overflow = '';
      if (entry.pushed && !fromHistory) { entry.skipPop = true; window.__rlSkipPop = (window.__rlSkipPop || 0) + 1; history.back(); }
      wrap.classList.remove('on');
      setTimeout(() => { wrap.remove(); try { prevFocus && prevFocus.focus && prevFocus.focus({ preventScroll: true }); } catch (e) {} }, 380);
      o.onClose && o.onClose(v);
      resolve(v === undefined ? null : v);
    }
    const ctx = { root: body, sheet: $('.sheet', wrap), close, foot: $('.sheet-foot', wrap), btn: i => $('[data-a="' + i + '"]', wrap) };
    wrap.addEventListener('click', e => {
      if (e.target === wrap && o.dismiss !== false) close(null);
      if (e.target.closest('[data-x]')) close(null);
    });
    $$('[data-a]', wrap).forEach(b => b.onclick = async () => {
      const a = acts[+b.dataset.a];
      if (a.handler) {
        b.setAttribute('aria-busy', 'true');
        try { const r = await a.handler(ctx, b); if (r !== false) close(r === undefined ? (a.value ?? true) : r); }
        catch (err) { bad(err); }
        finally { b.removeAttribute('aria-busy'); }
      } else close(a.value ?? true);
    });
    wrap.addEventListener('keydown', e => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && acts.length) { const b = $('.sheet-foot .btn.pri, .sheet-foot .btn.danger', wrap); if (b) b.click(); }
      if (e.key === 'Tab') trap(e, $('.sheet', wrap));
    });
    // سحب للإغلاق (جوال)
    const sh = $('.sheet', wrap); let y0 = null, dy = 0;
    const startDrag = e => { if (body.scrollTop > 0 && !e.target.closest('.grab,.sheet-head')) return; y0 = e.touches[0].clientY; dy = 0; sh.style.transition = 'none'; };
    sh.addEventListener('touchstart', startDrag, { passive: true });
    sh.addEventListener('touchmove', e => { if (y0 == null) return; dy = Math.max(0, e.touches[0].clientY - y0); if (dy > 0 && body.scrollTop <= 0) sh.style.transform = 'translateY(' + dy + 'px)'; else if (body.scrollTop > 0) { y0 = null; sh.style.transform = ''; } }, { passive: true });
    sh.addEventListener('touchend', () => { if (y0 == null) return; sh.style.transition = ''; sh.style.transform = ''; if (dy > 110 && o.dismiss !== false) close(null); y0 = null; });
    if (o.onMount) o.onMount(ctx);
    setTimeout(() => { const f = $('[autofocus]', wrap) || (window.innerWidth > 640 && $('input:not([type=hidden]):not([type=checkbox]),textarea', body)); if (f) f.focus({ preventScroll: true }); }, 320);
  });
}
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || !stack.length) return;
  const top = stack[stack.length - 1];
  if (top.dismiss) { e.preventDefault(); top.close(null); }
});
function trap(e, root) {
  const f = $$('button:not([disabled]),[href],input:not([type=hidden]),select,textarea,[tabindex]:not([tabindex="-1"])', root).filter(x => x.offsetParent !== null);
  if (!f.length) return;
  const first = f[0], last = f[f.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

export function confirm(msg, o = {}) {
  return sheet({ title: o.title || 'تأكيد', sub: msg, size: 'sm', actions: [{ label: o.cancel || 'إلغاء', kind: 'ghost', value: false }, { label: o.ok || 'تأكيد', kind: o.danger ? 'danger' : 'pri', value: true }] }).then(v => v === true);
}
export function alertSheet(title, msg, o = {}) {
  return sheet({ title, body: html`<div style="white-space:pre-line;line-height:1.9;font-size:var(--fs-2);color:var(--tx-2)">${msg}</div>${o.extra ? raw(o.extra) : ''}`, size: 'sm', actions: [{ label: o.ok || 'حسناً', kind: 'pri' }] });
}
export function prompt(o = {}) {
  return sheet({
    title: o.title, sub: o.sub, size: 'sm',
    body: html`<label class="field"><span>${o.label || ''}</span>${o.multiline ? html`<textarea name="v" rows="4" maxlength="${o.max || 1000}" placeholder="${o.placeholder || ''}">${o.value || ''}</textarea>` : html`<input name="v" value="${o.value || ''}" maxlength="${o.max || 200}" placeholder="${o.placeholder || ''}" autocomplete="off">`}</label>`,
    actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: o.ok || 'حفظ', kind: 'pri', handler: ({ root }) => { const v = $('[name=v]', root).value.trim(); if (o.required !== false && !v) { toast('اكتب قيمة أولاً', 'bad'); return false; } return v; } }],
    onMount: ({ root }) => { const i = $('[name=v]', root); i.addEventListener('keydown', e => { if (e.key === 'Enter' && !o.multiline) { e.preventDefault(); $('.sheet-foot .btn.pri', root.closest('.sheet')).click(); } }); },
  });
}
export function menu(items, o = {}) {
  return sheet({
    title: o.title, sub: o.sub, size: 'sm',
    body: html`<div class="menu">${items.filter(Boolean).map((it, i) => it === '-' ? raw('<hr>') : html`<button type="button" data-m="${i}" class="${it.danger ? 'danger' : ''}">${ic(it.icon || 'chev')}<span class="grow">${it.label}</span>${it.hint ? html`<span class="mu" style="font-size:var(--fs-0)">${it.hint}</span>` : ''}</button>`)}</div>`,
    onMount: ({ root, close }) => { root.addEventListener('click', e => { const b = e.target.closest('[data-m]'); if (!b) return; const it = items.filter(Boolean)[+b.dataset.m]; close(true); setTimeout(() => it.fn && it.fn(), 60); }); },
  });
}

export async function busy(btn, fn) {
  if (!btn) return fn();
  btn.setAttribute('aria-busy', 'true');
  try { return await fn(); } finally { btn.removeAttribute('aria-busy'); }
}

export const empty = (iconName, title, text, action) => html`<div class="empty"><div class="ic">${ic(iconName)}</div><h3>${title}</h3>${text ? html`<p>${text}</p>` : ''}${action || ''}</div>`;
export const skelGrid = (n = 6) => html`<div class="grid">${Array.from({ length: n }, () => raw('<div class="skel skel-card"></div>'))}</div>`;
export const skelList = (n = 5) => html`<div class="stack">${Array.from({ length: n }, () => raw('<div class="skel" style="height:64px;border-radius:var(--r-row)"></div>'))}</div>`;
export const errorBox = (e, retry) => html`<div class="empty"><div class="ic">${ic('wifiOff')}</div><h3>تعذّر التحميل</h3><p>${(e && e.message) || 'حدث خطأ'}</p>${retry ? raw('<button class="btn soft" data-retry>' + icon('refresh') + ' إعادة المحاولة</button>') : ''}</div>`;

export function copy(text, msg = 'تم النسخ') {
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(() => ok(msg)).catch(() => {
    const t = document.createElement('textarea'); t.value = text; document.body.appendChild(t); t.select(); try { document.execCommand('copy'); ok(msg); } catch (e) {} t.remove();
  });
}
export { render };
