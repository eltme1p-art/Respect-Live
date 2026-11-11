// ديسكورد: رومات تنقلها الإدارة، وأنت تختار أي قنوات تيليجرام تستقبلها
import { S, api, post, patch, del, upload, pickFile, load, peek, drop, isOwner } from '../core/api.js?v=__BUILD__';
import { html, raw, render, $, $$, ic, avatar, num, esc } from '../core/dom.js?v=__BUILD__';
import { sheet, toast, ok, bad, confirm, menu, empty, skelGrid, errorBox } from '../core/ui.js?v=__BUILD__';
import { platSeg } from './channels.js?v=__BUILD__';
import { tgPreview } from '../components/compose.js?v=__BUILD__';
import { navigate } from '../core/router.js?v=__BUILD__';

const name = (f, d) => (f.display_name || '').trim() || (d.known_channels[f.channel_id] || {}).name || f.channel_name || f.channel_id;
const arr = s => { try { const v = JSON.parse(s || '[]'); return Array.isArray(v) ? v : []; } catch (e) { return []; } };

export default {
  async render(ctx) {
    const paint = (d, err) => {
      if (!ctx.alive()) return;
      const own = d && d.is_owner;
      render(ctx.root, html`${platSeg('dc')}
        <header class="page-head"><span class="pi dc">${ic('dc')}</span><div><h1>ديسكورد</h1><p>${own ? (d.bot_ready ? 'الحساب متصل ويقرأ ' + num(Object.keys(d.known_channels).length) + ' روم' : 'الحساب غير متصل حالياً') : 'اختر الرومات التي تريد أن تصل رسائلها لقنواتك.'}</p></div>
          ${own ? html`<div class="acts"><button class="btn ghost" data-sync>${ic('refresh')}<span>تحديث الرومات</span></button><button class="btn pri" data-add>${ic('plus')} ربط روم</button></div>` : ''}</header>
        ${own && !d.bot_ready ? html`<div class="callout warn" style="margin-bottom:14px">${ic('warn')}<div><b>حساب ديسكورد غير متصل</b><br>تأكد من متغير DISCORD_BOT_TOKEN في الخادم. الرسائل لن تُنقل حتى يتصل.</div></div>` : ''}
        ${err ? errorBox(err, true) : !d ? skelGrid(3) : !d.rows.length ? empty('dc', 'لا توجد رومات مربوطة', own ? 'اربط روم ديسكورد، ثم يختار المستخدمون قنواتهم لاستقبال رسائله.' : 'لم تضف الإدارة رومات بعد.', own ? html`<button class="btn pri" data-add>${ic('plus')} ربط روم</button>` : '')
          : html`<div class="grid">${d.rows.map(f => { const subs = f.my_subs || []; const kw = arr(f.keyword_rules).length, ib = arr(f.ignore_bots).length;
            return html`<article class="ch ${f.enabled ? '' : 'off'}" data-id="${f.id}"><div class="ch-body" style="padding-top:16px">
              <div class="hstack" style="margin-bottom:12px;flex-wrap:nowrap"><span class="pi dc">${ic('hash')}</span><div class="grow"><div class="ch-name clip">${name(f, d)}</div><div class="mu clip" style="font-size:var(--fs-0)">${(d.guilds[f.guild_id] || {}).name || (d.known_channels[f.channel_id] || {}).guild || ''}</div></div>${f.enabled ? '' : html`<span class="tag">موقوف</span>`}</div>
              <div class="ch-meta">${subs.length ? html`<span class="tag ok">${ic('check')} يصل لـ ${num(subs.length)} من قنواتك</span>` : html`<span class="tag">لا يصلك</span>`}
                ${own ? html`<span class="tag">${ic('users')} ${num(f.subs_count || 0)} اشتراك</span>${f.use_original ? '' : html`<span class="tag ac">قالب</span>`}${kw ? html`<span class="tag violet">${num(kw)} قاعدة صورة</span>` : ''}${ib ? html`<span class="tag warn">${num(ib)} بوت مستثنى</span>` : ''}${f.use_ai ? html`<span class="tag violet">${ic('sparkle')} AI</span>` : ''}` : ''}</div></div>
              <div class="ch-acts"><button class="btn sm ${subs.length ? 'soft' : 'pri'} grow" data-act="sub">${ic('tg')} ${subs.length ? 'قنواتي المستقبلة' : 'استقبل في قنواتي'}</button>${own ? html`<button class="btn sm icon" data-act="edit" aria-label="تخصيص">${ic('edit')}</button><button class="btn sm icon" data-act="more" aria-label="المزيد">${ic('more')}</button>` : ''}</div></article>`; })}</div>`}`);
    };
    const segFix = () => { const on = $('.seg.plat .on', ctx.root); if (on) on.parentElement.scrollLeft = on.offsetLeft - on.parentElement.clientWidth / 2 + on.clientWidth / 2; };
    const reload = async () => { try { paint(await load('dc', '/api/discord/feeds', 0)); } catch (e) { paint(peek('dc'), peek('dc') ? null : e); } segFix(); };
    ctx.onRefresh(reload);
    ctx.root.addEventListener('click', async e => {
      const d = peek('dc'); if (!d) return;
      if (e.target.closest('[data-retry]')) return reload();
      if (e.target.closest('[data-sync]')) { try { const r = await post('/api/discord/refresh'); ok('وجدنا ' + num(r.channels) + ' روم'); drop('dc'); reload(); } catch (x) { bad(x); } return; }
      if (e.target.closest('[data-add]')) return addFeed(d, reload);
      const c = e.target.closest('.ch'); if (!c) return;
      const f = d.rows.find(x => x.id === +c.dataset.id); const a = e.target.closest('[data-act]'); if (!a || !f) return;
      if (a.dataset.act === 'sub') return subscribe(f, d, reload);
      if (a.dataset.act === 'edit') return editFeed(f, d, reload);
      if (a.dataset.act === 'more') return menu([
        { icon: f.enabled ? 'pause' : 'play', label: f.enabled ? 'إيقاف النقل' : 'تشغيل النقل', fn: async () => { try { await patch('/api/discord/feeds/' + f.id, { enabled: !f.enabled }); drop('dc'); reload(); } catch (x) { bad(x); } } },
        '-', { icon: 'trash', label: 'حذف الربط', danger: true, fn: async () => { if (!await confirm('ستتوقف رسائل هذا الروم عن الوصول لكل المشتركين.', { title: 'حذف الربط؟', ok: 'حذف', danger: true })) return; try { await del('/api/discord/feeds/' + f.id); ok('حُذف الربط'); drop('dc'); reload(); } catch (x) { bad(x); } } },
      ], { title: '#' + name(f, d) });
    });
    paint(peek('dc')); await reload();
  },
};

