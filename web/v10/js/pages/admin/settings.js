// إعدادات الموقع: التسجيل والحدود، القناة الرسمية، النصوص، القوالب، البوت
import { S, api } from '../../core/api.js?v=__BUILD__';
import { html, render, $, ic } from '../../core/dom.js?v=__BUILD__';
import { errorBox, busy } from '../../core/ui.js?v=__BUILD__';
import { head, card, fields, collect, saveSettings } from './_lib.js?v=__BUILD__';

const N = (k, t, ph) => ({ k, t, type: 'number', ph });
const SECS = [
  ['التسجيل والزوار', 'user', [{ k: 'registration_enabled', t: 'السماح بإنشاء حسابات جديدة', type: 'switch' }, { k: 'guest_mode', t: 'السماح بالتصفح بدون حساب', type: 'switch', hint: 'يرى الزائر الصفحة الرئيسية والبث المباشر فقط' }]],
  ['الحدود الافتراضية', 'chart', [N('default_lim_kick', 'كيك'), N('default_lim_yt', 'يوتيوب'), N('default_lim_tw', 'X'), N('default_lim_tt', 'تيك توك'), N('default_lim_tg', 'تيليجرام')], 'grid'],
  ['حدود الأعضاء (المنضمّين للقناة الرسمية)', 'gift', [N('bonus_lim_kick', 'كيك'), N('bonus_lim_yt', 'يوتيوب'), N('bonus_lim_tw', 'X'), N('bonus_lim_tt', 'تيك توك'), N('bonus_lim_tg', 'تيليجرام')], 'grid'],
  ['القناة الرسمية', 'megaphone', [{ k: 'required_channel_id', t: 'معرّف القناة', ph: '-100… أو @channel', ltr: true, hint: 'البوت يجب أن يكون مشرفاً فيها حتى يتحقق من العضوية' }, { k: 'required_channel_name', t: 'الاسم الظاهر' }, { k: 'required_channel_url', t: 'رابط الانضمام', ph: 'https://t.me/…', ltr: true }, { k: 'required_channel_msg', t: 'رسالة التشجيع', type: 'textarea', rows: 2 }]],
  ['واجهة الموقع', 'home', [{ k: 'site_name', t: 'اسم الموقع' }, { k: 'site_sub', t: 'الوصف القصير' }, { k: 'hero_title', t: 'عنوان الصفحة للزوار' }, { k: 'hero_accent', t: 'تكملة العنوان' }, { k: 'hero_text', t: 'نص الترحيب للزوار', type: 'textarea', rows: 2 },
    { k: 'announce_bar', t: 'شريط إعلان أعلى الموقع (اختياري)', hint: 'يظهر لكل الزوار ويمكنهم إخفاؤه. اتركه فارغاً لإيقافه' }, { k: 'signup_welcome_text', t: 'رسالة بعد التسجيل', type: 'textarea', rows: 2 }]],
  ['نصوص الأزرار', 'link', [{ k: 'btn_kick', t: 'كيك' }, { k: 'btn_yt', t: 'يوتيوب' }, { k: 'btn_tw', t: 'X' }, { k: 'btn_tt', t: 'تيك توك' }, { k: 'btn_discord', t: 'ديسكورد' }, { k: 'btn_tg', t: 'تيليجرام' }], 'grid'],
  ['قوالب التنبيهات', 'edit', [{ k: 'tpl_kick', t: 'كيك — {name} {title} {url}', type: 'code' }, { k: 'tpl_yt', t: 'يوتيوب — {name} {title} {url}', type: 'code' }, { k: 'tpl_tw', t: 'X — {name} {username} {text} {url}', type: 'code' },
    { k: 'tpl_tt', t: 'تيك توك — {name} {title} {url}', type: 'code' }, { k: 'tpl_discord', t: 'ديسكورد — {author_no_at} {content} {title} {channel}', type: 'code' }]],
  ['البوت ورسائله', 'tg', [{ k: 'bot_name_custom', t: 'اسم البوت في الرسائل' }, { k: 'bot_tg_link', t: 'رابط البوت في تيليجرام', ltr: true, ph: 'https://t.me/YourBot', hint: 'اتركه فارغاً ليُكتشف تلقائياً من التوكن' }, { k: 'bot_invite_url', t: 'رابط دعوة ديسكورد', ltr: true },
    { k: 'tpl_tg_verify', t: 'رسالة طلب التوثيق — {site_user} {chat_name}', type: 'code' }, { k: 'tpl_tg_success', t: 'رسالة نجاح التوثيق', type: 'code' }, { k: 'tpl_tg_link', t: 'رسالة رمز الربط — {code}', type: 'code' }]],
];

export default {
  async render(ctx) {
    ctx.setTitle('الإعدادات');
    let s; try { s = await api('/api/settings'); } catch (e) { return render(ctx.root, errorBox(e)); }
    render(ctx.root, html`${head('settings')}
      ${SECS.map(([t, i, f, g]) => card(t, i, g ? html`<div class="grid3">${fields(f, s)}</div>` : fields(f, s)))}
      <div style="position:sticky;bottom:calc(var(--tab-h) + var(--safe-b) + 20px);z-index:5;padding-top:6px"><button class="btn pri lg block" data-save style="box-shadow:var(--float)">${ic('check')} حفظ كل الإعدادات</button></div>`);
    $('[data-save]', ctx.root).onclick = e => busy(e.currentTarget, async () => {
      const v = collect(ctx.root);
      if (await saveSettings(v)) { Object.assign(S.boot, { site_name: v.site_name, announce_bar: v.announce_bar, registration_enabled: v.registration_enabled === '1', guest_mode: v.guest_mode === '1' }); try { const b = await api('/api/boot'); Object.assign(S.boot, b); } catch (x) {} }
    });
  },
};
