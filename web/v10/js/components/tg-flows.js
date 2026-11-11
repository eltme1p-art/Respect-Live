// توثيق قناة تيليجرام + ربط الحساب الشخصي (للعضوية والإرسال التجريبي)
import { S, api, post, drop, canWrite, emit } from '../core/api.js?v=__BUILD__';
import { html, raw, $, $$, ic, avatar, sleep } from '../core/dom.js?v=__BUILD__';
import { sheet, toast, ok, bad, confirm, alertSheet, copy } from '../core/ui.js?v=__BUILD__';

const botBtn = (label = 'فتح البوت في تيليجرام') => S.boot.bot_link ? html`<a class="btn soft block" href="${S.boot.bot_link}" target="_blank" rel="noopener" style="margin-top:10px">${ic('tg')} ${label}${S.boot.bot_username ? html` <span class="ltr mu">@${S.boot.bot_username}</span>` : ''}</a>` : '';
export const tgErr = (e, title) => {
  const m = (e && e.message) || 'خطأ';
  if (m.length <= 70 && !(e && e.data && (e.data.need_start || e.data.bot_link))) return bad(e);
  return alertSheet(title || 'تعذّر الإكمال', m, { extra: botBtn().s });
};
async function refreshMe() { try { S.me = await api('/api/me'); emit('me:changed'); } catch (e) {} }

