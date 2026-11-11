// التنبيهات: كل ما حدث في قنواتك، مجمّع حسب اليوم
import { S, api, post, del, emit } from '../core/api.js?v=__BUILD__';
import { html, render, ic, ago, dayLabel, time } from '../core/dom.js?v=__BUILD__';
import { empty, skelList, errorBox, confirm, ok, bad } from '../core/ui.js?v=__BUILD__';
import { pushSupported, pushStatus, enablePush } from '../core/push.js?v=__BUILD__';

const KINDS = [['', 'الكل', 'bell'], ['kick', 'كيك', 'kick'], ['yt', 'يوتيوب', 'yt'], ['tw', 'X', 'tw'], ['tt', 'تيك توك', 'tt'], ['discord', 'ديسكورد', 'dc'], ['admin', 'الإدارة', 'megaphone']];
const KI = { kick: ['kick', 'kick'], yt: ['yt', 'yt'], tw: ['tw', 'tw'], tt: ['tt', 'tt'], discord: ['dc', 'dc'], admin: ['megaphone', 'violet'], tg_verify: ['shieldOk', 'ok'] };

export default {
  async render(ctx) {
    let kind = '', data = null, err = null;
    await pushStatus();
    const paint = () => {
      if (!ctx.alive()) return;
      const rows = data ? data.rows : null; let last = '';
      render(ctx.root, html`
        <header class="page-head"><span class="pi">${ic('bell')}</span><div><h1>التنبيهات</h1><p>${data ? (data.unread ? data.unread + ' غير مقروءة' : 'قرأت كل شيء') : ''}</p></div>
          ${rows && rows.length ? html`<div class="acts"><button class="btn ghost" data-read>${ic('check')}<span>تعليم الكل كمقروء</span></button><button class="btn ghost" data-clear>${ic('trash')}<span>مسح</span></button></div>` : ''}</header>
        ${S.boot.has_push && pushSupported() && !S.pushOn ? html`<div class="callout" style="margin-bottom:16px">${ic('device')}<div class="grow"><b>استلمها حتى لو الموقع مغلق</b><br>فعّل إشعارات هذا الجهاز لتصلك لحظة حدوثها.</div><button class="btn sm pri" data-push style="align-self:center">تفعيل</button></div>` : ''}
        <div class="chips" style="margin-bottom:14px">${KINDS.map(([k, t, i]) => html`<button class="chip ${kind === k ? 'on' : ''}" data-k="${k}">${ic(i)}${t}</button>`)}</div>
        ${err ? errorBox(err, true) : !rows ? skelList(6) : !rows.length ? empty('inbox', kind ? 'لا تنبيهات من هذا النوع' : 'لا تنبيهات بعد', 'عندما يبدأ بث أو يُنشر جديد في قنواتك، يظهر هنا.')
          : html`<div class="tl">${rows.map(n => { const d = dayLabel(n.ts), h = d !== last ? html`<div class="tl-day">${d}</div>` : ''; last = d; const k = KI[n.kind] || ['bell', 'mu'];
            return html`${h}<div class="item ${n.is_read ? '' : 'un'}" data-id="${n.id}">${n.image ? html`<img class="thumb" src="${n.image}" alt="" loading="lazy" onerror="this.remove()">` : html`<span class="pi ${k[1]}">${ic(k[0])}</span>`}
              <div class="item-tx"><b>${n.title}</b>${n.body ? html`<p>${n.body}</p>` : ''}
              <div class="acts" style="align-items:center">${n.btn_url ? html`<a class="btn sm soft" href="${n.btn_url}" target="_blank" rel="noopener">${ic('ext')} ${n.btn_text || 'فتح'}</a>` : ''}<time title="${time(n.ts)}" style="margin:0">${ago(n.ts)}</time><button class="btn sm ghost icon" data-del aria-label="حذف" style="margin-inline-start:auto;width:30px;height:30px">${ic('trash')}</button></div></div></div>`; })}</div>`}`);
    };
    const reload = async () => { try { data = await api('/api/notifs' + (kind ? '?kind=' + kind : '')); err = null; S.unread = data.unread || 0; emit('badges'); } catch (e) { err = e; } paint(); };
    ctx.onRefresh(reload);
    const onPush = () => reload(); window.addEventListener('rl:push', onPush); ctx.cleanup(() => window.removeEventListener('rl:push', onPush));
    ctx.root.addEventListener('click', async e => {
      const c = e.target.closest('[data-k]'); if (c) { kind = c.dataset.k; data = null; paint(); return reload(); }
      if (e.target.closest('[data-retry]')) return reload();
      if (e.target.closest('[data-push]')) { if (await enablePush()) paint(); return; }
      if (e.target.closest('[data-read]')) { try { await post('/api/notifs/read-all'); data.rows.forEach(n => n.is_read = 1); data.unread = 0; S.unread = 0; emit('badges'); paint(); } catch (x) { bad(x); } return; }
      if (e.target.closest('[data-clear]')) { if (!await confirm('ستُحذف كل التنبيهات من هذه القائمة.', { title: 'مسح التنبيهات؟', ok: 'مسح', danger: true })) return; try { await post('/api/notifs/clear'); ok('مُسحت التنبيهات'); reload(); } catch (x) { bad(x); } return; }
      const it = e.target.closest('.item'); if (!it) return;
      const n = data.rows.find(x => x.id === +it.dataset.id);
      if (e.target.closest('[data-del]')) { try { await del('/api/notifs/' + n.id); data.rows = data.rows.filter(x => x !== n); if (!n.is_read) { data.unread--; S.unread = Math.max(0, S.unread - 1); emit('badges'); } paint(); } catch (x) { bad(x); } return; }
      if (!n.is_read) { n.is_read = 1; data.unread = Math.max(0, data.unread - 1); S.unread = Math.max(0, S.unread - 1); emit('badges'); it.classList.remove('un'); post('/api/notifs/' + n.id + '/read').catch(() => {}); }
    });
    paint(); await reload();
  },
};
