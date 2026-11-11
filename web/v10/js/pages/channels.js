// صفحة منصة: كيك / يوتيوب / X / تيك توك
import { S, api, post, load, peek, put, drop, KIND, handleOf, isLogged, isOwner, canWrite, canDiscord, ttOn } from '../core/api.js?v=__BUILD__';
import { html, raw, render, $, $$, ic, num, debounce, ls } from '../core/dom.js?v=__BUILD__';
import { toast, ok, bad, confirm, menu, empty, skelGrid, errorBox } from '../core/ui.js?v=__BUILD__';
import { card, actions, editMessage, addChannel, paintTones } from '../components/channel-tools.js?v=__BUILD__';

export function platSeg(active) {
  const items = [['kick', '/kick', 'كيك'], ['yt', '/youtube', 'يوتيوب'], ['tw', '/x', 'X']];
  if (ttOn()) items.push(['tt', '/tiktok', 'تيك توك']);
  if (canDiscord()) items.push(['dc', '/discord', 'ديسكورد']);
  return html`<nav class="seg plat" aria-label="المنصات" style="margin-bottom:16px">${items.map(([k, h, t]) => html`<a href="${h}" class="${k === active ? 'on' : ''}" style="--c:var(--${k === 'tw' ? 'x' : k})">${ic(k)}<span>${t}</span></a>`)}</nav>`;
}

const FILTERS = [['all', 'الكل'], ['live', 'على الهواء'], ['on', 'تعمل'], ['off', 'موقوفة'], ['muted', 'بدون تنبيه'], ['custom', 'رسالة مخصصة']];
const SORTS = [['new', 'الأحدث إضافة'], ['name', 'الاسم'], ['live', 'المباشر أولاً'], ['viewers', 'الأكثر مشاهدة']];

