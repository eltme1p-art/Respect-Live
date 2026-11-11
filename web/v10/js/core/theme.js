// المظهر: ألوان الموقع، الوضع الفاتح/الداكن، الضبابية، الوضع الخفيف
import { S } from './api.js?v=__BUILD__';
import { ls } from './dom.js?v=__BUILD__';

const root = document.documentElement;

function hexRgb(h) { h = String(h || '').replace('#', ''); if (h.length === 3) h = h.split('').map(c => c + c).join(''); const n = parseInt(h, 16); return isNaN(n) ? null : [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
const lum = ([r, g, b]) => { const f = c => { c /= 255; return c <= .03928 ? c / 12.92 : Math.pow((c + .055) / 1.055, 2.4); }; return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };

export function applyTheme(t) {
  if (!t) return;
  const st = root.style;
  const light = root.classList.contains('light');
  if (!light) {
    if (t.c1) st.setProperty('--bg', t.c1); else st.removeProperty('--bg');
    if (t.c2) st.setProperty('--bg-2', t.c2); else st.removeProperty('--bg-2');
  } else { st.removeProperty('--bg'); st.removeProperty('--bg-2'); }
  const rgb = hexRgb(t.ac);
  if (rgb) {
    st.setProperty('--ac', t.ac);
    st.setProperty('--ac-rgb', rgb.join(','));
    st.setProperty('--ac-ink', lum(rgb) > .55 ? '#0b1020' : '#fff');
  }
  const m = document.querySelector('meta[name="theme-color"]');
  if (m) m.setAttribute('content', light ? '#eef1f7' : (t.c1 || '#080b14'));
}

// إعدادات «الزجاج» القديمة تُترجم لضبابية: blur → قوة الضبابية، transparency → شفافية الأسطح، radius → الاستدارة، orbs → الإضاءة الخلفية
export function applyBlur(g) {
  g = g || {};
  const st = root.style, n = (v, d) => { v = parseFloat(v); return isNaN(v) ? d : v; };
  st.setProperty('--blur', Math.round(n(g.blur, 22)) + 'px');
  st.setProperty('--sat', Math.round(n(g.sat, 160)) + '%');
  st.setProperty('--rs', (n(g.radius, 100) / 100).toFixed(2));
  const tr = n(g.transparency, 50);
  if (!root.classList.contains('light')) st.setProperty('--sf-a', (0.11 - tr * 0.0008).toFixed(3)); else st.removeProperty('--sf-a');
  st.setProperty('--amb', (n(g.orbs, 55) / 100 * (root.classList.contains('light') ? .6 : 1)).toFixed(2));
}

export function applyFeatures(f) {
  f = f || {};
  root.classList.toggle('fx-zoom', !!f.fx_press_zoom);
  root.classList.toggle('nav-labels', f.nav_labels !== false);
  root.classList.toggle('no-motion', ls.get('rl_motion', '') === 'off' || (f.fx_page_transition === false && ls.get('rl_motion', '') !== 'on'));
  let st = false; try { st = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true; } catch (e) {}
  root.classList.toggle('pwa', st);
}

// ─── تفضيلات المستخدم على هذا الجهاز ───
export const scheme = () => ls.get('rl_scheme', 'dark');   // dark | light | auto
export function setScheme(v) { ls.set('rl_scheme', v); applyScheme(); }
export function applyScheme() {
  const v = scheme();
  const light = v === 'light' || (v === 'auto' && matchMedia('(prefers-color-scheme: light)').matches);
  root.classList.toggle('light', light);
  applyTheme(S.boot.theme);
  applyBlur(S.boot.glass);
}
matchMedia('(prefers-color-scheme: light)').addEventListener?.('change', () => { if (scheme() === 'auto') applyScheme(); });

export function deviceWeak() {
  try {
    const mem = navigator.deviceMemory, cores = navigator.hardwareConcurrency, sd = navigator.connection && navigator.connection.saveData;
    const noBlur = !(window.CSS && CSS.supports && (CSS.supports('backdrop-filter', 'blur(1px)') || CSS.supports('-webkit-backdrop-filter', 'blur(1px)')));
    return !!((mem && mem <= 3) || (cores && cores <= 3) || sd || noBlur);
  } catch (e) { return false; }
}
export const uiMode = () => { const m = ls.get('rl_ui_mode', ''); return m === 'lite' || m === 'full' ? m : ''; };
export function setLite(on, persist = true) {
  if (persist) ls.set('rl_ui_mode', on ? 'lite' : 'full');
  root.classList.toggle('lite', !!on);
  // الأسطح تُضبَّب فعلياً فقط على الأجهزة القوية (الضبابية الخلفية مُسبقة أصلاً)
  root.classList.toggle('fx-cards', !on && !deviceWeak() && matchMedia('(min-width: 900px)').matches && matchMedia('(pointer: fine)').matches);
}

export function initTheme() {
  const m = uiMode();
  setLite(m ? m === 'lite' : (deviceWeak() || S.boot.ui_default_mode === 'lite'), false);
  applyScheme();
  applyFeatures(S.boot.features);
}
