// أدوات القنوات: البطاقة، الإضافة، تخصيص الرسالة، فلترة X
import { S, api, post, patch, del, upload, pickFile, KIND, handleOf, urlOf, isOwner, canWrite, drop } from '../core/api.js?v=__BUILD__';
import { html, raw, $, $$, ic, avatar, tone, compact, ago, esc } from '../core/dom.js?v=__BUILD__';
import { sheet, toast, ok, bad, confirm, menu, prompt } from '../core/ui.js?v=__BUILD__';
import { tgPreview } from './compose.js?v=__BUILD__';

// ─── البطاقة ───
export function card(kind, r, o = {}) {
  const live = (kind === 'kick' || kind === 'tt') && r.live && r.enabled;
  const name = r.name || handleOf(kind, r);
  const cover = r.banner || (live ? r.thumb : '') || '';
  const mine = !isOwner() || !r.added_by || r.added_by === S.me.user.username;
  return html`<article class="ch ${r.enabled ? '' : 'off'} ${o.sel ? 'sel' : ''}" data-id="${r.id}" id="ch-${r.id}">
    <div class="ch-cover ${cover ? '' : 'tone'}" data-tone="${cover ? '' : (r.avatar || '')}" data-seed="${handleOf(kind, r)}">
      ${cover ? html`<img src="${cover}" alt="" loading="lazy" decoding="async" onerror="this.parentNode.classList.add('tone');this.remove()">` : ''}
      <div class="ch-badges">
        ${live ? html`<span class="tag air">على الهواء</span>` : ''}
        ${!r.enabled ? html`<span class="tag">${ic('pause')} موقوفة</span>` : ''}
        ${kind !== 'tg' && r.auto_send === 0 ? html`<span class="tag">${ic('bellOff')} بدون تنبيه</span>` : ''}
        ${kind === 'tg' && r.verified ? html`<span class="tag">${ic('shieldOk')} موثّقة</span>` : ''}
        ${!mine ? html`<span class="tag">${ic('user')} ${r.added_by}</span>` : ''}
      </div>
      ${o.selecting ? html`<span class="ch-sel">${ic('check')}</span>` : ''}
    </div>
    <div class="ch-head">${raw(avatar(r.avatar, name, live ? 'onair' : '').s)}<div class="ch-id"><div class="ch-name clip">${name}</div><div class="ch-sub clip">${handleOf(kind, r)}</div></div></div>
    <div class="ch-body">
      ${live && r.title ? html`<div class="ch-live"><span class="t">${r.title}</span><span class="v">${ic('eye')}${compact(r.viewers)}</span></div>`
        : html`<div class="ch-meta">${r.msg ? html`<span class="tag ac">${ic('edit')} رسالة مخصصة</span>` : ''}${kind === 'tw' && r.filters && r.filters !== '{}' && hasFilters(r.filters) ? html`<span class="tag violet">${ic('filter')} فلترة</span>` : ''}${r.last_check ? html`<span class="tag">${ic('clock')} ${ago(r.last_check)}</span>` : ''}</div>`}
    </div>
    <div class="ch-acts">
      ${kind !== 'tg' ? html`<a class="btn sm soft grow" href="${urlOf(kind, r)}" target="_blank" rel="noopener">${ic(live ? 'play' : 'ext')} ${live ? 'شاهد' : 'فتح'}</a>`
        : html`<button class="btn sm soft grow" data-act="log">${ic('inbox')} آخر الرسائل</button>`}
      ${kind !== 'tg' ? html`<button class="btn sm icon" data-act="edit" title="تخصيص الرسالة" aria-label="تخصيص الرسالة">${ic('edit')}</button>` : ''}
      <button class="btn sm icon" data-act="more" title="المزيد" aria-label="المزيد">${ic('more')}</button>
    </div></article>`;
}
const hasFilters = f => { try { const o = JSON.parse(f); return Object.values(o).some(v => Array.isArray(v) ? v.length : !!v); } catch (e) { return false; } };
export function paintTones(root) { $$('.ch-cover.tone, .live-card .cv', root).forEach(el => { if (!el.dataset.painted) { el.dataset.painted = 1; tone(el, el.dataset.tone, el.dataset.seed); } }); }

