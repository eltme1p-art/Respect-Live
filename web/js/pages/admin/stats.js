// الإحصائيات
import { api } from '../../core/api.js?v=__BUILD__';
import { html, render, ic, num } from '../../core/dom.js?v=__BUILD__';
import { errorBox } from '../../core/ui.js?v=__BUILD__';
import { head } from './_lib.js?v=__BUILD__';

export default {
  async render(ctx) {
    ctx.setTitle('الإحصائيات');
    let s; try { s = await api('/api/admin/stats'); } catch (e) { return render(ctx.root, errorBox(e)); }
    const max = Math.max(1, ...s.sent_series.map(x => x.ok + x.bad));
    const days = s.sent_series.map((x, i) => { const d = new Date(Date.now() - (6 - i) * 864e5); return { ...x, l: i === 6 ? 'اليوم' : d.toLocaleDateString('ar-EG-u-nu-latn', { weekday: 'short' }) }; });
    const S = (b, t) => html`<div class="stat"><b>${num(b)}</b><small>${t}</small></div>`;
    render(ctx.root, html`${head('stats')}
      <section class="card pad-l"><div class="sec-h"><h2 style="font-size:var(--fs-3)">الإرسال لتيليجرام — آخر 7 أيام</h2><span class="tag ok">${num(s.sent_24h)} اليوم</span>${s.failed_24h ? html`<span class="tag bad">${num(s.failed_24h)} فشل</span>` : ''}</div>
        <div class="bars" role="img" aria-label="رسم الإرسال اليومي">${days.map(d => html`<div title="${d.l}: ${d.ok} وصلت، ${d.bad} فشلت">${d.bad ? html`<i class="bad" style="height:${d.bad / max * 100}%"></i>` : ''}<i style="height:${Math.max(2, d.ok / max * 100)}%"></i><span>${d.l}</span></div>`)}</div></section>
      <div class="group-title">${ic('users')} المستخدمون</div><div class="statrow">${S(s.users_total, 'إجمالي')}${S(s.users_active, 'نشط')}${S(s.users_new_7d, 'جديد هذا الأسبوع')}${S(s.users_linked_tg, 'ربط تيليجرام')}${S(s.users_members, 'عضو بالقناة')}${S(s.users_banned, 'محظور')}</div>
      <div class="group-title">${ic('signal')} القنوات</div><div class="statrow">${S(s.kick_total, 'كيك')}${S(s.yt_total, 'يوتيوب')}${S(s.tw_total, 'X')}${S(s.tt_total, 'تيك توك')}${S(s.tg_total, 'تيليجرام (' + s.tg_verified + ' موثقة)')}${S(s.feeds_total, 'روم ديسكورد')}</div>
      <div class="group-title">${ic('bell')} أخرى</div><div class="statrow">${S(s.push_subs, 'جهاز مفعّل للإشعارات')}${S(s.feed_subs_total, 'اشتراك ديسكورد')}${S(s.defaults_total, 'قناة مقترحة')}${S(s.tg_known, 'قناة يعرفها البوت')}${S(s.news_total, 'خبر منشور')}${S(s.suggestions_unread, 'اقتراح غير مقروء')}</div>`);
  },
};
