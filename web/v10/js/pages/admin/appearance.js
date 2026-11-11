// المظهر: الشعار، الألوان، الضبابية، الميزات، انميشن الدخول
import { S, api, post, del, upload, pickFile } from '../../core/api.js?v=__BUILD__';
import { html, raw, render, $, $$, ic } from '../../core/dom.js?v=__BUILD__';
import { ok, bad, confirm, errorBox, busy, toast } from '../../core/ui.js?v=__BUILD__';
import { applyTheme, applyBlur, applyFeatures } from '../../core/theme.js?v=__BUILD__';
import { head, card, fields, collect, saveSettings } from './_lib.js?v=__BUILD__';

const THEMES = [['default', 'الافتراضي', '#05070c', '#0c111b', '#2f6bff'], ['saudi', 'اليوم الوطني', '#03271a', '#0b5a33', '#3ddc84'], ['founding', 'يوم التأسيس', '#24190a', '#0b3f2a', '#e6b85c'],
  ['ramadan', 'رمضان', '#070f24', '#162c55', '#f5c04a'], ['fitr', 'عيد الفطر', '#071f20', '#14514a', '#ffd166'], ['adha', 'عيد الأضحى', '#1c1208', '#4a3217', '#f0b84d']];
const BLUR = [['blur', 'قوة الضبابية', 0, 60, 'px'], ['transparency', 'شفافية الأسطح', 0, 100, '%'], ['sat', 'تشبّع الألوان خلف الضبابية', 100, 300, '%'], ['orbs', 'إضاءة الخلفية', 0, 100, '%'], ['radius', 'استدارة الزوايا', 0, 200, '%']];
const PRESETS = [['متوازن', { blur: 22, transparency: 50, sat: 160, orbs: 55, radius: 100 }], ['ضبابي كثيف', { blur: 40, transparency: 70, sat: 190, orbs: 75, radius: 110 }], ['هادئ', { blur: 14, transparency: 30, sat: 130, orbs: 30, radius: 100 }], ['حاد', { blur: 20, transparency: 45, sat: 150, orbs: 45, radius: 40 }]];
const FEATS = [['fx_page_transition', 'حركة الانتقال بين الصفحات', 'انتقال ضبابي ناعم'], ['nav_labels', 'أسماء أزرار الشريط السفلي', 'تحت كل أيقونة في الجوال'], ['fx_press_zoom', 'رفع الأزرار عند التحويم', 'للشاشات بالماوس'],
  ['pwa_enhance', 'تخزين التطبيق على الجهاز', 'يفتح فوراً ويعمل بدون اتصال جزئياً'], ['tiktok_enabled', 'متابعة تيك توك', 'إظهار صفحة تيك توك وفحص البث'], ['feat_haptics', 'اهتزاز خفيف عند اللمس', 'للأجهزة التي تدعمه'], ['feat_install_prompt', 'زر تثبيت التطبيق', 'في صفحة حسابي']];
const ANIMS = [['نبضات', '<style>html,body{margin:0;height:100%;background:#05070c;display:grid;place-items:center;overflow:hidden}.r{position:absolute;width:100px;height:100px;border-radius:50%;border:3px solid #2f6bff;animation:p 1.6s ease-out infinite}.r:nth-child(2){animation-delay:.4s}.r:nth-child(3){animation-delay:.8s}h1{position:relative;margin:0;font:700 28px system-ui;letter-spacing:6px;color:#fff;opacity:0;animation:t .8s .3s forwards}@keyframes p{from{transform:scale(.3);opacity:1}to{transform:scale(3.4);opacity:0}}@keyframes t{to{opacity:1}}</style><div class="r"></div><div class="r"></div><div class="r"></div><h1>WELCOME</h1>'],
  ['ضباب يتكشّف', '<style>html,body{margin:0;height:100%;background:#05070c;display:grid;place-items:center;overflow:hidden}h1{font:700 34px system-ui;color:#fff;letter-spacing:4px;animation:b 1.6s cubic-bezier(.2,.8,.2,1) forwards}@keyframes b{from{filter:blur(24px);opacity:0;transform:scale(1.2)}to{filter:blur(0);opacity:1;transform:none}}</style><h1>RESPECT LIVE</h1>']];