// ─── قائمة إجراءات القناة ───
export function actions(kind, r, reload) {
  const P = '/api/channels/' + kind + '/' + r.id;
  const run = async (fn, msg) => { try { await fn(); if (msg) ok(msg); drop('ch:' + kind); drop('home'); await reload(); } catch (e) { bad(e); } };
  return menu([
    kind !== 'tg' && { icon: 'send', label: 'إرسال تجريبي لحسابي', hint: 'لا يُرسل لقنواتك', fn: async () => { try { await post(P + '/test'); ok('أرسلنا نسخة تجريبية لحسابك في تيليجرام'); } catch (e) { bad(e); } } },
    kind === 'tw' && { icon: 'filter', label: 'فلترة التغريدات', fn: () => editFilters(r, reload) },
    kind !== 'tg' && { icon: r.auto_send === 0 ? 'bell' : 'bellOff', label: r.auto_send === 0 ? 'تشغيل التنبيهات' : 'إيقاف التنبيهات مؤقتاً', fn: () => run(() => patch(P, { auto_send: r.auto_send === 0 ? 1 : 0 }), r.auto_send === 0 ? 'التنبيهات تعمل' : 'أوقفنا التنبيهات لهذه القناة') },
    { icon: r.enabled ? 'pause' : 'play', label: r.enabled ? 'إيقاف المراقبة' : 'تشغيل المراقبة', fn: () => run(() => patch(P, { enabled: !r.enabled }), r.enabled ? 'أُوقفت المراقبة' : 'المراقبة تعمل') },
    { icon: 'edit', label: 'تغيير الاسم المعروض', fn: async () => { const v = await prompt({ title: 'الاسم المعروض', label: 'يظهر في الموقع وفي {name} داخل الرسالة', value: r.name }); if (v) run(() => patch(P, { name: v }), 'حُفظ الاسم'); } },
    { icon: 'refresh', label: 'تحديث الصورة والبيانات', fn: () => run(() => post(P + '/refresh'), 'حُدّثت البيانات') },
    kind === 'tg' && r.username && { icon: 'ext', label: 'فتح القناة في تيليجرام', fn: () => window.open(urlOf(kind, r), '_blank', 'noopener') },
    '-',
    { icon: 'trash', label: kind === 'tg' ? 'إزالة القناة' : 'حذف القناة', danger: true, fn: async () => { if (await confirm('سيتوقف كل شيء مرتبط بـ «' + (r.name || handleOf(kind, r)) + '». لا يمكن التراجع.', { title: 'حذف القناة؟', ok: 'حذف', danger: true })) run(() => del(P), 'حُذفت القناة'); } },
  ], { title: r.name || handleOf(kind, r), sub: '\u2066' + handleOf(kind, r) + '\u2069' });
}

// ─── تخصيص الرسالة ───
const VARS = { kick: ['{name}', '{title}', '{url}'], tt: ['{name}', '{title}', '{url}'], yt: ['{name}', '{title}', '{url}'], tw: ['{name}', '{username}', '{text}', '{url}'] };
export async function editMessage(kind, r, reload) {
  const m = (r.msg || '').match(/\{img:([^}]+)\}/);
  let img = m ? m[1] : '';
  const cur = (r.msg || '').replace(/\{img:[^}]+\}/g, '').trim();
  const def = (S.me && S.me['tpl_' + kind]) || '';
  const defBtn = (S.me && S.me['btn_' + kind]) || KIND[kind].btn;
  const sample = t => t.replace(/\{name\}/g, r.name || 'اسم القناة').replace(/\{title\}/g, kind === 'yt' ? 'عنوان الفيديو الجديد' : 'عنوان البث').replace(/\{text\}/g, 'نص التغريدة يظهر هنا')
    .replace(/\{username\}/g, r.username || '').replace(/\{url\}/g, urlOf(kind, r));
  await sheet({
    title: 'رسالة التنبيه', sub: 'كيف يظهر التنبيه في قنواتك — اتركه فارغاً لاستخدام القالب العام', size: 'xwide',
    body: html`<div class="grid2" style="gap:18px;align-items:start" data-cols><div>
      <label class="field"><span>نص الرسالة</span><textarea name="msg" rows="6" placeholder="${def}">${cur}</textarea></label>
      <div class="vars">${VARS[kind].map(v => html`<button type="button" data-ins="${v}">${v}</button>`)}<button type="button" data-ins="<b></b>"><b>B</b></button></div>
      <label class="field"><span>نص الزر</span><input name="btn" maxlength="60" value="${r.btn_text || ''}" placeholder="${defBtn}"></label>
      <div class="field"><span>صورة ثابتة (اختياري — بدل صورة البث)</span><div class="imgbox" data-box>${img ? html`<img src="${img}" alt="">` : 'بدون صورة'}</div>
        <div class="hstack" style="margin-top:8px"><button type="button" class="btn sm soft" data-up>${ic('upload')} رفع</button><button type="button" class="btn sm ghost" data-clr>${ic('x')} إزالة</button></div></div>
    </div><div data-prev></div></div>`,
    actions: [{ label: 'استعادة الافتراضي', kind: 'ghost', handler: async () => { await patch('/api/channels/' + kind + '/' + r.id, { msg: '', btn_text: '' }); ok('عادت للقالب العام'); drop('ch:' + kind); reload(); } },
      { label: 'حفظ', kind: 'pri', handler: async ({ root }) => {
        let msg = $('[name=msg]', root).value.trim();
        if (img) msg = (msg ? msg + '\n' : '') + '{img:' + img + '}';
        await patch('/api/channels/' + kind + '/' + r.id, { msg, btn_text: $('[name=btn]', root).value.trim() });
        ok('حُفظت الرسالة'); drop('ch:' + kind); reload();
      } }],
    onMount: ({ root }) => {
      if (innerWidth < 760) $('[data-cols]', root).style.gridTemplateColumns = '1fr';
      const ta = $('[name=msg]', root), bt = $('[name=btn]', root), prev = $('[data-prev]', root);
      const paint = () => { prev.innerHTML = tgPreview(sample(ta.value.trim() || def), img || (kind === 'yt' ? '' : r.banner || r.thumb || ''), bt.value.trim() || defBtn).s; };
      root.addEventListener('input', paint); paint();
      root.addEventListener('click', async e => {
        const ins = e.target.closest('[data-ins]');
        if (ins) { const v = ins.dataset.ins, s = ta.selectionStart; ta.value = ta.value.slice(0, s) + v + ta.value.slice(ta.selectionEnd); ta.focus(); ta.selectionStart = ta.selectionEnd = s + (v === '<b></b>' ? 3 : v.length); paint(); }
        if (e.target.closest('[data-up]')) { const f = await pickFile(); if (!f) return; try { img = (await upload(f)).url; $('[data-box]', root).innerHTML = '<img src="' + esc(img) + '" alt="">'; paint(); } catch (x) { bad(x); } }
        if (e.target.closest('[data-clr]')) { img = ''; $('[data-box]', root).textContent = 'بدون صورة'; paint(); }
      });
    },
  });
}

