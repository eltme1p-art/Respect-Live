// الدخول وإنشاء الحساب
import { S } from '../core/api.js?v=__BUILD__';
import { html, render, $, ic } from '../core/dom.js?v=__BUILD__';
import { toast } from '../core/ui.js?v=__BUILD__';

export default {
  render(ctx) {
    const reg = ctx.params.mode === 'register';
    const b = S.boot;
    const canReg = b.registration_enabled !== false;
    const next = ctx.query.get('next') || '/';
    render(ctx.root, html`<div class="auth"><div class="auth-card card">
      <div class="brand"><span class="brand-logo">${b.site_logo ? html`<img src="${b.site_logo}" alt="">` : ic('logo')}</span>
        <div><h1>${reg ? 'أنشئ حسابك' : 'أهلاً بعودتك'}</h1></div></div>
      <p class="lead" style="text-align:center;margin-bottom:20px">${reg ? 'دقيقة واحدة، وتبدأ تصلك تنبيهات قنواتك.' : 'سجّل دخولك لإدارة قنواتك وتنبيهاتك.'}</p>
      ${canReg ? html`<div class="seg" style="margin-bottom:20px"><a href="/login${next !== '/' ? '?next=' + encodeURIComponent(next) : ''}" class="${reg ? '' : 'on'}">دخول</a><a href="/register" class="${reg ? 'on' : ''}">حساب جديد</a></div>` : ''}
      <form novalidate>
        <label class="field"><span>اسم المستخدم</span><input name="u" class="ltr" autocomplete="username" autocapitalize="off" spellcheck="false" required autofocus>${reg ? html`<small>3 إلى 30 حرفاً إنجليزياً أو أرقاماً</small>` : ''}</label>
        ${reg ? html`<label class="field"><span>الاسم الظاهر (اختياري)</span><input name="d" maxlength="60" placeholder="كيف يظهر اسمك في الموقع"></label>` : ''}
        <label class="field"><span>كلمة المرور</span><div class="pw-wrap"><input name="p" type="password" class="ltr" autocomplete="${reg ? 'new-password' : 'current-password'}" required minlength="${reg ? 6 : 1}"><button type="button" data-eye aria-label="إظهار كلمة المرور">${ic('eye')}</button></div>${reg ? html`<small>6 أحرف على الأقل</small>` : ''}</label>
        <button class="btn pri lg block" type="submit">${reg ? 'إنشاء الحساب' : 'دخول'}</button>
        <div class="err" role="alert"></div>
      </form>
      ${reg ? html`<div class="callout" style="margin-top:8px">${ic('gift')}<div>يبدأ حسابك بحدود أساسية. اربط تيليجرام وانضم للقناة الرسمية لتتضاعف.</div></div>` : ''}
      ${b.guest_mode ? html`<a class="btn ghost block" href="/" style="margin-top:14px">${ic('eye')} تصفّح بدون حساب</a>` : ''}
    </div></div>`);
    const f = $('form', ctx.root), err = $('.err', ctx.root), btn = $('[type=submit]', ctx.root);
    $('[data-eye]', ctx.root).onclick = e => { const i = f.p; i.type = i.type === 'password' ? 'text' : 'password'; e.currentTarget.innerHTML = ic(i.type === 'password' ? 'eye' : 'eyeOff').s; };
    f.onsubmit = async e => {
      e.preventDefault(); err.textContent = '';
      const u = f.u.value.trim(), p = f.p.value;
      if (!u || !p) { err.textContent = 'اكتب اسم المستخدم وكلمة المرور'; return; }
      if (reg && !/^[A-Za-z0-9_.-]{3,30}$/.test(u)) { err.textContent = 'اسم المستخدم: 3 إلى 30 حرفاً إنجليزياً أو أرقاماً أو _ . -'; return; }
      if (reg && p.length < 6) { err.textContent = 'كلمة المرور 6 أحرف على الأقل'; return; }
      btn.setAttribute('aria-busy', 'true');
      const fd = new FormData();
      if (reg) { fd.append('username', u); fd.append('password', p); fd.append('display', (f.d && f.d.value.trim()) || ''); } else { fd.append('u', u); fd.append('p', p); }
      try {
        const r = await fetch(reg ? '/api/register' : '/api/login', { method: 'POST', body: fd, credentials: 'same-origin' });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.error || (reg ? 'تعذّر إنشاء الحساب' : 'تعذّر الدخول'));
        try { sessionStorage.setItem('rl_intro', '1'); if (reg && j.message) sessionStorage.setItem('rl_welcome', j.message); } catch (x) {}
        location.replace(next.startsWith('/') && !next.startsWith('//') ? next : '/');
      } catch (x) { err.textContent = x.message; btn.removeAttribute('aria-busy'); f.p.select(); }
    };
  },
};
