// النظام: الصيانة، صحة المهام، النسخ الاحتياطي، أدوات تيليجرام وديسكورد
import { S, api, post } from '../../core/api.js?v=__BUILD__';
import { html, render, $, ic, num, ago, bytes, dur } from '../../core/dom.js?v=__BUILD__';
import { sheet, confirm, ok, bad, toast, errorBox, busy } from '../../core/ui.js?v=__BUILD__';
import { head, card, fields, collect, saveSettings } from './_lib.js?v=__BUILD__';

const JOB = { kick: 'فحص كيك', tiktok: 'فحص تيك توك', youtube: 'فحص يوتيوب', x: 'جلب X', membership: 'فحص العضوية', images: 'تخزين الصور', cleanup: 'تنظيف القاعدة' };

export default {
  async render(ctx) {
    ctx.setTitle('النظام');
    let sys = null, st = null, set = null, err = null;
    const paint = () => {
      if (!ctx.alive()) return;
      if (err) return render(ctx.root, html`${head('system')}${errorBox(err, true)}`);
      if (!sys) return render(ctx.root, html`${head('system')}<div class="skel" style="height:300px;border-radius:var(--r-card)"></div>`);
      const mnt = set.maintenance === '1';
      render(ctx.root, html`${head('system')}
        <section class="card pad-l" style="margin-bottom:14px;${mnt ? 'border-color:rgba(255,84,104,.45)' : ''}">
          <div class="sec-h"><span class="pi sm ${mnt ? 'bad' : ''}">${ic('wrench')}</span><h2 style="font-size:var(--fs-3)">وضع الصيانة</h2><span class="tag ${mnt ? 'bad' : 'ok'}">${mnt ? 'مفعّل' : 'متوقف'}</span></div>
          <p class="mu" style="font-size:var(--fs-1);margin-bottom:14px;line-height:1.8">يبقى الموقع متاحاً للتصفح، ويظهر شريط للمستخدمين، وتتوقف الإضافة والإرسال لغير الإدارة.</p>
          ${fields([{ k: 'maintenance_title', t: 'العنوان' }, { k: 'maintenance_text', t: 'النص', type: 'textarea', rows: 2 }], set)}
          <button class="btn ${mnt ? '' : 'danger'} block" data-mnt>${ic(mnt ? 'check' : 'wrench')} ${mnt ? 'إيقاف الصيانة' : 'تفعيل الصيانة'}</button></section>

        ${card('صحة النظام', 'activity', html`
          <dl class="kv" style="margin-bottom:14px"><dt>يعمل منذ</dt><dd>${dur(sys.uptime)}</dd><dt>حجم قاعدة البيانات</dt><dd class="num">${bytes(sys.db_size)}</dd><dt>الصور المخزنة</dt><dd class="num">${num(sys.images)} (${bytes(sys.images_size)})</dd>
            <dt>تنبيهات أُرسلت منذ التشغيل</dt><dd class="num">${num(sys.stats.tg_sent)}${sys.stats.tg_failed ? ' — فشل ' + num(sys.stats.tg_failed) : ''}</dd><dt>Python</dt><dd class="ltr">${sys.python}</dd></dl>
          ${sys.volume_hint ? html`<div class="callout bad" style="margin-bottom:14px">${ic('warn')}<div><b>قاعدة البيانات خارج الـ Volume</b><br>المسار الحالي <span class="ltr">${sys.db_path}</span>. بدون Volume على <span class="ltr">/app/data</span> ستُمسح البيانات عند كل نشر. اضبط <span class="ltr">DB_PATH=/app/data/respect.db</span>.</div></div>` : ''}
          <div class="group">${sys.jobs.map(j => html`<div class="row" style="min-height:54px"><span class="dot ${j.last_error ? 'bad' : j.last_ok ? 'ok' : 'warn'}"></span><span class="row-tx"><b>${JOB[j.name] || j.name}</b><small>${j.last_error ? j.last_error : j.last_ok ? 'آخر تشغيل ناجح ' + ago(j.last_ok) + '  (' + j.last_ms + 'ms)' : 'لم يعمل بعد'}</small></span><span class="row-end num">كل ${j.every >= 3600 ? Math.round(j.every / 3600) + ' س' : j.every + ' ث'}</span></div>`)}</div>`)}

        ${card('النسخ الاحتياطي', 'db', html`<p class="mu" style="font-size:var(--fs-1);line-height:1.8;margin-bottom:14px">نسخة كاملة من قاعدة البيانات (المستخدمون والقنوات والإعدادات). احتفظ بها قبل أي تغيير كبير — يمكن استرجاعها برفعها مكان الملف على الخادم.</p>
          <div class="hstack"><a class="btn pri" href="/api/admin/backup" download data-native>${ic('download')} تنزيل نسخة الآن</a><button class="btn" data-clean>${ic('trash')} حذف الصور غير المستخدمة</button></div>`)}

        ${card('تيليجرام', 'tg', html`<dl class="kv" style="margin-bottom:14px"><dt>البوت</dt><dd class="ltr">${sys.tg_bot.username ? '@' + sys.tg_bot.username : '—'}</dd><dt>الاستقبال</dt><dd>${st.webhook_set ? 'Webhook (محمي بسر)' : 'Polling — أضف PUBLIC_URL للتحويل إلى Webhook'}</dd><dt>الرابط العام</dt><dd class="ltr">${sys.public_url || '—'}</dd><dt>قنوات يعرفها البوت</dt><dd>${num(st.tg_known)}</dd></dl>
          <div class="hstack"><button class="btn" data-wh ${st.public_url ? '' : 'disabled'}>${ic('link')} إعادة ضبط Webhook</button><button class="btn ghost" data-whinfo>${ic('info')} حالة Webhook</button></div>`)}

        ${card('ديسكورد', 'dc', html`<dl class="kv" style="margin-bottom:14px"><dt>الحالة</dt><dd>${st.discord_ready ? 'متصل' : st.has_discord ? 'غير متصل' : 'لا يوجد توكن'}</dd><dt>الرومات المقروءة</dt><dd>${num(st.discord_channels)}</dd><dt>الاكتشاف</dt><dd>${st.auto_discovery ? 'تلقائي لكل الرومات' : 'رومات محددة في المتغيرات'}</dd></dl>
          <button class="btn" data-dc>${ic('refresh')} تحديث كاش الرومات</button>
          ${st.self_bot_mode ? html`<div class="callout warn" style="margin-top:14px">${ic('warn')}<div>يعمل بتوكن حساب شخصي (self-bot). هذا مخالف لشروط ديسكورد وقد يؤدي لإيقاف الحساب — يُفضّل استخدام حساب ثانوي.</div></div>` : ''}`)}`);
    };
    const reload = async () => { try { [sys, st, set] = await Promise.all([api('/api/admin/system'), api('/api/admin/stats'), api('/api/settings')]); err = null; } catch (e) { err = e; } paint(); };
    ctx.onRefresh(reload);
    ctx.root.addEventListener('click', async e => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.matches('[data-retry]')) return reload();
      if (b.matches('[data-mnt]')) { const on = set.maintenance !== '1'; if (on && !await confirm('ستتوقف الإضافة والإرسال لكل المستخدمين حتى تُوقفه.', { title: 'تفعيل الصيانة؟', ok: 'تفعيل', danger: true })) return;
        const v = collect(ctx.root); return busy(b, async () => { try { await post('/api/admin/maintenance', { enabled: on, title: v.maintenance_title, text: v.maintenance_text }); ok(on ? 'فُعّلت الصيانة' : 'أُوقفت الصيانة'); S.boot.maintenance = on; reload(); } catch (x) { bad(x); } }); }
      if (b.matches('[data-clean]')) { if (!await confirm('نحذف الصور التي لم تعد مستخدمة في أي مكان (أقدم من أسبوع).', { title: 'تنظيف الصور؟', ok: 'تنظيف' })) return; return busy(b, async () => { try { const r = await post('/api/admin/cleanup-images'); ok('حذفنا ' + num(r.deleted) + ' صورة'); reload(); } catch (x) { bad(x); } }); }
      if (b.matches('[data-wh]')) return busy(b, async () => { try { const r = await post('/api/telegram/setup-webhook'); r.ok ? ok('ضُبط Webhook') : toast('فشل: ' + (r.description || ''), 'bad'); } catch (x) { bad(x); } });
      if (b.matches('[data-whinfo]')) return busy(b, async () => { try { const r = await api('/api/telegram/webhook-info'); const x = r.result || {}; sheet({ title: 'حالة Webhook', size: 'sm', body: html`<dl class="kv"><dt>الرابط</dt><dd class="ltr" style="word-break:break-all">${x.url || '—'}</dd><dt>رسائل معلّقة</dt><dd>${num(x.pending_update_count || 0)}</dd><dt>آخر خطأ</dt><dd>${x.last_error_message || 'لا يوجد'}</dd></dl>` }); } catch (x) { bad(x); } });
      if (b.matches('[data-dc]')) return busy(b, async () => { try { const r = await post('/api/discord/refresh'); ok(num(r.channels) + ' روم'); reload(); } catch (x) { bad(x); } });
    });
    paint(); await reload();
  },
};