// ─── فلترة X ───
export function filtersForm(f = {}) {
  const ck = (k, t, s) => html`<label class="row" style="padding-inline:0"><span class="row-tx"><b>${t}</b>${s ? html`<small>${s}</small>` : ''}</span><span class="switch"><input type="checkbox" name="${k}" ${f[k] ? raw('checked') : ''}><i></i></span></label>`;
  const j = v => (v || []).join('، ');
  return html`<div data-filters>
    ${ck('skip_retweets', 'تجاهل إعادة التغريد')}${ck('skip_replies', 'تجاهل الردود')}${ck('skip_quotes', 'تجاهل الاقتباسات')}
    ${ck('only_media', 'فقط التغريدات التي فيها صورة أو فيديو')}${ck('block_youtube', 'تجاهل التغريدات التي فيها رابط يوتيوب', 'مفيد إذا كانت قناة يوتيوب نفسها مضافة لديك')}
    <div class="sp"></div>
    <label class="field"><span>كلمات تمنع الإرسال</span><input name="block_words" value="${j(f.block_words)}" placeholder="إعلان، مسابقة"><small>افصل بين الكلمات بفاصلة</small></label>
    <label class="field"><span>أرسل فقط إذا احتوت إحدى هذه الكلمات</span><input name="require_words" value="${j(f.require_words)}" placeholder="اختياري"></label>
    <label class="field"><span>روابط تمنع الإرسال</span><input name="block_domains" class="ltr" value="${j(f.block_domains)}" placeholder="twitch.tv, discord.gg"></label>
    <label class="field"><span>أقل عدد أحرف</span><input name="min_chars" type="number" min="0" max="280" value="${f.min_chars || ''}" placeholder="0"></label></div>`;
}
export function readFilters(root) {
  const g = n => $('[name=' + n + ']', root);
  return { skip_retweets: g('skip_retweets').checked, skip_replies: g('skip_replies').checked, skip_quotes: g('skip_quotes').checked, only_media: g('only_media').checked,
    block_youtube: g('block_youtube').checked, block_words: g('block_words').value, require_words: g('require_words').value, block_domains: g('block_domains').value, min_chars: parseInt(g('min_chars').value || '0', 10) || 0 };
}
async function editFilters(r, reload) {
  let f = {}; try { f = JSON.parse(r.filters || '{}') || {}; } catch (e) {}
  await sheet({ title: 'فلترة تغريدات @' + r.username, sub: 'التغريدة التي لا تطابق هذه الشروط لا تصل لقنواتك', size: 'wide', body: filtersForm(f),
    actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: 'حفظ الفلترة', kind: 'pri', handler: async ({ root }) => { await patch('/api/channels/tw/' + r.id, { filters: readFilters(root) }); ok('حُفظت الفلترة'); drop('ch:tw'); reload(); } }] });
}

