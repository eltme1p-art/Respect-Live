// الرئيسية: من على الهواء الآن، وماذا وصل لقنواتك
import { S, api, load, peek, isLogged, isOwner, ttOn, canDiscord, KIND, urlOf } from '../core/api.js?v=__BUILD__';
import { html, raw, render, $, ic, avatar, num, compact, ago, plain } from '../core/dom.js?v=__BUILD__';
import { empty, errorBox } from '../core/ui.js?v=__BUILD__';
import { paintTones } from '../components/channel-tools.js?v=__BUILD__';
import { SRC } from './activity.js?v=__BUILD__';

export function liveCard(r) {
  const img = r.thumb || r.banner;
  const kind = r.kind || 'kick';
  return html`<a class="live-card" href="${urlOf(kind, { ...r, live: 1 })}" target="_blank" rel="noopener">
    ${img ? html`<img src="${img}" alt="" loading="lazy" decoding="async" onerror="this.remove()">` : html`<span class="cv" data-tone="${r.avatar || ''}" data-seed="${r.slug}"></span>`}
    <div class="top"><span class="tag air">على الهواء</span><span class="viewers">${ic('eye')}${compact(r.viewers)}</span></div>
    <div class="bot">${avatar(r.avatar, r.name, 'sm onair')}<div class="clip grow"><b class="clip">${r.name || r.slug}</b><small class="clip">${r.title || KIND[kind].name}</small></div><span class="pi sm ${kind}" style="background:rgba(0,0,0,.4)">${ic(kind)}</span></div></a>`;
}

function greet() { const h = new Date().getHours(); return h < 5 ? 'سهرة سعيدة' : h < 12 ? 'صباح الخير' : h < 18 ? 'مساء الخير' : 'مساء النور'; }

export default {
  async render(ctx) {
    if (!isLogged()) return guest(ctx);
    const paint = (d, err) => {
      if (!ctx.alive()) return;
      const u = S.me.user, my = d ? d.my : {}, live = d ? d.live_now || [] : [];
      const mineLive = d ? my.live || 0 : 0;
      const total = d ? (my.kick || 0) + (my.yt || 0) + (my.tw || 0) + (my.tt || 0) : 0;
      const steps = [
        { done: !!u.linked_tg_id, t: 'اربط حسابك في تيليجرام', s: 'لمضاعفة الحدود والإرسال التجريبي', href: '/telegram' },
        { done: d && my.tg > 0, t: 'وثّق قناة تيليجرام', s: 'هي وجهة كل التنبيهات', href: '/telegram?verify=1' },
        { done: d && total > 0, t: 'أضف أول قناة تتابعها', s: 'كيك أو يوتيوب أو X أو تيك توك', href: '/kick?add=1' },
        { done: !S.boot.has_push || S.pushOn, t: 'فعّل إشعارات هذا الجهاز', s: 'تنبيه فوري حتى لو الموقع مغلق', href: '/account#push' },
      ];
      const left = steps.filter(x => !x.done).length;
      const status = !d ? 'لحظة…' : mineLive
        ? html`<span class="air">${num(mineLive)} ${mineLive === 1 ? 'من قنواتك على الهواء الآن' : 'من قنواتك على الهواء الآن'}</span>، و${my.sent_today ? html`وصل لقنواتك <strong>${num(my.sent_today)}</strong> تنبيه خلال آخر 24 ساعة.` : 'لم يصل أي تنبيه اليوم بعد.'}`
        : total ? html`قنواتك هادئة الآن. ${my.sent_today ? html`وصل لقنواتك <strong>${num(my.sent_today)}</strong> تنبيه خلال آخر 24 ساعة.` : 'سنخبرك فور بدء أي بث أو نشر جديد.'}`
          : 'ابدأ بإضافة القنوات التي تتابعها، ونرسل تنبيهاتها لقنواتك في تيليجرام.';
      const tiles = [['kick', '/kick'], ['yt', '/youtube'], ['tw', '/x']].concat(ttOn() ? [['tt', '/tiktok']] : []).concat([['tg', '/telegram']]).concat(canDiscord() ? [['dc', '/discord']] : []);
      render(ctx.root, html`
        <section class="hello"><h1>${greet()}، ${u.display || u.username}</h1><p class="status">${status}</p></section>

        ${u.is_member ? '' : S.boot.required_channel_url && u.linked_tg_id ? html`<div class="callout warn" style="margin-top:16px">${ic('gift')}<div><b>ضاعف حدودك</b><br>${S.me.required_channel_msg || 'انضم للقناة الرسمية ثم أعد فحص العضوية من صفحة تيليجرام.'}</div><a class="btn sm soft" href="${S.boot.required_channel_url}" target="_blank" rel="noopener" style="align-self:center">انضم</a></div>` : ''}

        ${live.length ? html`<section class="sec"><div class="sec-h"><h2>على الهواء</h2><a class="more" href="/live">عرض الكل${ic('chev', 'chev')}</a></div><div class="live-strip">${live.map(liveCard)}</div></section>` : ''}

        ${left && d ? html`<section class="sec"><div class="sec-h"><h2>ابدأ من هنا</h2><span class="tag">${4 - left} من 4</span></div><div class="steps">${steps.map((s, i) => html`<a class="step ${s.done ? 'done' : ''}" href="${s.href}"><span class="n">${s.done ? ic('check') : i + 1}</span><span class="row-tx"><b>${s.t}</b><small>${s.s}</small></span>${s.done ? '' : ic('chev', 'chev')}</a>`)}</div></section>` : ''}

        <section class="sec"><div class="sec-h"><h2>قنواتك</h2></div><div class="plat-tiles">${tiles.map(([k, h]) => html`<a class="ptile" href="${h}"><span class="pi ${k}">${ic(k)}</span><span><b class="num">${k === 'dc' ? num(my.feeds || 0) : num(my[k] || 0)}</b><small>${KIND[k].name}</small></span></a>`)}</div></section>

        ${d && d.recent && d.recent.length ? html`<section class="sec"><div class="sec-h"><h2>آخر ما وصل لقنواتك</h2><a class="more" href="/activity">السجل كاملاً${ic('chev', 'chev')}</a></div>
          <div class="group">${d.recent.map(m => { const s = SRC[m.source] || SRC.manual; return html`<a class="row" href="/activity"><span class="pi sm ${s.c}">${ic(s.i)}</span><span class="row-tx"><b class="clip">${m.source_name || s.n}</b><small class="clip">${plain(m.text).slice(0, 90)}</small></span><span class="row-end">${m.ok ? '' : html`<span class="tag bad">لم تصل</span>`}<span>${ago(m.ts)}</span></span></a>`; })}</div></section>` : ''}

        ${d && d.videos && d.videos.length ? html`<section class="sec"><div class="sec-h"><h2>فيديوهات جديدة</h2></div><div class="vgrid">${d.videos.map(v => html`<a class="vcard" href="${v.url}" target="_blank" rel="noopener"><img src="${v.thumb}" alt="" loading="lazy" onerror="this.src='https://i.ytimg.com/vi/${v.video_id}/hqdefault.jpg'"><div><b>${v.title}</b><small>${v.ch_name}  ${ago(v.ts)}</small></div></a>`)}</div></section>` : ''}

        ${isOwner() ? html`<section class="sec"><a class="adm-card" href="/admin"><span class="pi violet">${ic('shield')}</span><span><b>لوحة الإدارة</b><small>المستخدمون والإعدادات وصحة النظام</small></span></a></section>` : ''}
        ${err ? errorBox(err, true) : ''}`);
      paintTones(ctx.root);
    };
    const reload = async (force) => { try { paint(await load('home', '/api/home-stats', force ? 0 : 20000)); } catch (e) { paint(peek('home'), peek('home') ? null : e); } };
    ctx.onRefresh(() => reload(true));
    ctx.root.addEventListener('click', e => { if (e.target.closest('[data-retry]')) reload(true); });
    paint(peek('home'));
    await reload(true);
    const t = setInterval(() => { if (document.visibilityState === 'visible') reload(true); }, 60000);
    ctx.cleanup(() => clearInterval(t));
  },
};

