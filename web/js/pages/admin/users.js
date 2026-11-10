// إدارة المستخدمين
import { S, api, post, patch, del } from '../../core/api.js?v=__BUILD__';
import { html, raw, render, $, ic, avatar, num, ago, date, debounce } from '../../core/dom.js?v=__BUILD__';
import { sheet, confirm, menu, ok, bad, toast, empty, skelList, errorBox } from '../../core/ui.js?v=__BUILD__';
import { head } from './_lib.js?v=__BUILD__';

const F = [['all', 'الكل'], ['owner', 'الإدارة'], ['member', 'أعضاء القناة'], ['linked', 'ربطوا تيليجرام'], ['dc', 'لديهم ديسكورد'], ['banned', 'محظورون'], ['idle', 'لم يدخلوا منذ 30 يوماً']];
const match = (u, f) => f === 'all' || (f === 'owner' && u.role === 'owner') || (f === 'member' && u.is_member) || (f === 'linked' && u.linked_tg_id) || (f === 'dc' && u.can_discord) || (f === 'banned' && u.banned) || (f === 'idle' && (!u.last_login || u.last_login < Date.now() / 1000 - 30 * 86400));
const total = u => Object.values(u.counts || {}).reduce((a, b) => a + b, 0);

export default {
  async render(ctx) {
    ctx.setTitle('المستخدمون');
    let rows = null, err = null, q = '', f = 'all', sort = 'new';
    const paint = () => {
      if (!ctx.alive()) return;
      const focused = document.activeElement && document.activeElement.matches('[data-q]');
      let list = rows ? rows.filter(u => match(u, f) && (!q || (u.username + ' ' + (u.display || '') + ' ' + (u.linked_tg_username || '')).toLowerCase().includes(q.toLowerCase()))) : [];
      list.sort(sort === 'new' ? (a, b) => b.id - a.id : sort === 'active' ? (a, b) => (b.last_login || 0) - (a.last_login || 0) : (a, b) => total(b) - total(a));
      render(ctx.root, html`${head('users', html`<button class="btn pri" data-add>${ic('plus')} مستخدم</button>`)}
        <div class="toolbar"><label class="search">${ic('search')}<input data-q placeholder="ابحث بالاسم أو يوزر تيليجرام" value="${q}"></label>
          <select class="input" data-sort style="width:auto;height:42px;font-size:var(--fs-1)"><option value="new" ${sort === 'new' ? raw('selected') : ''}>الأحدث</option><option value="active" ${sort === 'active' ? raw('selected') : ''}>آخر دخول</option><option value="ch" ${sort === 'ch' ? raw('selected') : ''}>الأكثر قنوات</option></select></div>
        <div class="chips" style="margin-bottom:14px">${F.map(([k, t]) => html`<button class="chip ${f === k ? 'on' : ''}" data-f="${k}">${t}${rows ? html`<span class="n">${num(rows.filter(u => match(u, k)).length)}</span>` : ''}</button>`)}</div>
        ${err ? errorBox(err, true) : !rows ? skelList(8) : !list.length ? empty('users', 'لا نتائج', '') : html`<div class="group">${list.slice(0, 300).map(u => html`<button class="row" data-id="${u.id}">${avatar(u.avatar, u.display || u.username, 'sm')}
          <span class="row-tx"><b class="clip">${u.display || u.username} ${u.role === 'owner' ? html`<span class="tag violet">إدارة</span>` : ''}${u.banned ? html`<span class="tag bad">محظور</span>` : ''}${u.is_member ? html`<span class="tag ok">عضو</span>` : ''}${u.can_discord ? html`<span class="tag">DC</span>` : ''}</b>
          <small class="clip"><span class="ltr">@${u.username}</span>  ${num(total(u))} قناة  ${u.last_login ? 'آخر دخول ' + ago(u.last_login) : 'لم يدخل بعد'}</small></span><span class="row-end">${ic('chev', 'chev')}</span></button>`)}</div>`}`);
      if (focused) { const i = $('[data-q]', ctx.root); i.focus(); i.setSelectionRange(q.length, q.length); }
    };
    const reload = async () => { try { rows = (await api('/api/admin/users')).rows; err = null; } catch (e) { err = e; } paint(); };
    ctx.onRefresh(reload);
    ctx.root.addEventListener('input', debounce(e => { if (e.target.matches('[data-q]')) { q = e.target.value; paint(); } }, 150));
    ctx.root.addEventListener('change', e => { if (e.target.matches('[data-sort]')) { sort = e.target.value; paint(); } });
    ctx.root.addEventListener('click', e => {
      const c = e.target.closest('[data-f]'); if (c) { f = c.dataset.f; return paint(); }
      if (e.target.closest('[data-retry]')) return reload();
      if (e.target.closest('[data-add]')) return addUser(reload);
      const r = e.target.closest('[data-id]'); if (r) return details(rows.find(x => x.id === +r.dataset.id), reload);
    });
    paint(); await reload();
  },
};

