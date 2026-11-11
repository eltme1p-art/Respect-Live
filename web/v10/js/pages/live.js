// على الهواء: كل البثوث المباشرة الآن، تتحدث تلقائياً
import { S, load, peek, isLogged, api } from '../core/api.js?v=__BUILD__';
import { html, render, ic, num, time } from '../core/dom.js?v=__BUILD__';
import { empty, errorBox } from '../core/ui.js?v=__BUILD__';
import { paintTones } from '../components/channel-tools.js?v=__BUILD__';
import { liveCard } from './home.js?v=__BUILD__';

export default {
  async render(ctx) {
    let at = 0;
    const paint = (d, err) => {
      if (!ctx.alive()) return;
      const rows = d ? (d.live_now || d.live || []) : null;
      render(ctx.root, html`<header class="page-head"><span class="pi air">${ic('signal')}</span><div><h1>على الهواء</h1><p>${rows ? (rows.length ? num(rows.length) + ' بث مباشر الآن' : 'لا يوجد بث الآن') : 'جارٍ التحميل…'}${at ? '  — آخر تحديث ' + time(at) : ''}</p></div></header>
        ${err ? errorBox(err, true) : !rows ? html`<div class="vgrid">${[1, 2, 3, 4].map(() => html`<div class="skel" style="aspect-ratio:16/10;border-radius:var(--r-card)"></div>`)}</div>`
          : rows.length ? html`<div class="vgrid" style="grid-template-columns:repeat(auto-fill,minmax(260px,1fr))">${rows.map(liveCard)}</div>`
            : empty('signal', 'لا أحد على الهواء الآن', 'نفحص قنوات كيك كل دقيقة ونصف تقريباً. عندما يبدأ أحد البث يظهر هنا ويصلك التنبيه.', html`<a class="btn soft" href="/kick">${ic('kick')} قنوات كيك</a>`)}`);
      paintTones(ctx.root);
    };
    const reload = async () => {
      try { const d = isLogged() ? await load('home', '/api/home-stats', 0) : await api('/api/guest-preview'); at = Date.now() / 1000; paint(d); }
      catch (e) { paint(peek('home'), peek('home') ? null : e); }
    };
    ctx.onRefresh(reload);
    paint(isLogged() ? peek('home') : null);
    await reload();
    const t = setInterval(() => { if (document.visibilityState === 'visible') reload(); }, 45000);
    ctx.cleanup(() => clearInterval(t));
  },
};
