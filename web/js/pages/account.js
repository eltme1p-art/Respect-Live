// حسابي: الملف، الحدود، الإشعارات، المظهر، الأمان، بياناتي
import { S, api, post, patch, upload, pickFile, load, isLogged, isOwner, ttOn, emit, KIND, handleOf } from '../core/api.js?v=__BUILD__';
import { html, raw, render, $, ic, avatar, num, date, ago, ls } from '../core/dom.js?v=__BUILD__';
import { sheet, prompt, confirm, ok, bad, toast, empty } from '../core/ui.js?v=__BUILD__';
import { scheme, setScheme, setLite, deviceWeak } from '../core/theme.js?v=__BUILD__';
import { pushSupported, pushStatus, enablePush, disablePush, testPush } from '../core/push.js?v=__BUILD__';
import { linkAccount } from '../components/tg-flows.js?v=__BUILD__';

const ACT = { login_ok: ['دخول', 'ok'], login_fail: ['محاولة دخول فاشلة', 'bad'], login_throttled: ['حُظرت محاولات كثيرة', 'bad'], register_ok: ['إنشاء الحساب', 'ok'], tg_verify_ok: ['توثيق قناة تيليجرام', 'ok'],
  password_change: ['تغيير كلمة المرور', 'warn'], sessions_revoked: ['إنهاء الجلسات الأخرى', 'warn'], link_tg_ok: ['ربط تيليجرام', 'ok'] };
let installEvt = null;
addEventListener('beforeinstallprompt', e => { e.preventDefault(); installEvt = e; });