// ─── الإضافة ───
export async function addChannel(kind, reload) {
  if (!canWrite()) return toast('الموقع في صيانة — الإضافة متوقفة مؤقتاً', 'bad');
  if (kind === 'tw' && !(S.me && S.me.has_twitter)) return toast('متابعة X غير مفعّلة بعد — الإدارة لم تضف مفتاح API', 'bad');
  const K = KIND[kind];
  let sugg = [];
  try { sugg = (await api('/api/channels/' + kind + '/suggestions')).rows || []; } catch (e) {}
  const lim = (S.me && S.me.limits) ? { limit: S.me.limits[kind], used: (S.me.usage || {})[kind] || 0 } : null;
  await sheet({
    title: 'إضافة ' + (kind === 'tw' ? 'حساب X' : kind === 'tt' ? 'حساب تيك توك' : 'قناة ' + K.name), size: sugg.length ? 'wide' : '',
    body: html`
      ${!S.boot.has_telegram ? html`<div class="callout warn" style="margin-bottom:14px">${ic('warn')}<div>بوت تيليجرام غير مضبوط في الخادم، فلن تصل التنبيهات لقنواتك حتى تضبطه الإدارة.</div></div>` : ''}
      <label class="field"><span>${kind === 'yt' ? 'القناة' : 'الحساب'}</span><input name="v" class="ltr" placeholder="${K.ph}" autocomplete="off" autocapitalize="off" spellcheck="false" autofocus><small>${K.hint}</small></label>
      <details style="margin-bottom:12px"><summary class="mu" style="cursor:pointer;font-size:var(--fs-1)">خيارات إضافية</summary><div style="padding-top:12px">
        <label class="field"><span>اسم معروض (اختياري)</span><input name="name" maxlength="80" placeholder="يُجلب تلقائياً"></label>
        <label class="field"><span>نص الزر (اختياري)</span><input name="btn" maxlength="60" placeholder="${K.btn}"></label>
        ${kind === 'tw' ? filtersForm({}) : ''}</div></details>
      ${sugg.length ? html`<div class="group-title" style="margin-top:6px">${ic('sparkle')} مقترحة من الإدارة — اختر واحدة أو أكثر</div>
        <div class="picks cols" data-sugg>${sugg.map(s => html`<button type="button" class="pick" data-id="${s.id}">${avatar(s.avatar, s.name)}<span class="row-tx"><b class="clip">${s.name || s.identifier}</b><small class="clip ltr" style="text-align:start">${s.alias || s.identifier}</small></span><span class="ck">${ic('check')}</span></button>`)}</div>
        <div class="hstack" style="margin-top:10px"><span class="mu" data-cnt style="font-size:var(--fs-1)">لم تختر شيئاً</span><button type="button" class="btn sm ghost" data-all style="margin-inline-start:auto">تحديد الكل</button></div>` : ''}
      ${lim && lim.limit < 9999 ? html`<div class="hint" style="margin-top:14px">استخدمت ${lim.used} من ${lim.limit}</div>` : ''}`,
    actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: 'إضافة', icon: 'plus', kind: 'pri', handler: async ({ root }) => {
      const ids = $$('[data-sugg] .pick.on', root).map(x => +x.dataset.id);
      const v = $('[name=v]', root).value.trim();
      if (ids.length) {
        const r = await post('/api/channels/' + kind + '/bulk-add', { ids });
        ok('أضفنا ' + (r.added || 0) + (r.failed ? ' — تعذّر ' + r.failed : ''));
        if (r.errors && r.errors.length) setTimeout(() => toast(r.errors[0], 'info'), 700);
      }
      if (v) {
        const body = { input: v, name: $('[name=name]', root).value.trim(), btn_text: $('[name=btn]', root).value.trim(), msg: '' };
        if (kind === 'tw') body.filters = readFilters(root);
        const r = await post('/api/channels/' + kind, body);
        ok((r.name ? '«' + r.name + '» ' : '') + 'أُضيفت' + (r.from_suggestion ? ' من المقترحة' : ''));
        if (r.warn) setTimeout(() => toast(r.warn, 'info'), 700);
      }
      if (!ids.length && !v) { toast('اكتب اسم ' + (kind === 'yt' ? 'القناة' : 'الحساب') + ' أو اختر من المقترحة', 'bad'); return false; }
      drop('ch:' + kind); drop('home'); await reload(true);
    } }],
    onMount: ({ root }) => {
      const cnt = () => { const n = $$('[data-sugg] .pick.on', root).length; const c = $('[data-cnt]', root); if (c) c.textContent = n ? 'اخترت ' + n : 'لم تختر شيئاً'; };
      root.addEventListener('click', e => {
        const p = e.target.closest('[data-sugg] .pick'); if (p) { p.classList.toggle('on'); cnt(); }
        if (e.target.closest('[data-all]')) { const all = $$('[data-sugg] .pick', root); const on = all.every(x => x.classList.contains('on')); all.forEach(x => x.classList.toggle('on', !on)); cnt(); }
      });
      $('[name=v]', root).addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); $('.sheet-foot .btn.pri', root.closest('.sheet')).click(); } });
    },
  });
}