async function subscribe(f, d, reload) {
  const tgs = d.my_tgs || [];
  if (!tgs.length) return sheet({ title: 'لا توجد قنوات تيليجرام', sub: 'وثّق قناة تيليجرام أولاً لتستقبل فيها رسائل ديسكورد.', size: 'sm', actions: [{ label: 'لاحقاً', kind: 'ghost' }, { label: 'توثيق قناة', kind: 'pri', handler: () => { setTimeout(() => navigate('/telegram?verify=1'), 80); } }] });
  const mine = new Set(f.my_subs || []);
  await sheet({ title: 'أين تصل رسائل #' + name(f, d) + '؟', size: 'wide',
    body: html`<div class="picks">${tgs.map(t => html`<button type="button" class="pick ${mine.has(t.id) ? 'on' : ''}" data-id="${t.id}">${avatar(t.avatar, t.name, 'sm')}<span class="row-tx"><b>${t.name}</b><small class="ltr" style="text-align:start">${t.username || ''}</small></span><span class="ck">${ic('check')}</span></button>`)}</div>`,
    actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: 'حفظ', kind: 'pri', handler: async ({ root }) => { const ids = $$('.pick.on', root).map(x => +x.dataset.id); await post('/api/discord/feeds/' + f.id + '/subscribe', { tg_channel_ids: ids }); ok(ids.length ? 'ستصل الرسائل إلى ' + ids.length + ' قناة' : 'أوقفنا الاستقبال'); drop('dc'); reload(); } }],
    onMount: ({ root }) => root.addEventListener('click', e => { const p = e.target.closest('.pick'); if (p) p.classList.toggle('on'); }) });
}