export default {
  async render(ctx) {
    const kind = ctx.params.kind, K = KIND[kind];
    const st = { q: '', f: 'all', sort: ls.get('rl_sort_' + kind, kind === 'kick' || kind === 'tt' ? 'live' : 'new'), sel: null, mine: ls.get('rl_mine', '1') === '1' };
    const isLive = kind === 'kick' || kind === 'tt';
    const key = () => 'ch:' + kind + (isOwner() && !st.mine ? ':all' : '');
    const url = () => '/api/channels/' + kind + (isOwner() && st.mine ? '?mine=1' : '');

    if (!isLogged()) {
      render(ctx.root, html`${platSeg(kind)}<div class="page-head"><span class="pi ${kind}">${ic(kind)}</span><div><h1>${K.name}</h1><p>${pitch(kind)}</p></div></div>
        <div class="card pad-l" style="text-align:center;max-width:520px;margin:30px auto"><span class="pi lg ${kind}" style="margin:0 auto 14px;width:56px;height:56px">${ic(kind)}</span>
        <h3 style="font-size:var(--fs-4);margin-bottom:6px">سجّل دخولك لإضافة قنواتك</h3><p class="mu" style="margin-bottom:16px;font-size:var(--fs-2)">بعد الإضافة تصل تنبيهات ${K.name} إلى قنواتك في تيليجرام تلقائياً.</p>
        <div class="hstack" style="justify-content:center"><a class="btn pri" href="/login?next=${K.path}">تسجيل الدخول</a><a class="btn ghost" href="/register">حساب جديد</a></div></div>`);
      return;
    }

    const paint = (data, err) => {
      if (!ctx.alive()) return;
      const rows = data ? data.rows || [] : null;
      const lim = data ? data.limits : null;
      const full = lim && lim.remaining <= 0;
      const pct = lim && lim.limit ? Math.min(100, lim.used / lim.limit * 100) : 0;
      let list = rows ? filterSort(rows) : null;
      const liveN = rows ? rows.filter(r => r.live && r.enabled).length : 0;
      render(ctx.root, html`
        ${platSeg(kind)}
        <header class="page-head">
          <span class="pi ${kind}">${ic(kind)}</span>
          <div><h1>${kind === 'tw' ? 'حسابات X' : kind === 'tt' ? 'حسابات تيك توك' : 'قنوات ' + K.name}</h1>
            <p>${rows ? (rows.length ? num(rows.length) + (kind === 'tw' || kind === 'tt' ? ' حساب' : ' قناة') + (isLive && liveN ? '، منها ' + num(liveN) + ' على الهواء الآن' : '') : pitch(kind)) : 'جارٍ التحميل…'}</p></div>
          <div class="acts">
            ${rows && rows.length > 1 ? html`<button class="btn ${st.sel ? 'soft' : 'ghost'}" data-selmode>${ic('select')}<span>${st.sel ? 'إنهاء التحديد' : 'تحديد'}</span></button>` : ''}
            <button class="btn pri" data-add ${full || !canWrite() ? raw('disabled') : ''}>${ic('plus')} إضافة</button></div>
        </header>
        ${kind === 'tw' && !S.me.has_twitter ? html`<div class="callout warn" style="margin-bottom:14px">${ic('warn')}<div><b>متابعة X متوقفة حالياً</b><br>الإدارة لم تضف مفتاح X API بعد، لذلك لن تُجلب التغريدات حتى يُضاف.</div></div>` : ''}
        ${lim && lim.limit < 9999 ? html`<div class="card limit"><span class="mu" style="font-size:var(--fs-1)">الحد</span><div class="meter ${pct >= 100 ? 'full' : pct >= 80 ? 'warn' : ''}"><i style="width:${pct}%"></i></div><b class="num">${lim.used} / ${lim.limit}</b>
          ${lim.is_member ? html`<span class="tag ok">${ic('gift')} مضاعف</span>` : html`<a class="tag ac" href="/telegram">ضاعف الحد</a>`}</div>` : ''}
        ${rows && rows.length ? html`<div class="toolbar">
          <label class="search">${ic('search')}<input type="search" placeholder="ابحث في ${kind === 'tw' || kind === 'tt' ? 'الحسابات' : 'القنوات'}…" value="${st.q}" aria-label="بحث"></label>
          <button class="btn icon" data-sort title="الترتيب" aria-label="الترتيب">${ic('sort')}</button>
          ${isOwner() ? html`<button class="btn ${st.mine ? '' : 'soft'}" data-mine title="عرض قنوات كل المستخدمين">${ic('users')}<span>${st.mine ? 'قنواتي' : 'الكل'}</span></button>` : ''}
        </div>
        <div class="chips" style="margin-bottom:16px" data-filters>${FILTERS.filter(([k]) => isLive || k !== 'live').map(([k, t]) => html`<button class="chip ${st.f === k ? 'on' : ''}" data-f="${k}">${t}<span class="n">${num(count(rows, k))}</span></button>`)}</div>` : ''}
        <div data-list>${err ? errorBox(err, true) : !rows ? skelGrid(6) : !rows.length ? empty(kind, kind === 'tw' || kind === 'tt' ? 'لا توجد حسابات بعد' : 'لا توجد قنوات بعد', emptyText(kind), html`<button class="btn pri" data-add>${ic('plus')} ${kind === 'tw' || kind === 'tt' ? 'أضف أول حساب' : 'أضف أول قناة'}</button>`)
          : !list.length ? empty('search', 'لا نتائج', 'جرّب كلمة أخرى أو غيّر الفلتر.') : html`<div class="grid">${list.map(r => card(kind, r, { selecting: !!st.sel, sel: st.sel && st.sel.has(r.id) }))}</div>`}</div>
        ${!full && canWrite() ? html`<button class="fab" data-add aria-label="إضافة">${ic('plus')}</button>` : ''}
        ${st.sel ? html`<div class="selbar blur"><b>${st.sel.size ? 'اخترت ' + num(st.sel.size) : 'اختر قنوات'}</b>
          <button class="btn sm ghost" data-bulk="all">${ic('select')} الكل</button>
          <button class="btn sm" data-bulk="menu" ${st.sel.size ? '' : raw('disabled')}>${ic('more')} إجراء</button>
          <button class="btn sm icon ghost" data-selmode aria-label="إنهاء">${ic('x')}</button></div>` : ''}`);
      paintTones(ctx.root);
      const on = $('.seg.plat .on', ctx.root); if (on && on.parentElement.scrollWidth > on.parentElement.clientWidth) on.parentElement.scrollLeft = on.offsetLeft - on.parentElement.clientWidth / 2 + on.clientWidth / 2;
      const s = $('.search input', ctx.root);
      if (s) s.addEventListener('input', debounce(() => { st.q = s.value; const pos = s.selectionStart; paint(peek(key())); const n = $('.search input', ctx.root); if (n) { n.focus(); n.setSelectionRange(pos, pos); } }, 140));
      if (ctx._focus && rows) { const el = $('#ch-' + ctx._focus, ctx.root); if (el) { el.scrollIntoView({ block: 'center' }); el.classList.add('sel'); setTimeout(() => el.classList.remove('sel'), 1800); } ctx._focus = null; }
    };

    const filterSort = rows => {
      const qq = st.q.trim().toLowerCase();
      let out = rows.filter(r => {
        if (qq && !((r.name || '') + ' ' + handleOf(kind, r)).toLowerCase().includes(qq)) return false;
        return matchF(r, st.f);
      });
      const by = { name: (a, b) => (a.name || '').localeCompare(b.name || '', 'ar'), live: (a, b) => (b.live * b.enabled - a.live * a.enabled) || (b.viewers || 0) - (a.viewers || 0) || b.id - a.id,
        viewers: (a, b) => (b.viewers || 0) - (a.viewers || 0), new: (a, b) => b.id - a.id }[st.sort] || ((a, b) => b.id - a.id);
      return out.sort(by);
    };
    const matchF = (r, f) => f === 'all' || (f === 'live' && r.live && r.enabled) || (f === 'on' && r.enabled) || (f === 'off' && !r.enabled) || (f === 'muted' && r.auto_send === 0) || (f === 'custom' && !!r.msg);
    const count = (rows, f) => rows.filter(r => matchF(r, f)).length;

    const reload = async (force) => {
      try { const d = force ? await (drop(key()), load(key(), url(), 0)) : await load(key(), url(), 0); if (S.me && d.limits) { S.me.usage = S.me.usage || {}; S.me.usage[kind] = d.limits.used; } paint(d); }
      catch (e) { paint(peek(key()), peek(key()) ? null : e); if (peek(key())) bad(e); }
    };
    ctx.onRefresh(() => reload(true));
    ctx._focus = +ctx.query.get('focus') || null;

    ctx.root.addEventListener('click', async e => {
      const t = e.target;
      if (t.closest('[data-add]')) return addChannel(kind, reload);
      if (t.closest('[data-retry]')) return reload(true);
      const f = t.closest('[data-f]'); if (f) { st.f = f.dataset.f; return paint(peek(key())); }
      if (t.closest('[data-sort]')) return menu(SORTS.map(([k, l]) => ({ icon: st.sort === k ? 'check' : 'sort', label: l, fn: () => { st.sort = k; ls.set('rl_sort_' + kind, k); paint(peek(key())); } })), { title: 'ترتيب حسب' });
      if (t.closest('[data-mine]')) { st.mine = !st.mine; ls.set('rl_mine', st.mine ? '1' : '0'); paint(null); return reload(); }
      if (t.closest('[data-selmode]')) { st.sel = st.sel ? null : new Set(); return paint(peek(key())); }
      const b = t.closest('[data-bulk]');
      if (b) {
        const rows = filterSort((peek(key()) || {}).rows || []);
        if (b.dataset.bulk === 'all') { const allOn = rows.every(r => st.sel.has(r.id)); rows.forEach(r => allOn ? st.sel.delete(r.id) : st.sel.add(r.id)); return paint(peek(key())); }
        return bulkMenu();
      }
      const cardEl = t.closest('.ch'); if (!cardEl) return;
      const id = +cardEl.dataset.id;
      const r = ((peek(key()) || {}).rows || []).find(x => x.id === id); if (!r) return;
      if (st.sel && !t.closest('a')) { e.preventDefault(); st.sel.has(id) ? st.sel.delete(id) : st.sel.add(id); return paint(peek(key())); }
      const act = t.closest('[data-act]'); if (!act) return;
      if (act.dataset.act === 'edit') return editMessage(kind, r, reload);
      if (act.dataset.act === 'more') return actions(kind, r, reload);
    });

    function bulkMenu() {
      const ids = [...st.sel];
      const go = async (action, msg) => { try { const r = await post('/api/channels/' + kind + '/bulk', { ids, action }); ok(msg.replace('{n}', num(r.affected))); st.sel = null; drop('ch:' + kind); drop('home'); reload(true); } catch (e) { bad(e); } };
      menu([
        { icon: 'play', label: 'تشغيل المراقبة', fn: () => go('enable', 'شغّلنا {n}') },
        { icon: 'pause', label: 'إيقاف المراقبة', fn: () => go('disable', 'أوقفنا {n}') },
        { icon: 'bellOff', label: 'إيقاف التنبيهات', fn: () => go('mute', 'أوقفنا تنبيهات {n}') },
        { icon: 'bell', label: 'تشغيل التنبيهات', fn: () => go('unmute', 'شغّلنا تنبيهات {n}') },
        '-',
        { icon: 'trash', label: 'حذف المحدد', danger: true, fn: async () => { if (await confirm('سيُحذف ' + num(ids.length) + ' نهائياً.', { title: 'حذف المحدد؟', ok: 'حذف', danger: true })) go('delete', 'حذفنا {n}'); } },
      ], { title: num(ids.length) + ' محددة' });
    }

    const cached = peek(key());
    paint(cached || null);
    if (ctx.query.get('add') === '1') { history.replaceState(history.state, '', location.pathname); setTimeout(() => addChannel(kind, reload), 250); }
    await reload();
    // تحديث تلقائي لحالة البث
    if (isLive) { const t = setInterval(() => { if (document.visibilityState === 'visible' && !st.sel && !document.querySelector('.sheet-wrap')) { drop(key()); reload(); } }, 60000); ctx.cleanup(() => clearInterval(t)); }
  },
};

function pitch(kind) {
  return { kick: 'تنبيه لحظة بدء أي بث، مع العنوان وعدد المشاهدين.', yt: 'تنبيه لكل فيديو جديد خلال دقائق من نشره.', tw: 'التغريدات الجديدة تصل قنواتك، مع فلترة ما لا تريده.', tt: 'تنبيه عندما يبدأ الحساب بثاً مباشراً.' }[kind];
}
function emptyText(kind) {
  return { kick: 'أضف قناة كيك، وعندما تبدأ البث نرسل التنبيه لقنواتك في تيليجرام.', yt: 'أضف قناة يوتيوب ونخبرك بكل فيديو جديد.', tw: 'أضف حساب X وتصل تغريداته لقنواتك.', tt: 'أضف حساب تيك توك ونخبرك عند بدء البث.' }[kind];
}