async function guest(ctx) {
  const b = S.boot;
  let p = null;
  const paint = () => render(ctx.root, html`
    <section class="hello" style="padding-top:18px"><h1>${b.hero_title || 'مراقبة'} <span>${b.hero_accent || 'القنوات.'}</span></h1>
      <p class="status">${b.hero_text || 'تابع قنواتك على كيك ويوتيوب وX وتيك توك، وتصلك التنبيهات في تيليجرام فور حدوثها.'}</p>
      <div class="hstack" style="margin-top:18px">${b.registration_enabled ? html`<a class="btn pri lg" href="/register">أنشئ حسابك مجاناً</a>` : ''}<a class="btn lg" href="/login">تسجيل الدخول</a></div></section>
    ${p && p.live && p.live.length ? html`<section class="sec"><div class="sec-h"><h2>على الهواء الآن</h2></div><div class="live-strip">${p.live.map(r => liveCard(r))}</div></section>` : ''}
    <section class="sec"><div class="plat-tiles">
      ${[['kick', 'بث كيك', 'تنبيه لحظة بدء البث'], ['yt', 'يوتيوب', 'كل فيديو جديد خلال دقائق'], ['tw', 'X', 'التغريدات مع فلترة ذكية'], ['tt', 'تيك توك', 'بداية البث المباشر'], ['tg', 'تيليجرام', 'كل شيء يصل قنواتك تلقائياً']].filter(x => x[0] !== 'tt' || ttOn())
        .map(([k, t, s]) => html`<div class="ptile"><span class="pi ${k}">${ic(k)}</span><span><b style="font-size:var(--fs-2)">${t}</b><small>${s}</small></span></div>`)}</div></section>
    ${p ? html`<section class="sec"><div class="statrow">${[['kick', 'قناة كيك'], ['yt', 'قناة يوتيوب'], ['tg', 'قناة تيليجرام'], ['tw', 'حساب X']].map(([k, t]) => html`<div class="stat"><b>${num(p.counts[k] || 0)}</b><small>${t} تحت المراقبة</small></div>`)}</div></section>` : ''}`);
  paint();
  if (b.guest_mode) { try { p = await api('/api/guest-preview'); if (ctx.alive()) { paint(); paintTones(ctx.root); } } catch (e) {} }
}