export default {
  async render(ctx) {
    ctx.setTitle('المظهر');
    let s, la;
    try { [s, la] = await Promise.all([api('/api/settings'), api('/api/admin/login-anim')]); } catch (e) { return render(ctx.root, errorBox(e)); }
    const g = { blur: +s.glass_blur, transparency: +s.glass_transparency, sat: +s.glass_sat, orbs: +s.glass_orbs, radius: +s.glass_radius };
    const cur = s.site_theme || 'default';
    const range = ([k, t, lo, hi, u]) => html`<div class="field"><span class="hstack" style="justify-content:space-between"><span>${t}</span><b class="num" data-out="${k}">${g[k]}${u}</b></span><input type="range" min="${lo}" max="${hi}" value="${g[k]}" data-g="${k}"></div>`;
    render(ctx.root, html`${head('appearance')}
      ${card('الشعار', 'image', html`<div class="hstack"><span class="brand-logo" style="width:64px;height:64px;border-radius:20px" data-logo>${s.site_logo ? html`<img src="${s.site_logo}" alt="">` : ic('logo')}</span>
        <div class="grow"><b style="font-size:var(--fs-2)">${s.site_logo ? 'شعار مخصص' : 'الشعار الافتراضي'}</b><div class="hint">PNG أو JPG مربع، حتى 500KB. يظهر في الموقع وأيقونة التطبيق.</div></div>
        <button class="btn soft" data-lup>${ic('upload')} رفع</button>${s.site_logo ? html`<button class="btn ghost icon" data-ldel aria-label="حذف">${ic('trash')}</button>` : ''}</div>`)}
      ${card('ألوان الموقع', 'palette', html`<div class="picks cols" data-themes>${THEMES.map(([id, n, c1, c2, ac]) => html`<button type="button" class="pick ${cur === id ? 'on' : ''}" data-t="${id}"><span class="av sm" style="background:linear-gradient(135deg,${c1},${c2});border:1px solid var(--line-2)"><i style="width:12px;height:12px;border-radius:50%;background:${ac}"></i></span><span class="row-tx"><b>${n}</b></span><span class="ck">${ic('check')}</span></button>`)}
        <button type="button" class="pick ${cur === 'custom' ? 'on' : ''}" data-t="custom"><span class="av sm" style="background:conic-gradient(#f5c04a,#2f6bff,#3ddc84,#ff4d5e,#f5c04a)"></span><span class="row-tx"><b>مخصص</b></span><span class="ck">${ic('check')}</span></button></div>
        <div class="grid3" style="margin-top:14px" data-custom ${cur === 'custom' ? '' : raw('hidden')}>${fields([{ k: 'site_c1', t: 'الخلفية', type: 'color' }, { k: 'site_c2', t: 'النوافذ', type: 'color' }, { k: 'site_ac', t: 'اللون المميز', type: 'color' }], s)}</div>`)}
      ${card('الضبابية', 'sparkle', html`<p class="hint" style="margin:-6px 0 14px">التغييرات تظهر فوراً للمعاينة، وتُطبّق على الجميع بعد الحفظ. الوضع الخفيف لا يتأثر.</p>
        <div class="chips" style="margin-bottom:16px">${PRESETS.map(([n], i) => html`<button class="chip" data-pre="${i}">${n}</button>`)}</div>${BLUR.map(range)}`,
        html`<button class="btn pri block" data-gsave>${ic('check')} حفظ الضبابية للموقع</button>`)}
      ${card('الميزات', 'bolt', html`<div data-feats>${fields(FEATS.map(([k, t, h]) => ({ k, t, hint: h, type: 'switch' })), s)}</div>`, html`<button class="btn pri block" data-fsave style="margin-top:10px">${ic('check')} حفظ الميزات</button>`)}
      ${card('طريقة العرض الافتراضية', 'device', html`<div data-ui>${fields([{ k: 'ui_mode_prompt', t: 'اسأل المستخدم عند أول دخول', type: 'switch', hint: 'يختار بين العرض الكامل والخفيف مرة واحدة' }, { k: 'ui_default_mode', t: 'إذا لم نسأله', type: 'select', opts: [['full', 'العرض الكامل'], ['lite', 'الوضع الخفيف']] }], s)}</div>`, html`<button class="btn pri block" data-usave>${ic('check')} حفظ</button>`)}
      ${card('انميشن الدخول', 'play', html`<p class="hint" style="margin:-6px 0 14px">كود HTML/CSS يظهر بملء الشاشة بعد تسجيل الدخول ثم يختفي. يعمل في صندوق معزول لا يصل لبيانات الموقع. لإنهائه مبكراً: <span class="ltr">parent.postMessage('rl:done','*')</span></p>
        <label class="row" style="padding-inline:0"><span class="row-tx"><b>تفعيل الانميشن</b></span><span class="switch"><input type="checkbox" data-laon ${la.enabled ? raw('checked') : ''}><i></i></span></label>
        <label class="field"><span>المدة (ثوانٍ)</span><input type="number" min="1" max="20" value="${la.secs}" data-lasecs></label>
        <label class="field"><span>الكود</span><textarea class="code" rows="8" data-lacode spellcheck="false">${la.code}</textarea></label>
        <div class="chips" style="margin-bottom:14px">${ANIMS.map(([n], i) => html`<button class="chip" data-ains="${i}">${ic('plus')} مثال: ${n}</button>`)}</div>`,
        html`<div class="hstack"><button class="btn" data-laprev>${ic('play')} معاينة</button><button class="btn pri grow" data-lasave>${ic('check')} حفظ الانميشن</button></div>`)}`);

    const R = ctx.root;
    const live = () => { applyBlur(g); BLUR.forEach(([k, , , , u]) => { const o = $('[data-out="' + k + '"]', R); if (o) o.textContent = g[k] + u; const i = $('[data-g="' + k + '"]', R); if (i) i.value = g[k]; }); };
    R.addEventListener('input', e => {
      if (e.target.matches('[data-g]')) { g[e.target.dataset.g] = +e.target.value; live(); }
      if (e.target.matches('[data-k^="site_"]')) applyTheme({ c1: $('[data-k=site_c1]', R).value, c2: $('[data-k=site_c2]', R).value, ac: $('[data-k=site_ac]', R).value });
    });
    ctx.cleanup(() => applyBlur(S.boot.glass));
    R.addEventListener('change', async e => { if (e.target.matches('[data-k^="site_"]')) { const v = collect($('[data-custom]', R)); v.site_theme = 'custom'; if (await saveSettings(v, 'حُفظت الألوان')) { S.boot.theme = { id: 'custom', c1: v.site_c1, c2: v.site_c2, ac: v.site_ac }; } } });
    R.addEventListener('click', async e => {
      const b = e.target.closest('button'); if (!b) return;
      const t = b.closest('[data-themes] .pick');
      if (t) {
        $$('[data-themes] .pick', R).forEach(x => x.classList.toggle('on', x === t)); const id = t.dataset.t; $('[data-custom]', R).hidden = id !== 'custom';
        const th = id === 'custom' ? { id, c1: $('[data-k=site_c1]', R).value, c2: $('[data-k=site_c2]', R).value, ac: $('[data-k=site_ac]', R).value } : (([i, n, c1, c2, ac]) => ({ id: i, c1, c2, ac }))(THEMES.find(x => x[0] === id));
        applyTheme(th); if (await saveSettings({ site_theme: id }, 'طُبّقت الألوان')) S.boot.theme = th; return;
      }
      if (b.matches('[data-pre]')) { Object.assign(g, PRESETS[+b.dataset.pre][1]); return live(); }
      if (b.matches('[data-gsave]')) return busy(b, async () => { const body = {}; Object.entries(g).forEach(([k, v]) => body['glass_' + k] = v); if (await saveSettings(body, 'حُفظت الضبابية لكل الموقع')) S.boot.glass = { ...S.boot.glass, ...g }; });
      if (b.matches('[data-fsave]')) return busy(b, async () => { const v = collect($('[data-feats]', R)); if (await saveSettings(v, 'حُفظت الميزات')) { Object.keys(v).forEach(k => S.boot.features[k] = v[k] === '1'); applyFeatures(S.boot.features); } });
      if (b.matches('[data-usave]')) return busy(b, async () => { const v = collect($('[data-ui]', R)); if (await saveSettings(v)) { S.boot.ui_mode_prompt = v.ui_mode_prompt === '1'; S.boot.ui_default_mode = v.ui_default_mode; } });
      if (b.matches('[data-lup]')) { const f = await pickFile(); if (!f) return; try { const r = await upload(f, '/api/admin/site-logo', 512000); S.boot.site_logo = r.url; ok('رُفع الشعار'); ctx.rerender(); } catch (x) { bad(x); } return; }
      if (b.matches('[data-ldel]')) { if (!await confirm('نرجع للشعار الافتراضي.', { title: 'حذف الشعار؟', ok: 'حذف', danger: true })) return; try { await del('/api/admin/site-logo'); S.boot.site_logo = ''; ok('حُذف الشعار'); ctx.rerender(); } catch (x) { bad(x); } return; }
      if (b.matches('[data-ains]')) { $('[data-lacode]', R).value = ANIMS[+b.dataset.ains][1]; return; }
      if (b.matches('[data-laprev]')) { const c = $('[data-lacode]', R).value; if (!c.trim()) return toast('ألصق الكود أولاً', 'bad'); const m = await import('../../components/intro.js?v=__BUILD__'); return m.play(c, +$('[data-lasecs]', R).value || 3, true); }
      if (b.matches('[data-lasave]')) return busy(b, async () => { try { await post('/api/admin/login-anim', { enabled: $('[data-laon]', R).checked, code: $('[data-lacode]', R).value, secs: +$('[data-lasecs]', R).value || 3 }); ok('حُفظ الانميشن'); } catch (x) { bad(x); } });
    });
  },
};