async function addFeed(d, reload) {
  const linked = new Set(d.rows.map(f => f.channel_id));
  const avail = Object.entries(d.known_channels).filter(([id]) => !linked.has(id));
  if (!avail.length) return toast(Object.keys(d.known_channels).length ? 'كل الرومات مربوطة' : 'لم نكتشف رومات — اضغط «تحديث الرومات»', 'bad');
  await sheet({ title: 'ربط روم ديسكورد', size: 'wide',
    body: html`<label class="search" style="display:block;margin-bottom:12px">${ic('search')}<input type="search" placeholder="ابحث عن روم…" data-q></label>
      <div class="picks" data-list style="max-height:320px;overflow:auto">${avail.map(([id, c]) => html`<button type="button" class="pick" data-id="${id}" data-n="${(c.name + ' ' + c.guild).toLowerCase()}"><span class="pi sm dc">${ic('hash')}</span><span class="row-tx"><b>${c.name}</b><small>${c.guild || ''}</small></span><span class="ck">${ic('check')}</span></button>`)}</div>
      <label class="row" style="padding-inline:0;margin-top:10px"><span class="row-tx"><b>نسخ الرسالة كما هي</b><small>بدون قالب — يمكنك تغييره لاحقاً</small></span><span class="switch"><input type="checkbox" name="orig" checked><i></i></span></label>`,
    actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: 'ربط', kind: 'pri', handler: async ({ root }) => {
      const p = $('.pick.on', root); if (!p) { toast('اختر روماً', 'bad'); return false; }
      const c = d.known_channels[p.dataset.id];
      await post('/api/discord/feeds', { channel_id: p.dataset.id, channel_name: c.name, guild_id: c.guild_id, use_original: $('[name=orig]', root).checked });
      ok('رُبط #' + c.name); drop('dc'); reload();
    } }],
    onMount: ({ root }) => {
      root.addEventListener('click', e => { const p = e.target.closest('.pick'); if (p) $$('.pick', root).forEach(x => x.classList.toggle('on', x === p)); });
      $('[data-q]', root).addEventListener('input', e => { const v = e.target.value.toLowerCase(); $$('[data-list] .pick', root).forEach(x => { x.hidden = v && !x.dataset.n.includes(v); }); });
    } });
}