const limFields = u => html`<div class="grid2">${[['lim_kick', 'حد كيك'], ['lim_yt', 'حد يوتيوب'], ['lim_tg', 'حد تيليجرام'], ['lim_tw', 'حد X']].map(([k, t]) => html`<label class="field"><span>${t}</span><input name="${k}" type="number" min="0" value="${u && u[k] != null ? u[k] : ''}" placeholder="الافتراضي"></label>`)}</div><div class="hint" style="margin:-6px 0 12px">اتركه فارغاً ليتبع الحد الافتراضي (ويتضاعف تلقائياً للأعضاء)</div>`;
const readLims = root => Object.fromEntries(['lim_kick', 'lim_yt', 'lim_tg', 'lim_tw'].map(k => [k, $('[name=' + k + ']', root).value]));

function addUser(reload) {
  return sheet({ title: 'مستخدم جديد', size: 'wide',
    body: html`<div class="grid2"><label class="field"><span>اسم المستخدم</span><input name="un" class="ltr" autocapitalize="off"></label><label class="field"><span>الاسم الظاهر</span><input name="dn"></label></div>
      <label class="field"><span>كلمة المرور</span><input name="pw" type="text" class="ltr" autocomplete="off"><small>6 أحرف على الأقل — أعطها للمستخدم ليغيّرها لاحقاً</small></label>${limFields(null)}
      <label class="row" style="padding-inline:0"><span class="row-tx"><b>صلاحية ديسكورد</b></span><span class="switch"><input type="checkbox" name="dc"><i></i></span></label>`,
    actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: 'إنشاء', kind: 'pri', handler: async ({ root }) => {
      await post('/api/admin/users', { username: $('[name=un]', root).value.trim(), display: $('[name=dn]', root).value.trim(), password: $('[name=pw]', root).value, can_discord: $('[name=dc]', root).checked, ...readLims(root) });
      ok('أُنشئ الحساب'); reload();
    } }] });
}

async function details(u, reload) {
  let d; try { d = await api('/api/admin/users/' + u.id + '/details'); } catch (e) { return bad(e); }
  const sec = (k, icon, t, list, line) => list && list.length ? html`<div class="group-title">${ic(icon)} ${t} (${list.length})</div><div class="group">${list.slice(0, 30).map(line)}</div>` : '';
  const ln = (k, x, name, sub, st) => html`<div class="row" style="min-height:50px"><span class="pi sm ${k}">${ic(k)}</span><span class="row-tx"><b class="clip">${name}</b><small class="clip ltr" style="text-align:start">${sub}</small></span><span class="row-end">${st}</span></div>`;
  const onOff = x => x.enabled ? html`<span class="tag ok">تعمل</span>` : html`<span class="tag">موقوفة</span>`;
  const me = u.username === S.me.user.username;
  await sheet({ title: u.display || u.username, sub: '@' + u.username, size: 'wide',
    body: html`<div class="hstack" style="margin-bottom:12px">${u.role === 'owner' ? html`<span class="tag violet">إدارة</span>` : html`<span class="tag">مستخدم</span>`}${u.banned ? html`<span class="tag bad">محظور</span>` : html`<span class="tag ok">نشط</span>`}${u.linked_tg_id ? html`<span class="tag ac">${ic('tg')} ${u.linked_tg_username || u.linked_tg_id}</span>` : html`<span class="tag">تيليجرام غير مربوط</span>`}${u.is_member ? html`<span class="tag ok">عضو القناة</span>` : ''}${u.can_discord ? html`<span class="tag">ديسكورد</span>` : ''}</div>
      <dl class="kv card pad"><dt>أنشئ</dt><dd>${date(u.created)}</dd><dt>آخر دخول</dt><dd>${u.last_login ? ago(u.last_login) : '—'}</dd><dt>جلسات نشطة</dt><dd>${num(d.sessions)}</dd><dt>التنبيهات</dt><dd>${num(d.notifs_count)}</dd>
        <dt>الحدود</dt><dd>كيك ${u.lim_kick ?? 'افتراضي'}  يوتيوب ${u.lim_yt ?? 'افتراضي'}  تيليجرام ${u.lim_tg ?? 'افتراضي'}  X ${u.lim_tw ?? 'افتراضي'}</dd></dl>
      ${sec('kick', 'kick', 'كيك', d.kick, x => ln('kick', x, x.name || x.slug, '@' + x.slug, x.live ? html`<span class="tag air">مباشر</span>` : onOff(x)))}
      ${sec('yt', 'yt', 'يوتيوب', d.yt, x => ln('yt', x, x.name, x.channel_id, onOff(x)))}
      ${sec('tw', 'tw', 'X', d.tw, x => ln('tw', x, x.name || x.username, '@' + x.username, onOff(x)))}
      ${sec('tt', 'tt', 'تيك توك', d.tt, x => ln('tt', x, x.name || x.slug, '@' + x.slug, x.live ? html`<span class="tag air">مباشر</span>` : onOff(x)))}
      ${sec('tg', 'tg', 'تيليجرام', d.tg, x => ln('tg', x, x.name, x.username || x.chat_id, x.verified ? html`<span class="tag ok">موثّقة</span>` : ''))}
      ${d.feed_subs && d.feed_subs.length ? html`<div class="group-title">${ic('dc')} اشتراكات ديسكورد</div><div class="group">${d.feed_subs.map(s => html`<div class="row" style="min-height:48px"><span class="pi sm dc">${ic('hash')}</span><span class="row-tx"><b>${s.channel_name || s.feed_id}</b><small>${ic('tg')} ${s.tg_name || s.tg_channel_id}</small></span></div>`)}</div>` : ''}`,
    actions: [{ label: 'إجراءات', kind: '', icon: 'more', handler: () => { setTimeout(() => userMenu(u, me, reload), 50); return true; } }, { label: 'تعديل', kind: 'pri', icon: 'edit', handler: () => { setTimeout(() => editUser(u, reload), 50); return true; } }] });
}

