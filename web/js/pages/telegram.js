// تيليجرام: ربط الحساب + القنوات الموثّقة (وجهة كل التنبيهات)
import { S, api, load, peek, drop, isLogged, canWrite } from '../core/api.js?v=__BUILD__';
import { html, raw, render, $, ic, avatar, ago, num, plain } from '../core/dom.js?v=__BUILD__';
import { sheet, empty, skelGrid, errorBox, bad } from '../core/ui.js?v=__BUILD__';
import { card, actions, paintTones } from '../components/channel-tools.js?v=__BUILD__';
import { verifyChannel, linkAccount } from '../components/tg-flows.js?v=__BUILD__';
import { SRC } from './activity.js?v=__BUILD__';

export default {
  async render(ctx) {
    const bot = S.boot.bot_link;
    if (!isLogged()) {
      render(ctx.root, html`<header class="page-head"><span class="pi tg">${ic('tg')}</span><div><h1>تيليجرام</h1><p>كل التنبيهات من كيك ويوتيوب وX وتيك توك تصل إلى قنواتك هنا.</p></div></header>
        ${how(bot)}<div class="sp"></div><div class="hstack"><a class="btn pri" href="/login?next=/telegram">سجّل دخولك للبدء</a></div>`);
      return;
    }
    const paint = (d, err) => {
      if (!ctx.alive()) return;
      const u = S.me.user, rows = d ? d.rows || [] : null, lim = d && d.limits;
      const linked = !!u.linked_tg_id;
      render(ctx.root, html`
        <header class="page-head"><span class="pi tg">${ic('tg')}</span><div><h1>تيليجرام</h1><p>قنواتك الموثّقة هي وجهة كل التنبيهات.</p></div>
          <div class="acts"><a class="btn ghost" href="/activity">${ic('activity')}<span>سجل الإرسال</span></a><button class="btn pri" data-verify ${!canWrite() || (lim && lim.remaining <= 0) ? raw('disabled') : ''}>${ic('shieldOk')} توثيق قناة</button></div></header>

        <div class="group">
          <button class="row" data-link><span class="pi tg">${ic('user')}</span><span class="row-tx"><b>${linked ? 'حسابك مربوط' : 'اربط حسابك في تيليجرام'}</b><small class="${linked ? 'ltr' : ''}" style="${linked ? 'text-align:start' : ''}">${linked ? (u.linked_tg_username || u.linked_tg_name) : 'لمضاعفة الحدود واستلام الإرسال التجريبي'}</small></span>
            <span class="row-end">${linked ? html`<span class="tag ${u.is_member ? 'ok' : 'warn'}">${u.is_member ? 'عضو' : 'غير عضو'}</span>` : html`<span class="tag ac">اربط</span>`}${ic('chev', 'chev')}</span></button>
          ${S.boot.required_channel_url ? html`<a class="row" href="${S.boot.required_channel_url}" target="_blank" rel="noopener"><span class="pi warn">${ic('gift')}</span><span class="row-tx"><b>${S.boot.required_channel_name || 'القناة الرسمية'}</b><small>انضم لمضاعفة حدودك في كل المنصات</small></span><span class="row-end">${ic('ext')}</span></a>` : ''}
          ${bot ? html`<a class="row" href="${bot}" target="_blank" rel="noopener"><span class="pi">${ic('tg')}</span><span class="row-tx"><b>البوت</b><small class="ltr" style="text-align:start">@${S.boot.bot_username || bot.replace(/^https?:\/\/t\.me\//, '')}</small></span><span class="row-end">${ic('ext')}</span></a>` : ''}
        </div>

        <div class="sec"><div class="sec-h"><h2>القنوات الموثّقة</h2>${lim && lim.limit < 9999 ? html`<span class="tag num">${lim.used} / ${lim.limit}</span>` : ''}</div>
          ${err ? errorBox(err, true) : !rows ? skelGrid(2) : !rows.length ? html`${empty('tg', 'لم توثّق أي قناة بعد', 'وثّق قناتك مرة واحدة، وبعدها تصلها كل التنبيهات تلقائياً.', html`<button class="btn pri" data-verify>${ic('shieldOk')} توثيق أول قناة</button>`)}${how(bot)}`
            : html`<div class="grid">${rows.map(r => card('tg', r))}</div>`}
        </div>`);
      paintTones(ctx.root);
    };
    const reload = async () => { try { const d = await load('ch:tg', '/api/channels/tg', 0); if (S.me.usage && d.limits) S.me.usage.tg = d.limits.used; paint(d); } catch (e) { paint(peek('ch:tg'), peek('ch:tg') ? null : e); } };
    ctx.onRefresh(() => { drop('ch:tg'); return reload(); });
    ctx.cleanup(() => {});
    const onMe = () => paint(peek('ch:tg'));
    window.addEventListener('rl:me', onMe); ctx.cleanup(() => window.removeEventListener('rl:me', onMe));
    ctx.root.addEventListener('click', async e => {
      if (e.target.closest('[data-verify]')) return verifyChannel(reload);
      if (e.target.closest('[data-link]')) return linkAccount(() => paint(peek('ch:tg')));
      if (e.target.closest('[data-retry]')) return reload();
      const c = e.target.closest('.ch'); if (!c) return;
      const r = ((peek('ch:tg') || {}).rows || []).find(x => x.id === +c.dataset.id); if (!r) return;
      const a = e.target.closest('[data-act]'); if (!a) return;
      if (a.dataset.act === 'log') return showLog(r);
      if (a.dataset.act === 'more') return actions('tg', r, reload);
    });
    paint(peek('ch:tg') || null);
    if (ctx.query.get('verify') === '1') { history.replaceState(history.state, '', '/telegram'); setTimeout(() => verifyChannel(reload), 250); }
    await reload();
  },
};

function how(bot) {
  return html`<div class="card pad" style="margin-top:14px"><div class="sec-h" style="margin-bottom:6px"><h2 style="font-size:var(--fs-3)">كيف تعمل؟</h2></div>
    <div class="steps">
      <div class="step"><span class="n">1</span><div class="row-tx"><b>أضف البوت كمشرف في قناتك</b><small>مع صلاحية نشر الرسائل${bot ? '' : ' — رابط البوت يظهر بعد ضبطه من الإدارة'}</small></div>${bot ? html`<a class="btn sm soft" href="${bot}" target="_blank" rel="noopener">${ic('tg')} البوت</a>` : ''}</div>
      <div class="step"><span class="n">2</span><div class="row-tx"><b>وثّق القناة من هنا</b><small>يصل لمشرف القناة رمز من 6 أرقام</small></div></div>
      <div class="step"><span class="n">3</span><div class="row-tx"><b>أضف قنواتك من المنصات</b><small>كل بث أو فيديو أو تغريدة جديدة يصل تلقائياً</small></div></div>
    </div></div>`;
}

async function showLog(r) {
  let d; try { d = await api('/api/channels/tg/' + r.id + '/messages'); } catch (e) { return bad(e); }
  const rows = d.rows || [];
  sheet({ title: 'آخر ما وصل إلى «' + (d.name || r.name) + '»', size: 'wide',
    body: rows.length ? html`<div class="tl">${rows.map(m => { const s = SRC[m.source] || SRC.manual; return html`<div class="item">${m.image ? html`<img class="thumb" src="${m.image}" alt="" loading="lazy" onerror="this.remove()">` : html`<span class="pi ${s.c}">${ic(s.i)}</span>`}
      <div class="item-tx"><b>${m.source_name || s.n}</b><p>${plain(m.text).slice(0, 260)}</p><time>${s.n}  ${ago(m.ts)}</time>${m.ok ? '' : html`<span class="tag bad" style="margin-top:6px">${ic('warn')} لم تُرسل</span>`}</div></div>`; })}</div>`
      : empty('inbox', 'لا رسائل بعد', 'هنا تظهر آخر 25 رسالة أرسلها البوت لهذه القناة.') });
}