// ═══ توثيق القناة ═══
export async function verifyChannel(onDone) {
  if (!canWrite()) return toast('الموقع في صيانة — التوثيق متوقف مؤقتاً', 'bad');
  if (!S.boot.has_telegram) return alertSheet('تيليجرام غير مضبوط', 'بوت تيليجرام غير مضبوط في الخادم بعد. تواصل مع الإدارة.');
  const L = S.me.limits || {}, used = (S.me.usage || {}).tg || 0;
  if (L.tg != null && used >= L.tg) return alertSheet('وصلت الحد', 'يمكنك توثيق ' + L.tg + ' قناة كحد أقصى.' + (S.me.user.is_member ? '' : '\nاربط حسابك وانضم للقناة الرسمية لمضاعفة الحد.'));
  let state = null;
  const res = await sheet({
    title: 'توثيق قناة تيليجرام', sub: 'نتأكد أنك تملك القناة عبر رسالة تصل لمشرفها', size: 'wide',
    body: html`<div class="stepper"><i class="on"></i><i></i><i></i></div>
      <div class="callout warn">${ic('warn')}<div><b>قبل البدء</b><br>أضف البوت <b>كمشرف</b> في قناتك مع صلاحية نشر الرسائل.${botBtn('رابط البوت — أضفه لقناتك')}</div></div>
      <div class="sp"></div>
      <label class="field"><span>القناة</span><input name="c" class="ltr" placeholder="@channel أو t.me/channel أو -100…" autocomplete="off" autocapitalize="off" autofocus><small>للقنوات الخاصة اكتب رقم القناة الذي يبدأ بـ ‎-100</small></label>`,
    actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: 'متابعة', kind: 'pri', handler: async ({ root }) => {
      const v = $('[name=c]', root).value.trim(); if (!v) { toast('اكتب معرّف القناة', 'bad'); return false; }
      try { state = await post('/api/tg/verify/start', { chat_id: v }); return true; } catch (e) { tgErr(e, 'تعذّر الوصول للقناة'); return false; }
    } }],
  });
  if (!res || !state) return;
  let adminId = state.auto_admin_id, adminName = (state.admins[0] || {}).name;
  if (state.admins.length > 1) {
    const owner = state.admins.find(a => a.is_owner) || state.admins[0];
    const pickRes = await sheet({
      title: 'من يستلم رسالة التأكيد؟', sub: 'يجب أن يكون قد فتح البوت وضغط Start مرة واحدة', size: 'wide',
      body: html`<div class="stepper"><i class="on"></i><i class="on"></i><i></i></div>${chatHead(state)}<div class="picks" data-admins>${state.admins.map(a => html`<button type="button" class="pick ${a.id === owner.id ? 'on' : ''}" data-id="${a.id}">${avatar('', a.name, 'sm round')}<span class="row-tx"><b>${a.name} ${a.is_owner ? ic('crown') : ''}</b><small class="ltr" style="text-align:start">${a.username || ''}</small></span><span class="ck">${ic('check')}</span></button>`)}</div>`,
      actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: 'إرسال الرسالة', kind: 'pri', handler: ({ root }) => { const p = $('[data-admins] .pick.on', root); return p ? p.dataset.id : false; } }],
      onMount: ({ root }) => root.addEventListener('click', e => { const p = e.target.closest('.pick'); if (p) $$('.pick', root).forEach(x => x.classList.toggle('on', x === p)); }),
    });
    if (!pickRes) { post('/api/tg/verify/' + state.verify_id + '/cancel').catch(() => {}); return; }
    adminId = pickRes; adminName = (state.admins.find(a => a.id === adminId) || {}).name;
  }
  try { await post('/api/tg/verify/' + state.verify_id + '/send', { admin_id: adminId }); }
  catch (e) { return tgErr(e, 'المشرف لم يفعّل البوت بعد'); }
  // انتظار ضغط «نعم» في تيليجرام
  let stop = false, confirmed = false;
  const waitRes = await sheet({
    title: 'بانتظار التأكيد', size: 'wide',
    body: html`<div class="stepper"><i class="on"></i><i class="on"></i><i></i></div>${chatHead(state)}
      <div class="wait"><div class="ring"></div><div class="mu2" style="line-height:1.9;font-size:var(--fs-2)">أرسلنا رسالة إلى <b>${adminName || 'المشرف'}</b> في تيليجرام.<br>عندما يضغط «نعم» يظهر له رمز من 6 أرقام.</div><div class="mu num" data-left style="font-size:var(--fs-1)"></div></div>`,
    actions: [{ label: 'إلغاء الطلب', kind: 'ghost', value: 'cancel' }, { label: 'معي الرمز', kind: 'pri', value: 'code' }],
    onMount: async ({ root, close }) => {
      let left = 600; const lb = $('[data-left]', root);
      const tick = setInterval(() => { left--; if (lb) lb.textContent = 'ينتهي الطلب خلال ' + Math.floor(left / 60) + ':' + String(left % 60).padStart(2, '0'); if (left <= 0) { clearInterval(tick); close('expired'); } }, 1000);
      while (!stop && left > 0) {
        await sleep(2500); if (stop) break;
        try { const s = await api('/api/tg/verify/' + state.verify_id); if (s.status === 'confirmed') { confirmed = true; close('code'); break; } if (['cancelled', 'expired', 'failed'].includes(s.status)) { close(s.status); break; } } catch (e) {}
      }
      clearInterval(tick);
    },
    onClose: () => { stop = true; },
  });
  stop = true;
  if (waitRes === 'cancelled') return toast('ألغى المشرف الطلب من تيليجرام', 'bad');
  if (waitRes === 'expired') return toast('انتهت مدة الطلب — ابدأ من جديد', 'bad');
  if (waitRes !== 'code') { post('/api/tg/verify/' + state.verify_id + '/cancel').catch(() => {}); return; }
  const done = await sheet({
    title: 'أدخل رمز التأكيد', sub: confirmed ? 'المشرف أكّد — انسخ الرمز من رسالة البوت' : 'الرمز صالح لمدة 5 دقائق', size: 'sm',
    body: html`<div class="stepper"><i class="on"></i><i class="on"></i><i class="on"></i></div><input class="code-in" name="code" inputmode="numeric" maxlength="6" placeholder="••••••" autocomplete="one-time-code" autofocus>`,
    actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: 'تأكيد وإضافة', kind: 'pri', handler: async ({ root }) => {
      const c = $('[name=code]', root).value.replace(/\D/g, ''); if (c.length !== 6) { toast('الرمز 6 أرقام', 'bad'); return false; }
      await post('/api/tg/verify/' + state.verify_id + '/code', { code: c }); return true;
    } }],
    onMount: ({ root }) => { const i = $('[name=code]', root); i.addEventListener('input', () => { i.value = i.value.replace(/\D/g, '').slice(0, 6); if (i.value.length === 6) $('.sheet-foot .btn.pri', root.closest('.sheet')).click(); }); },
  });
  if (done) { ok('وُثّقت «' + state.chat_name + '» — التنبيهات ستصلها من الآن'); drop('ch:tg'); drop('home'); await refreshMe(); onDone && onDone(); }
}
const chatHead = s => html`<div class="card" style="display:flex;gap:12px;align-items:center;padding:12px 14px;margin-bottom:14px">${avatar(s.chat_avatar, s.chat_name)}<div class="row-tx"><b>${s.chat_name}</b><small>${s.admins.length} مشرف</small></div></div>`;