function userMenu(u, me, reload) {
  const P = '/api/admin/users/' + u.id;
  const go = async (body, msg) => { try { await patch(P, body); ok(msg); reload(); } catch (e) { bad(e); } };
  menu([
    !me && u.role !== 'owner' && { icon: u.banned ? 'check' : 'lock', label: u.banned ? 'رفع الحظر' : 'حظر الحساب', fn: async () => { if (u.banned || await confirm('لن يستطيع الدخول، وتتوقف جلساته فوراً.', { title: 'حظر @' + u.username + '؟', ok: 'حظر', danger: true })) go({ banned: !u.banned }, u.banned ? 'رُفع الحظر' : 'حُظر الحساب'); } },
    { icon: 'gift', label: u.can_discord ? 'سحب صلاحية ديسكورد' : 'منح صلاحية ديسكورد', fn: () => go({ can_discord: !u.can_discord }, 'حُدّثت الصلاحية') },
    !me && { icon: 'crown', label: u.role === 'owner' ? 'إزالة من الإدارة' : 'ترقية للإدارة', fn: async () => { if (await confirm(u.role === 'owner' ? 'سيفقد الوصول للوحة الإدارة.' : 'سيحصل على كل صلاحيات الإدارة.', { title: 'تأكيد', danger: u.role !== 'owner' })) go({ role: u.role === 'owner' ? 'user' : 'owner' }, 'حُدّث الدور'); } },
    { icon: 'logout', label: 'تسجيل خروجه من كل الأجهزة', fn: () => go({ logout: true }, 'أنهينا جلساته') },
    '-',
    !me && u.role !== 'owner' && { icon: 'trash', label: 'حذف الحساب وكل قنواته', danger: true, fn: async () => { if (!await confirm('سيُحذف @' + u.username + ' مع كل قنواته وتنبيهاته نهائياً.', { title: 'حذف المستخدم؟', ok: 'حذف نهائياً', danger: true })) return; try { await del(P); ok('حُذف الحساب'); reload(); } catch (e) { bad(e); } } },
  ], { title: '@' + u.username });
}

function editUser(u, reload) {
  return sheet({ title: 'تعديل @' + u.username, size: 'wide',
    body: html`<label class="field"><span>الاسم الظاهر</span><input name="dn" value="${u.display || ''}"></label>
      <label class="field"><span>كلمة مرور جديدة (اختياري)</span><input name="pw" type="text" class="ltr" autocomplete="off" placeholder="اتركها فارغة للإبقاء"></label>${limFields(u)}`,
    actions: [{ label: 'إلغاء', kind: 'ghost', value: null }, { label: 'حفظ', kind: 'pri', handler: async ({ root }) => {
      const pw = $('[name=pw]', root).value; if (pw && pw.length < 6) { toast('كلمة المرور 6 أحرف على الأقل', 'bad'); return false; }
      await patch('/api/admin/users/' + u.id, { display: $('[name=dn]', root).value.trim(), password: pw, ...readLims(root) }); ok('حُفظت التعديلات'); reload();
    } }] });
}
