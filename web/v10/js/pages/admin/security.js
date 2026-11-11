// السجل الأمني
import { api } from '../../core/api.js?v=__BUILD__';
import { html, render, $, ic, ago, num, time, debounce } from '../../core/dom.js?v=__BUILD__';
import { errorBox, skelList, empty } from '../../core/ui.js?v=__BUILD__';
import { head } from './_lib.js?v=__BUILD__';

const F = [['', 'الكل'], ['login_fail', 'فشل الدخول'], ['login_ok', 'دخول'], ['register', 'تسجيل'], ['admin_', 'إجراءات الإدارة'], ['settings', 'الإعدادات'], ['tg_verify', 'التوثيق']];
export default {
  async render(ctx) {
    ctx.setTitle('الأمان');
    let act = '', user = '', d = null, err = null;
    const paint = () => {
      if (!ctx.alive()) return;
      render(ctx.root, html`${head('security')}
        <div class="callout" style="margin-bottom:14px">${ic('shieldOk')}<div><b>الحماية النشطة:</b> تشفير PBKDF2 لكلمات المرور، حد لمحاولات الدخول لكل IP وحساب، كوكيز آمنة، تحقق من webhook تيليجرام، وحماية رفع الصور.${d ? html`<br>محاولات دخول فاشلة خلال 24 ساعة: <b>${num(d.fails_24h)}</b>` : ''}</div></div>
        <div class="toolbar"><label class="search">${ic('search')}<input placeholder="اسم مستخدم محدد" value="${user}" data-u class="ltr"></label></div>
        <div class="chips" style="margin-bottom:14px">${F.map(([k, t]) => html`<button class="chip ${act === k ? 'on' : ''}" data-a="${k}">${t}</button>`)}</div>
        ${err ? errorBox(err, true) : !d ? skelList(6) : !d.rows.length ? empty('shield', 'لا أحداث', '') : html`<div class="group">${d.rows.map(r => html`<div class="row" style="min-height:54px"><span class="dot ${/fail|banned|throttled/.test(r.action) ? 'bad' : /ok/.test(r.action) ? 'ok' : 'warn'}"></span>
          <span class="row-tx"><b class="ltr" style="text-align:start">${r.action}  <span class="mu">@${r.username || '-'}</span></b><small class="clip">${r.ip || ''} ${r.detail ? ' — ' + r.detail : ''}</small></span><span class="row-end" title="${time(r.ts)}">${ago(r.ts)}</span></div>`)}</div>`}`);
      const u = $('[data-u]', ctx.root); u.addEventListener('input', debounce(() => { user = u.value.trim(); reload(); }, 400));
    };
    const reload = async () => { try { d = await api('/api/admin/security?action=' + encodeURIComponent(act) + '&user=' + encodeURIComponent(user)); err = null; } catch (e) { err = e; } paint(); };
    ctx.root.addEventListener('click', e => { const c = e.target.closest('[data-a]'); if (c) { act = c.dataset.a; reload(); } if (e.target.closest('[data-retry]')) reload(); });
    ctx.onRefresh(reload); paint(); await reload();
  },
};