// ═══ ربط الحساب ═══
export async function linkAccount(onDone) {
  if (!S.boot.has_telegram) return toast('بوت تيليجرام غير مضبوط في الخادم', 'bad');
  const u = S.me.user;
  if (u.linked_tg_id) return manageLinked(onDone);
  const choice = await sheet({
    title: 'ربط حسابك في تيليجرام', sub: 'يفيدك في مضاعفة الحدود واستلام الإرسال التجريبي', size: 'wide',
    body: html`<div class="callout">${ic('bolt')}<div><b>الأسهل: ربط تلقائي بضغطة</b><br>نفتح البوت، تضغط Start، ويرجع حسابك مربوطاً هنا تلقائياً.</div></div>
      <div class="sp"></div><button class="btn pri lg block" data-auto ${S.boot.bot_link ? '' : raw('disabled')}>${ic('tg')} الربط التلقائي</button>
      <div class="hstack" style="margin:20px 0 12px;color:var(--tx-4);font-size:var(--fs-0)"><i style="flex:1;height:1px;background:var(--line)"></i>أو عبر رمز<i style="flex:1;height:1px;background:var(--line)"></i></div>
      <label class="field"><span>يوزرك في تيليجرام</span><input name="un" class="ltr" placeholder="username" autocapitalize="off" autocomplete="off"><small>افتح البوت واضغط Start مرة واحدة أولاً، ثم نرسل لك رمزاً.</small></label>
      <button class="btn block" data-code>${ic('key')} أرسل لي رمزاً</button>`,
    onMount: ({ root, close }) => root.addEventListener('click', e => {
      if (e.target.closest('[data-auto]')) close('auto');
      if (e.target.closest('[data-code]')) { const v = $('[name=un]', root).value.trim().replace(/^@/, ''); if (!/^[A-Za-z][A-Za-z0-9_]{3,31}$/.test(v)) return toast('اكتب يوزر صحيح', 'bad'); close('@' + v); }
    }),
  });
  if (!choice) return;
  if (choice === 'auto') {
    let r; try { r = await post('/api/link-tg/start', {}); } catch (e) { return tgErr(e, 'تعذّر بدء الربط'); }
    window.open(r.link, '_blank', 'noopener');
    let stop = false, linked = false;
    await sheet({ title: 'أكمل في تيليجرام', size: 'sm',
      body: html`<div class="wait"><div class="ring"></div><div class="mu2" style="font-size:var(--fs-2);line-height:1.9">اضغط <b>Start</b> في البوت ثم ارجع هنا — سنكمل تلقائياً.</div></div><a class="btn soft block" href="${r.link}" target="_blank" rel="noopener">${ic('tg')} فتح البوت</a><button type="button" class="btn ghost block" data-copy style="margin-top:8px">${ic('copy')} نسخ الرابط</button>`,
      onMount: async ({ root, close }) => {
        root.querySelector('[data-copy]').onclick = () => copy(r.link);
        const t0 = Date.now();
        while (!stop && Date.now() - t0 < 600000) { await sleep(2000); if (stop) break; try { const s = await api('/api/link-tg/' + r.link_id + '/status'); if (s.status === 'used') { linked = true; close(true); break; } if (s.status === 'expired' || s.status === 'none') { close(false); break; } } catch (e) {} }
      }, onClose: () => { stop = true; } });
    stop = true;
    if (linked) { await refreshMe(); ok(S.me.user.is_member ? 'رُبط حسابك — وأنت عضو، حدودك مضاعفة' : 'رُبط حسابك في تيليجرام'); onDone && onDone(); }
    return;
  }
  let r; try { r = await post('/api/link-tg/start', { tg_username: choice }); } catch (e) { return tgErr(e, 'تعذّر إرسال الرمز'); }
  const okk = await sheet({ title: 'أدخل الرمز', sub: 'أرسلناه لـ ' + choice + ' في تيليجرام', size: 'sm',
    body: html`<input class="code-in" name="code" inputmode="numeric" maxlength="6" placeholder="••••••" autocomplete="one-time-code" autofocus>`,
    actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: 'تأكيد الربط', kind: 'pri', handler: async ({ root }) => { const c = $('[name=code]', root).value.replace(/\D/g, ''); if (c.length !== 6) { toast('الرمز 6 أرقام', 'bad'); return false; } return await post('/api/link-tg/' + r.link_id + '/verify', { code: c }); } }],
    onMount: ({ root }) => { const i = $('[name=code]', root); i.addEventListener('input', () => { i.value = i.value.replace(/\D/g, '').slice(0, 6); }); } });
  if (okk) { await refreshMe(); ok(okk.message || 'رُبط الحساب'); onDone && onDone(); }
}