export default {
  async render(ctx) {
    if (!isLogged()) {
      render(ctx.root, html`<div style="padding-top:20px">${empty('user', 'سجّل دخولك', 'حدودك وربط تيليجرام والإشعارات وأمان حسابك — كلها هنا.', html`<div class="hstack" style="justify-content:center"><a class="btn pri" href="/login">تسجيل الدخول</a><a class="btn ghost" href="/register">حساب جديد</a></div>`)}</div>`);
      return;
    }
    let acct = null;
    await pushStatus();
    const paint = () => {
      if (!ctx.alive()) return;
      const u = S.me.user, L = S.me.limits || {}, U = S.me.usage || {};
      const standalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone;
      const lim = (k) => { const l = L[k], used = U[k] || 0; if (l == null) return ''; const p = l >= 9999 ? 0 : Math.min(100, used / l * 100);
        return html`<div class="row"><span class="pi sm ${k}">${ic(k)}</span><span class="row-tx"><b>${KIND[k].name}</b>${l < 9999 ? html`<div class="meter ${p >= 100 ? 'full' : p >= 80 ? 'warn' : ''}"><i style="width:${p}%"></i></div>` : ''}</span><span class="row-end num">${l >= 9999 ? num(used) : num(used) + ' / ' + num(l)}</span></div>`; };
      const sc = scheme(), lite = document.documentElement.classList.contains('lite');
      render(ctx.root, html`
        <div class="card profile">
          <button class="av xl" data-avatar aria-label="تغيير الصورة" style="${u.avatar ? '' : ''}">${u.avatar ? html`<img src="${u.avatar}" alt="">` : (u.display || u.username).charAt(0).toUpperCase()}</button>
          <div class="grow"><h2 class="clip">${u.display || u.username}</h2><div class="mu ltr" style="text-align:start;font-size:var(--fs-1)">@${u.username}</div>
            <div class="tags">${u.role === 'owner' ? html`<span class="tag violet">${ic('crown')} الإدارة</span>` : ''}${u.is_member ? html`<span class="tag ok">${ic('gift')} حدود مضاعفة</span>` : ''}${u.linked_tg_id ? html`<span class="tag ac">${ic('tg')} مربوط</span>` : ''}${u.can_discord ? html`<span class="tag">${ic('dc')} ديسكورد</span>` : ''}</div></div>
          <button class="btn icon ghost" data-name aria-label="تعديل الاسم">${ic('edit')}</button></div>

        <div class="group-title">${ic('chart')} الحدود</div>
        <div class="group">${lim('kick')}${lim('yt')}${lim('tw')}${ttOn() ? lim('tt') : ''}${lim('tg')}</div>
        ${!u.is_member && u.role !== 'owner' ? html`<div class="group-note">اربط حسابك في تيليجرام وانضم للقناة الرسمية لتتضاعف حدودك.</div>` : ''}

        <div class="group-title">${ic('tg')} تيليجرام</div>
        <div class="group"><button class="row" data-tg><span class="pi tg">${ic('tg')}</span><span class="row-tx"><b>${u.linked_tg_id ? 'الحساب المربوط' : 'ربط حسابك في تيليجرام'}</b><small class="${u.linked_tg_id ? 'ltr' : ''}" style="text-align:start">${u.linked_tg_id ? (u.linked_tg_username || u.linked_tg_name) : 'لمضاعفة الحدود واستلام الإرسال التجريبي'}</small></span><span class="row-end">${u.linked_tg_id ? html`<span class="tag ${u.is_member ? 'ok' : 'warn'}">${u.is_member ? 'عضو' : 'غير عضو'}</span>` : ''}${ic('chev', 'chev')}</span></button>
          <a class="row" href="/telegram"><span class="pi">${ic('shieldOk')}</span><span class="row-tx"><b>القنوات الموثّقة</b><small>${num(U.tg || 0)} قناة</small></span><span class="row-end">${ic('chev', 'chev')}</span></a>
          <a class="row" href="/activity"><span class="pi">${ic('activity')}</span><span class="row-tx"><b>سجل الإرسال</b><small>ما وصل لقنواتك وما لم يصل</small></span><span class="row-end">${ic('chev', 'chev')}</span></a></div>

        <div class="group-title" id="push">${ic('bell')} الإشعارات</div>
        <div class="group">
          <label class="row"><span class="pi violet">${ic('device')}</span><span class="row-tx"><b>إشعارات هذا الجهاز</b><small>${!S.boot.has_push ? 'غير مفعّلة من الخادم' : !pushSupported() ? 'المتصفح لا يدعمها — على آيفون ثبّت الموقع أولاً' : S.pushOn ? 'تصلك فوراً حتى والموقع مغلق' : 'متوقفة'}</small></span>
            <span class="switch"><input type="checkbox" data-push ${S.pushOn ? raw('checked') : ''} ${!S.boot.has_push || !pushSupported() ? raw('disabled') : ''}><i></i></span></label>
          ${S.pushOn ? html`<button class="row" data-ptest><span class="pi ok">${ic('send')}</span><span class="row-tx"><b>إرسال إشعار تجريبي</b></span></button>` : ''}
          <a class="row" href="/notifications"><span class="pi">${ic('inbox')}</span><span class="row-tx"><b>كل التنبيهات</b></span><span class="row-end">${S.unread ? html`<span class="badge">${S.unread}</span>` : ''}${ic('chev', 'chev')}</span></a></div>

        <div class="group-title">${ic('palette')} المظهر والأداء</div>
        <div class="group">
          <div class="row"><span class="pi">${ic(sc === 'light' ? 'sun' : 'moon')}</span><span class="row-tx"><b>المظهر</b></span>
            <div class="seg" style="flex:0 0 auto" data-scheme>${[['dark', 'داكن'], ['light', 'فاتح'], ['auto', 'تلقائي']].map(([k, t]) => html`<button type="button" data-v="${k}" class="${sc === k ? 'on' : ''}" style="height:34px;padding:0 12px">${t}</button>`)}</div></div>
          <label class="row"><span class="pi ok">${ic('bolt')}</span><span class="row-tx"><b>الوضع الخفيف</b><small>${lite ? 'مفعّل — بدون ضبابية وبحركة أقل' : deviceWeak() ? 'مقترح لجهازك: أسرع وأخف على البطارية' : 'فعّله إذا شعرت بتأخر أو سخونة'}</small></span><span class="switch"><input type="checkbox" data-lite ${lite ? raw('checked') : ''}><i></i></span></label>
          <label class="row"><span class="pi">${ic('sparkle')}</span><span class="row-tx"><b>تقليل الحركة</b><small>إيقاف حركة الانتقال بين الصفحات</small></span><span class="switch"><input type="checkbox" data-motion ${document.documentElement.classList.contains('no-motion') ? raw('checked') : ''}><i></i></span></label>
          ${!standalone ? html`<button class="row" data-install><span class="pi">${ic('download')}</span><span class="row-tx"><b>تثبيت التطبيق</b><small>يفتح بملء الشاشة وأسرع، وتعمل الإشعارات على آيفون</small></span><span class="row-end">${ic('chev', 'chev')}</span></button>` : ''}</div>

        <div class="group-title">${ic('lock')} الأمان</div>
        <div class="group">
          <button class="row" data-pass><span class="pi warn">${ic('key')}</span><span class="row-tx"><b>تغيير كلمة المرور</b><small>تُنهى جلساتك الأخرى تلقائياً</small></span><span class="row-end">${ic('chev', 'chev')}</span></button>
          <div class="row"><span class="pi ok">${ic('device')}</span><span class="row-tx"><b>الأجهزة المسجّلة</b><small>${acct ? num(acct.sessions) + ' جلسة نشطة' : '…'}</small></span>${acct && acct.sessions > 1 ? html`<button class="btn sm danger" data-revoke>تسجيل خروج الأخرى</button>` : ''}</div>
          <div class="row"><span class="pi">${ic('calendar')}</span><span class="row-tx"><b>عضو منذ</b></span><span class="row-end">${acct ? date(acct.created) : ''}</span></div></div>
        ${acct && acct.activity && acct.activity.length ? html`<div class="group-title">${ic('clock')} آخر النشاط على حسابك</div><div class="group">${acct.activity.slice(0, 8).map(a => { const L2 = ACT[a.action] || [a.action, '']; return html`<div class="row" style="min-height:52px"><span class="dot ${L2[1]}"></span><span class="row-tx"><b>${L2[0]}</b><small>${[a.device, a.ip].filter(Boolean).join('  ')}</small></span><span class="row-end">${ago(a.ts)}</span></div>`; })}</div>` : ''}

        <div class="group-title">${ic('db')} بياناتي والمساعدة</div>
        <div class="group">
          <button class="row" data-export><span class="pi">${ic('download')}</span><span class="row-tx"><b>تصدير قائمة قنواتي</b><small>ملف JSON بكل قنواتك ورسائلها المخصصة</small></span></button>
          <button class="row" data-suggest><span class="pi">${ic('msg')}</span><span class="row-tx"><b>إرسال اقتراح للإدارة</b></span><span class="row-end">${ic('chev', 'chev')}</span></button>
          ${isOwner() ? html`<a class="row" href="/admin"><span class="pi violet">${ic('shield')}</span><span class="row-tx"><b>لوحة الإدارة</b></span><span class="row-end">${ic('chev', 'chev')}</span></a>` : ''}
          <button class="row" data-keys><span class="pi">${ic('keyboard')}</span><span class="row-tx"><b>اختصارات لوحة المفاتيح</b></span></button></div>

        <div class="group" style="margin-top:22px"><button class="row danger" data-logout><span class="pi bad">${ic('logout')}</span><span class="row-tx"><b>تسجيل الخروج</b></span></button></div>
        <p class="mu" style="text-align:center;font-size:var(--fs-0);margin-top:18px">${S.boot.site_name || 'Respect Live'} — إصدار ${S.boot.build || ''}</p>`);
    };
    paint();
    api('/api/me/account').then(a => { acct = a; paint(); }).catch(() => {});
    if (location.hash === '#push') setTimeout(() => document.getElementById('push')?.scrollIntoView({ block: 'center' }), 200);

    ctx.root.addEventListener('change', async e => {
      const t = e.target;
      if (t.matches('[data-push]')) { t.disabled = true; t.checked ? await enablePush() : await disablePush(); paint(); }
      if (t.matches('[data-lite]')) { setLite(t.checked); post('/api/me/ui-mode', { mode: t.checked ? 'lite' : 'full' }).catch(() => {}); S.me.user.ui_mode = t.checked ? 'lite' : 'full'; ok(t.checked ? 'فعّلنا الوضع الخفيف' : 'رجعنا للعرض الكامل'); paint(); }
      if (t.matches('[data-motion]')) { ls.set('rl_motion', t.checked ? 'off' : 'on'); document.documentElement.classList.toggle('no-motion', t.checked); }
    });
    ctx.root.addEventListener('click', async e => {
      const t = e.target;
      const sch = t.closest('[data-scheme] [data-v]'); if (sch) { setScheme(sch.dataset.v); return paint(); }
      if (t.closest('[data-avatar]')) { const f = await pickFile(); if (!f) return; try { const r = await upload(f); await patch('/api/me/profile', { avatar: r.url }); S.me.user.avatar = r.url; ok('حُدّثت صورتك'); emit('me:changed'); paint(); } catch (x) { bad(x); } return; }
      if (t.closest('[data-name]')) { const v = await prompt({ title: 'الاسم الظاهر', label: 'كيف يظهر اسمك في الموقع', value: S.me.user.display, max: 60 }); if (!v) return; try { await patch('/api/me/profile', { display: v }); S.me.user.display = v; ok('حُفظ الاسم'); emit('me:changed'); paint(); } catch (x) { bad(x); } return; }
      if (t.closest('[data-tg]')) return linkAccount(paint);
      if (t.closest('[data-ptest]')) return testPush();
      if (t.closest('[data-install]')) return install();
      if (t.closest('[data-pass]')) return changePass(() => api('/api/me/account').then(a => { acct = a; paint(); }));
      if (t.closest('[data-revoke]')) { if (!await confirm('سيُطلب من كل أجهزتك الأخرى تسجيل الدخول من جديد. هذا الجهاز يبقى مسجّلاً.', { title: 'تسجيل خروج الأجهزة الأخرى؟', ok: 'تسجيل الخروج', danger: true })) return; try { const r = await post('/api/me/sessions/revoke-others'); ok('أنهينا ' + num(r.revoked) + ' جلسة'); acct = await api('/api/me/account'); paint(); } catch (x) { bad(x); } return; }
      if (t.closest('[data-export]')) return exportData(t.closest('[data-export]'));
      if (t.closest('[data-suggest]')) { const v = await prompt({ title: 'اقتراحك', label: 'ما الذي يجعل الموقع أفضل لك؟', multiline: true, max: 1000, ok: 'إرسال' }); if (!v) return; try { await post('/api/suggestions', { text: v }); ok('وصل اقتراحك — شكراً لك'); } catch (x) { bad(x); } return; }
      if (t.closest('[data-keys]')) return sheet({ title: 'اختصارات لوحة المفاتيح', size: 'sm', body: html`<dl class="kv"><dt class="ltr">Ctrl / ⌘ + K</dt><dd>البحث والأوامر</dd><dt class="ltr">/</dt><dd>البحث داخل الصفحة</dd><dt class="ltr">Esc</dt><dd>إغلاق النافذة</dd><dt class="ltr">Ctrl + Enter</dt><dd>تأكيد النافذة</dd></dl>` });
      if (t.closest('[data-logout]')) { if (!await confirm('ستحتاج كلمة المرور للدخول مجدداً.', { title: 'تسجيل الخروج؟', ok: 'تسجيل الخروج', danger: true })) return; try { await post('/api/logout'); } catch (x) {} location.replace('/login'); }
    });
  },
};