async function editFeed(f, d, reload) {
  let bots = []; try { bots = (await api('/api/discord/bots')).rows || []; } catch (e) {}
  const ig = new Set(arr(f.ignore_bots).map(String));
  const rules = arr(f.keyword_rules).map(r => ({ keywords: r.keywords || [], image: r.image || '', caption: r.caption || r.text || '' }));
  const ruleHTML = (r, i) => html`<div class="card pad" data-rule="${i}" style="margin-bottom:10px">
    <div class="hstack" style="margin-bottom:10px"><b style="font-size:var(--fs-2)">قاعدة ${i + 1}</b><button type="button" class="btn sm ghost icon" data-rdel style="margin-inline-start:auto" aria-label="حذف القاعدة">${ic('trash')}</button></div>
    <label class="field"><span>إذا احتوت الرسالة على</span><input data-kw value="${r.keywords.join('، ')}" placeholder="كلمة، كلمة أخرى"><small>افصل بفاصلة</small></label>
    <div class="grid2"><label class="field"><span>أرسل هذه الصورة</span><div class="hstack" style="flex-wrap:nowrap"><input data-img class="input ltr" value="${r.image}" placeholder="https://…"><button type="button" class="btn icon" data-rup aria-label="رفع">${ic('upload')}</button></div></label>
    <label class="field"><span>وبدّل النص بـ (اختياري)</span><input data-cap value="${r.caption}"></label></div></div>`;
  await sheet({ title: 'تخصيص #' + name(f, d), size: 'xwide',
    body: html`<div class="grid2" style="gap:18px;align-items:start" data-cols><div>
      <label class="row" style="padding-inline:0"><span class="row-tx"><b>نسخ الرسالة كما هي</b><small>أطفئه لاستخدام القالب أدناه</small></span><span class="switch"><input type="checkbox" name="orig" ${f.use_original ? raw('checked') : ''}><i></i></span></label>
      <label class="field"><span>القالب</span><textarea name="tpl" rows="4" class="code" placeholder="<b>{author_no_at}</b>&#10;&#10;{content}">${f.template || ''}</textarea></label>
      <div class="vars">${['{author_no_at}', '{content}', '{title}', '{description}', '{channel}', '{url}'].map(v => html`<button type="button" data-ins="${v}">${v}</button>`)}</div>
      <div class="grid2"><label class="field"><span>اسم الروم في الموقع</span><input name="dn" maxlength="100" value="${f.display_name || ''}" placeholder="${(d.known_channels[f.channel_id] || {}).name || f.channel_name}"></label>
        <label class="field"><span>نص الزر</span><input name="btn" maxlength="60" value="${f.btn_text || 'عرض الروم'}"></label></div>
      <label class="field"><span>رابط الزر (اختياري)</span><input name="ru" class="ltr" value="${f.room_url || ''}" placeholder="افتراضياً: رابط الرسالة في ديسكورد"></label>
      <label class="field"><span>صورة ثابتة (اختياري)</span><input name="fi" class="ltr" value="${f.fixed_image || ''}" placeholder="https://…"></label>
      ${S.me.has_groq ? html`<label class="row" style="padding-inline:0"><span class="row-tx"><b>إعادة صياغة بالذكاء الاصطناعي</b><small>Groq يعيد كتابة الرسالة قبل الإرسال</small></span><span class="switch"><input type="checkbox" name="ai" ${f.use_ai ? raw('checked') : ''}><i></i></span></label>
        <label class="field"><span>تعليمات الصياغة</span><textarea name="aip" rows="2" placeholder="اختصر الرسالة بأسلوب إخباري">${f.ai_prompt || ''}</textarea></label>` : ''}
      <div class="group-title" style="margin-top:8px">${ic('image')} قواعد الصور حسب الكلمات</div><div data-rules>${rules.map(ruleHTML)}</div><button type="button" class="btn sm soft" data-radd>${ic('plus')} قاعدة جديدة</button>
      <div class="group-title">${ic('ai')} بوتات لا تُنقل رسائلها</div>
      <div class="picks cols" data-bots>${bots.length ? bots.map(b => html`<button type="button" class="pick ${ig.has(b.id) ? 'on' : ''}" data-id="${b.id}">${avatar(b.avatar, b.name, 'sm')}<span class="row-tx"><b class="clip">${b.name}</b><small>${num(b.seen_count)} رسالة</small></span><span class="ck">${ic('check')}</span></button>`) : html`<div class="hint">لم نرصد بوتات بعد</div>`}</div>
    </div><div data-prev style="position:sticky;top:0"></div></div>`,
    actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: 'حفظ', kind: 'pri', handler: async ({ root }) => {
      const g = n => $('[name=' + n + ']', root);
      const kr = $$('[data-rule]', root).map(el => ({ keywords: $('[data-kw]', el).value.split(/[,،\n]+/).map(s => s.trim()).filter(Boolean), image: $('[data-img]', el).value.trim(), caption: $('[data-cap]', el).value.trim() })).filter(r => r.keywords.length);
      await patch('/api/discord/feeds/' + f.id, { use_original: g('orig').checked, template: g('tpl').value.trim(), display_name: g('dn').value.trim(), btn_text: g('btn').value.trim() || 'عرض الروم',
        room_url: g('ru').value.trim(), fixed_image: g('fi').value.trim(), use_ai: g('ai') ? g('ai').checked : !!f.use_ai, ai_prompt: g('aip') ? g('aip').value.trim() : f.ai_prompt || '',
        keyword_rules: kr, ignore_bots: $$('[data-bots] .pick.on', root).map(x => x.dataset.id) });
      ok('حُفظ التخصيص'); drop('dc'); reload();
    } }],
    onMount: ({ root }) => {
      if (innerWidth < 760) $('[data-cols]', root).style.gridTemplateColumns = '1fr';
      const ta = $('[name=tpl]', root), prev = $('[data-prev]', root);
      const paintP = () => { const orig = $('[name=orig]', root).checked; const t = orig ? '<b>اسم الكاتب</b>\n\n<b>نص الرسالة كما كُتب في ديسكورد</b>' : (ta.value || '<b>{author_no_at}</b>\n\n<b>{content}</b>').replace(/\{author_no_at\}|\{author\}|\{name\}/g, 'اسم الكاتب').replace(/\{content\}/g, 'نص الرسالة').replace(/\{title\}/g, 'العنوان').replace(/\{description\}/g, 'الوصف').replace(/\{channel\}/g, name(f, d)).replace(/\{url\}/g, 'https://discord.com/…');
        prev.innerHTML = tgPreview(t, $('[name=fi]', root).value.trim(), $('[name=btn]', root).value.trim()).s; };
      root.addEventListener('input', paintP); root.addEventListener('change', paintP); paintP();
      root.addEventListener('click', async e => {
        const ins = e.target.closest('[data-ins]'); if (ins) { const s = ta.selectionStart; ta.value = ta.value.slice(0, s) + ins.dataset.ins + ta.value.slice(ta.selectionEnd); ta.focus(); paintP(); }
        if (e.target.closest('[data-radd]')) { const box = $('[data-rules]', root); box.insertAdjacentHTML('beforeend', ruleHTML({ keywords: [], image: '', caption: '' }, box.children.length).s); }
        if (e.target.closest('[data-rdel]')) e.target.closest('[data-rule]').remove();
        const up = e.target.closest('[data-rup]'); if (up) { const file = await pickFile(); if (!file) return; try { $('[data-img]', up.closest('[data-rule]')).value = (await upload(file)).url; } catch (x) { bad(x); } }
        const b = e.target.closest('[data-bots] .pick'); if (b) b.classList.toggle('on');
      });
    } });
}