async function manageLinked(onDone) {
  const u = S.me.user;
  await sheet({
    title: 'حسابك في تيليجرام', size: 'sm',
    body: html`<div class="card" style="display:flex;gap:12px;align-items:center;padding:14px">${ic('tg')}<div class="row-tx"><b class="ltr" style="text-align:start">${u.linked_tg_username || u.linked_tg_name || u.linked_tg_id}</b><small>${u.is_member ? 'عضو في القناة الرسمية' : 'لست عضواً في القناة الرسمية بعد'}</small></div><span class="tag ${u.is_member ? 'ok' : 'warn'}">${u.is_member ? 'عضو' : 'غير عضو'}</span></div>
      ${!u.is_member && S.boot.required_channel_url ? html`<div class="callout warn" style="margin-top:12px">${ic('gift')}<div>${S.boot.required_channel_msg || 'انضم للقناة الرسمية ثم أعد الفحص لمضاعفة حدودك.'}<a class="btn sm soft" style="margin-top:8px" href="${S.boot.required_channel_url}" target="_blank" rel="noopener">${ic('ext')} الانضمام للقناة</a></div></div>` : ''}
      <div class="menu" style="margin-top:12px"><button data-chk>${ic('refresh')}<span class="grow">إعادة فحص العضوية</span></button><button data-un class="danger">${ic('x')}<span class="grow">إلغاء الربط</span></button></div>`,
    onMount: ({ root, close }) => root.addEventListener('click', async e => {
      if (e.target.closest('[data-chk]')) { try { const r = await post('/api/link-tg/refresh-membership'); toast(r.is_member ? 'أنت عضو — حدودك مضاعفة' : 'لم نجد عضويتك بعد — انضم ثم أعد الفحص', r.is_member ? 'ok' : 'bad'); await refreshMe(); close(); onDone && onDone(); } catch (x) { bad(x); } }
      if (e.target.closest('[data-un]')) { if (!await confirm('ستفقد الحدود المضاعفة إن كانت لديك.', { title: 'إلغاء ربط تيليجرام؟', ok: 'إلغاء الربط', danger: true })) return; try { await post('/api/link-tg/unlink'); ok('أُلغي الربط'); await refreshMe(); close(); onDone && onDone(); } catch (x) { bad(x); } }
    }),
  });
}