async function install() {
  if (installEvt) { installEvt.prompt(); try { await installEvt.userChoice; } catch (e) {} installEvt = null; return; }
  const ios = /iphone|ipad/i.test(navigator.userAgent);
  sheet({ title: 'تثبيت التطبيق', size: 'sm', body: html`<div class="steps">${(ios ? ['اضغط زر المشاركة في Safari', 'اختر «إضافة إلى الشاشة الرئيسية»', 'افتح التطبيق من الأيقونة'] : ['افتح قائمة المتصفح ⋮', 'اختر «تثبيت التطبيق» أو «إضافة إلى الشاشة الرئيسية»', 'افتح التطبيق من الأيقونة']).map((s, i) => html`<div class="step"><span class="n">${i + 1}</span><span class="row-tx"><b>${s}</b></span></div>`)}</div>`, actions: [{ label: 'حسناً', kind: 'pri' }] });
}

function changePass(after) {
  return sheet({ title: 'تغيير كلمة المرور', size: 'sm',
    body: html`<label class="field"><span>كلمة المرور الحالية</span><input type="password" name="o" autocomplete="current-password" class="ltr"></label><label class="field"><span>الجديدة</span><input type="password" name="n" autocomplete="new-password" class="ltr"><small>6 أحرف على الأقل</small></label><label class="field"><span>تأكيد الجديدة</span><input type="password" name="n2" autocomplete="new-password" class="ltr"></label>`,
    actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: 'تغيير', kind: 'pri', handler: async ({ root }) => {
      const o = $('[name=o]', root).value, n = $('[name=n]', root).value, n2 = $('[name=n2]', root).value;
      if (!o || !n) { toast('أكمل الحقول', 'bad'); return false; } if (n.length < 6) { toast('كلمة المرور الجديدة قصيرة', 'bad'); return false; } if (n !== n2) { toast('التأكيد لا يطابق', 'bad'); return false; }
      await post('/api/me/password', { old: o, new: n }); ok('غيّرنا كلمة المرور'); after && after();
    } }] });
}

async function exportData(btn) {
  btn.setAttribute('aria-busy', 'true');
  try {
    const kinds = ['kick', 'yt', 'tw', 'tt', 'tg'], out = { exported_at: new Date().toISOString(), user: S.me.user.username, channels: {} };
    for (const k of kinds) { const r = await api('/api/channels/' + k + (isOwner() ? '?mine=1' : '')); out.channels[k] = (r.rows || []).map(c => ({ id: handleOf(k, c), name: c.name, enabled: !!c.enabled, alerts: c.auto_send !== 0, message: c.msg || '', button: c.btn_text || '', filters: c.filters || undefined })); }
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' }));
    a.download = 'respect-live-channels-' + new Date().toISOString().slice(0, 10) + '.json'; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    ok('نزّلنا الملف');
  } catch (e) { bad(e); } finally { btn.removeAttribute('aria-busy'); }
}
