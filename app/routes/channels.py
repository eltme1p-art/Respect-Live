"""القنوات: كيك، يوتيوب، X، تيك توك، تيليجرام."""
import html as htmllib
import json
import sqlite3

from .. import config as C
from ..db import q, q1, run, val, tx, cfg, placeholders, now
from ..http import api, fail, ids_list
from ..security import rate_ok, maintenance_blocks
from ..services import sources as S
from ..services import telegram as tg
from ..services.extras import check_limit, limit_info, get_user_limits
from ..services.images import cache_remote_image, localize_rec

TITLES = {"kick": "كيك", "yt": "يوتيوب", "tw": "X", "tt": "تيك توك", "tg": "تيليجرام"}


def _kind(req, allow_tg=True):
    k = req.p("kind")
    if k not in C.KIND_TABLE or (k == "tg" and not allow_tg):
        fail(404, "نوع غير معروف")
    return k


def _own_row(req, kind, cid):
    row = q1("SELECT * FROM " + C.KIND_TABLE[kind] + " WHERE id=?", (cid,))
    if not row:
        fail(404, "غير موجود")
    if not req.owner and row["added_by"] != req.username:
        fail(403, "غير مصرح")
    return row


@api("/api/guest-preview")
async def guest_preview(req):
    if cfg("guest_mode", "1") != "1":
        fail(403, "وضع الزائر معطل")
    counts = {k: val("SELECT COUNT(*) FROM " + t + " WHERE enabled=1", (), 0) for k, t in C.KIND_TABLE.items()}
    live = q("SELECT slug,name,avatar,title,viewers,thumb FROM kick_channels WHERE live=1 AND enabled=1 GROUP BY slug ORDER BY viewers DESC LIMIT 6")
    return {"counts": counts, "live": live}


@api("/api/home-stats", auth="user")
async def home_stats(req):
    un = req.username
    my = {k: val("SELECT COUNT(*) FROM " + t + " WHERE added_by=?", (un,), 0) for k, t in C.KIND_TABLE.items()}
    my["feeds"] = val("SELECT COUNT(*) FROM feed_subs WHERE username=? AND enabled=1", (un,), 0)
    my["live"] = val("SELECT COUNT(*) FROM kick_channels WHERE added_by=? AND live=1 AND enabled=1", (un,), 0) + \
        val("SELECT COUNT(*) FROM tt_channels WHERE added_by=? AND live=1 AND enabled=1", (un,), 0)
    my["videos"] = val("SELECT COUNT(*) FROM recent_videos WHERE added_by=?", (un,), 0)
    my["sent_today"] = val("SELECT COUNT(*) FROM tg_sent_log l JOIN tg_channels t ON t.id=l.tg_id WHERE t.added_by=? AND l.ts>? AND l.ok=1", (un, now() - 86400), 0)
    g = {"users": val("SELECT COUNT(*) FROM users WHERE active=1 AND banned=0", (), 0),
         "total_live": val("SELECT COUNT(DISTINCT slug) FROM kick_channels WHERE live=1 AND enabled=1", (), 0)}
    # البث المباشر: قنواتي أولاً ثم الأكثر مشاهدة
    mine_live = q("SELECT slug,name,avatar,banner,thumb,title,viewers,'kick' kind FROM kick_channels WHERE added_by=? AND live=1 AND enabled=1 "
                  "UNION ALL SELECT slug,name,avatar,banner,thumb,title,viewers,'tt' kind FROM tt_channels WHERE added_by=? AND live=1 AND enabled=1 "
                  "ORDER BY viewers DESC LIMIT 12", (un, un))
    top_live = q("SELECT slug,name,avatar,banner,thumb,title,viewers,'kick' kind FROM kick_channels WHERE live=1 AND enabled=1 GROUP BY slug ORDER BY viewers DESC LIMIT 6")
    seen = {x["slug"] for x in mine_live}
    live_now = mine_live + [x for x in top_live if x["slug"] not in seen]
    vids = q("SELECT video_id,ch_name,title,thumb,url,ts FROM recent_videos WHERE added_by=? ORDER BY ts DESC LIMIT 8", (un,))
    recent = q("SELECT l.source,l.source_name,l.text,l.ok,l.ts FROM tg_sent_log l JOIN tg_channels t ON t.id=l.tg_id WHERE t.added_by=? ORDER BY l.id DESC LIMIT 6", (un,))
    return {"my": my, "global": g, "live_now": live_now[:12], "videos": vids, "recent": recent}


@api("/api/channels/{kind}", auth="user")
async def list_channels(req):
    kind = _kind(req)
    t = C.KIND_TABLE[kind]
    if req.owner and req.query.get("mine") != "1":
        rows = q("SELECT * FROM " + t + " ORDER BY id DESC")
    else:
        rows = q("SELECT * FROM " + t + " WHERE added_by=? ORDER BY id DESC", (req.username,))
    return {"rows": rows, "limits": limit_info(req.username, kind, req.user["role"])}


@api("/api/channels/{kind}/suggestions", auth="user")
async def channel_suggestions(req):
    kind = _kind(req)
    ic, t = C.KIND_IDCOL[kind], C.KIND_TABLE[kind]
    mine = {str(r["v"]).lower() for r in q("SELECT " + ic + " v FROM " + t + " WHERE added_by=?", (req.username,))}
    rows = q("SELECT * FROM default_channels WHERE kind=? AND enabled=1 ORDER BY id DESC", (kind,))
    return {"rows": [r for r in rows if str(r["identifier"]).lower() not in mine]}


def _insert(c, kind, username, rec, msg="", btn="", filters=""):
    t = now()
    if kind in ("kick", "tt"):
        c.execute("INSERT INTO " + C.KIND_TABLE[kind] + "(slug,name,avatar,banner,msg,btn_text,enabled,auto_send,live,title,viewers,thumb,last_check,added_by,created) VALUES(?,?,?,?,?,?,1,1,?,?,?,?,?,?,?)",
                  (rec["slug"], rec["name"], rec["avatar"], rec.get("banner", ""), msg[:1500], btn[:60], 1 if rec["live"] else 0, rec["title"], rec["viewers"] or 0, rec["thumb"],
                   t if kind == "kick" else 0, username, t))
    elif kind == "yt":
        c.execute("INSERT INTO yt_channels(channel_id,handle,name,avatar,banner,msg,btn_text,enabled,auto_send,last_video,last_check,added_by,created) VALUES(?,?,?,?,?,?,?,1,1,?,?,?,?)",
                  (rec["channel_id"], rec.get("handle", ""), rec["name"], rec["avatar"], rec["banner"], msg[:1500], btn[:60], rec["last_video"], t, username, t))
    elif kind == "tw":
        c.execute("INSERT INTO tw_channels(username,user_id,name,avatar,banner,msg,btn_text,filters,enabled,auto_send,last_tweet,last_check,added_by,created) VALUES(?,?,?,?,?,?,?,?,1,1,?,?,?,?)",
                  (rec["username"], rec["user_id"], rec["name"], rec["avatar"], rec["banner"], msg[:1500], btn[:60], filters, rec["last_tweet"], t, username, t))


def _limit_err(req, kind):
    i = limit_info(req.username, kind, req.user["role"])
    fail(400, "وصلت الحد (" + str(i["limit"]) + ")")


@api("/api/channels/{kind}", "POST", auth="user")
async def add_channel(req):
    kind = req.p("kind")
    if maintenance_blocks(req.user):
        fail(503, "الموقع في صيانة — لا يمكن الإضافة حالياً")
    if not rate_ok("add:" + req.username, C.MAX_PER_MIN_CH):
        fail(429, "عدد كبير، انتظر قليلاً")
    if kind == "tg":
        fail(400, "استخدم خطوات التوثيق")
    if kind not in ("kick", "yt", "tw", "tt"):
        fail(404, "نوع غير معروف")
    b = await req.json()
    warn = ""
    msg, btn = str(b.get("msg", "") or ""), str(b.get("btn_text", "") or "")
    custom_name = str(b.get("name") or "").strip()[:80]
    role = req.user["role"]
    if kind == "kick":
        slug = S.norm_kick(b.get("slug") or b.get("input") or "")
        if not slug:
            fail(400, "اسم غير صالح")
        if S.user_has("kick", slug, req.username):
            fail(409, "مضافة لديك مسبقاً")
        if not check_limit(req.username, "kick", role):
            _limit_err(req, kind)
        from_sug = bool(S.find_default("kick", slug))
        rec = await S.kick_record(slug)
        rec["slug"] = slug
    elif kind == "tt":
        if cfg("tiktok_enabled", "1") != "1":
            fail(400, "ميزة تيك توك معطلة حالياً")
        slug = S.norm_tt(b.get("slug") or b.get("input") or "")
        if not slug:
            fail(400, "اسم حساب تيك توك غير صالح")
        if S.user_has("tt", slug, req.username):
            fail(409, "مضافة لديك مسبقاً")
        if not check_limit(req.username, "tt", role):
            _limit_err(req, kind)
        from_sug = bool(S.find_default("tt", slug))
        rec, w = await S.tt_record(slug)
        rec["slug"] = slug
        if w:
            warn = "تعذّر جلب بيانات الحساب الآن (قد يحجب تيك توك الطلبات) — ستُحدَّث تلقائياً لاحقاً"
    elif kind == "yt":
        rec = await S.yt_record(b.get("channel_id") or b.get("input") or "")
        if not rec:
            fail(400, "تعذّر التعرف على القناة — جرّب @handle أو رابط القناة")
        if S.user_has("yt", rec["channel_id"], req.username):
            fail(409, "مضافة لديك مسبقاً")
        if not check_limit(req.username, "yt", role):
            _limit_err(req, kind)
        from_sug = bool(S.find_default("yt", rec["channel_id"]))
    else:
        if not S.tw_available():
            fail(400, "ميزة X غير مفعّلة حالياً — لم تضف الإدارة مفتاح API بعد")
        uname = S.norm_tw(b.get("username") or b.get("input") or "")
        if not uname:
            fail(400, "اسم حساب X غير صالح")
        if S.user_has("tw", uname, req.username):
            fail(409, "مضافة لديك مسبقاً")
        if not check_limit(req.username, "tw", role):
            _limit_err(req, kind)
        from_sug = bool(S.find_default("tw", uname.lower()))
        rec, err = await S.tw_record(uname)
        if not rec:
            fail(400, err or "تعذّر التحقق من الحساب")
    if custom_name:
        rec["name"] = custom_name
    rec = await localize_rec(rec)
    try:
        with tx() as c:
            _insert(c, kind, req.username, rec, msg, btn, json.dumps(S.parse_tw_filters(b.get("filters"))) if kind == "tw" else "")
    except sqlite3.IntegrityError:
        fail(409, "مضافة لديك مسبقاً")
    if not C.TELEGRAM_TOKEN:
        warn = "توكن تيليجرام غير مضبوط — لن تُرسل تنبيهات"
    return {"ok": True, "warn": warn, "from_suggestion": from_sug, "name": rec.get("name", "")}


@api("/api/channels/{kind}/bulk-add", "POST", auth="user")
async def bulk_add(req):
    kind = _kind(req, allow_tg=False)
    if maintenance_blocks(req.user):
        fail(503, "الموقع في صيانة — لا يمكن الإضافة حالياً")
    if kind == "tw" and not S.tw_available():
        fail(400, "ميزة X غير مفعّلة حالياً")
    ids = ids_list((await req.json()).get("ids"), 50)
    if not ids:
        fail(400, "لا توجد قنوات")
    owner = req.owner
    info = limit_info(req.username, kind, req.user["role"])
    if not owner and info["remaining"] < len(ids):
        fail(400, "المتبقي " + str(info["remaining"]) + " فقط")
    rows = q("SELECT * FROM default_channels WHERE id IN (" + placeholders(len(ids)) + ") AND kind=? AND enabled=1", (*ids, kind))
    if not rows:
        fail(404, "لا توجد قنوات")
    added = failed = 0
    errors = []
    remaining = 9999 if owner else info["remaining"]
    for row in rows:
        if remaining <= 0:
            errors.append(row["name"] + ": وصلت الحد")
            failed += 1
            continue
        try:
            ident = row["identifier"]
            if S.user_has(kind, ident, req.username):
                failed += 1
                errors.append(row["name"] + ": مضافة مسبقاً")
                continue
            if kind == "kick":
                rec = await S.kick_record(ident)
                rec["slug"] = ident
            elif kind == "tt":
                rec, _ = await S.tt_record(ident)
                rec["slug"] = ident
            elif kind == "yt":
                rec = await S.yt_record(ident)
                if not rec:
                    failed += 1
                    errors.append(row["name"] + ": تعذّر")
                    continue
            else:
                rec, err = await S.tw_record(ident)
                if not rec:
                    failed += 1
                    errors.append(row["name"] + ": " + (err or "تعذّر"))
                    continue
            rec["name"] = rec.get("name") or row["name"] or ident
            rec["avatar"] = rec.get("avatar") or row["avatar"] or ""
            rec = await localize_rec(rec)
            with tx() as c:
                _insert(c, kind, req.username, rec)
            added += 1
            remaining -= 1
        except Exception as e:
            failed += 1
            errors.append(row["name"] + ": " + str(e)[:60])
    return {"ok": True, "added": added, "failed": failed, "errors": errors}


@api("/api/channels/{kind}/bulk", "POST", auth="user")
async def bulk_action(req):
    """إجراءات جماعية (جديد): إيقاف/تفعيل/إسكات/حذف لعدة قنوات دفعة واحدة"""
    kind = _kind(req)
    b = await req.json()
    ids = ids_list(b.get("ids"), 500)
    act = str(b.get("action") or "")
    if not ids:
        fail(400, "لم تحدد قنوات")
    t = C.KIND_TABLE[kind]
    own = "" if req.owner else " AND added_by=?"
    params = tuple(ids) + (() if req.owner else (req.username,))
    where = " WHERE id IN (" + placeholders(len(ids)) + ")" + own
    if act in ("enable", "disable"):
        n = run("UPDATE " + t + " SET enabled=?" + where, (1 if act == "enable" else 0,) + params).rowcount
    elif act in ("mute", "unmute"):
        if kind == "tg":
            fail(400, "غير متاح لتيليجرام")
        n = run("UPDATE " + t + " SET auto_send=?" + where, (0 if act == "mute" else 1,) + params).rowcount
    elif act == "delete":
        with tx() as c:
            if kind == "tg":
                mine = [r["id"] for r in q("SELECT id FROM tg_channels" + where, params)]
                if mine:
                    ph = placeholders(len(mine))
                    c.execute("DELETE FROM feed_subs WHERE tg_channel_id IN (" + ph + ")", tuple(mine))
                    c.execute("DELETE FROM tg_sent_log WHERE tg_id IN (" + ph + ")", tuple(mine))
            n = c.execute("DELETE FROM " + t + where, params).rowcount
    else:
        fail(400, "إجراء غير معروف")
    return {"ok": True, "affected": n}


@api("/api/channels/{kind}/{cid:int}", "DELETE", auth="user")
async def del_channel(req):
    kind = _kind(req)
    cid = req.p("cid")
    _own_row(req, kind, cid)
    with tx() as c:
        if kind == "tg":
            c.execute("DELETE FROM feed_subs WHERE tg_channel_id=?", (cid,))
            c.execute("DELETE FROM tg_sent_log WHERE tg_id=?", (cid,))
        c.execute("DELETE FROM " + C.KIND_TABLE[kind] + " WHERE id=?", (cid,))
    return {"ok": True}


@api("/api/channels/{kind}/{cid:int}", "PATCH", auth="user")
async def patch_channel(req):
    kind = _kind(req)
    cid = req.p("cid")
    _own_row(req, kind, cid)
    b = await req.json()
    sets, vals = [], []
    if "enabled" in b:
        sets.append("enabled=?"); vals.append(1 if b["enabled"] else 0)
    if kind != "tg":
        if "auto_send" in b:
            sets.append("auto_send=?"); vals.append(1 if b["auto_send"] else 0)
        if "msg" in b:
            sets.append("msg=?"); vals.append(str(b["msg"])[:1500])
        if "btn_text" in b:
            sets.append("btn_text=?"); vals.append(str(b["btn_text"])[:60])
    if "name" in b and str(b["name"]).strip():
        sets.append("name=?"); vals.append(str(b["name"]).strip()[:80])
    if "avatar" in b and kind == "tg":
        sets.append("avatar=?"); vals.append(str(b["avatar"])[:500])
    if "banner" in b and kind in ("yt", "tg"):
        sets.append("banner=?"); vals.append(str(b["banner"])[:500])
    if "filters" in b and kind == "tw":
        sets.append("filters=?"); vals.append(json.dumps(S.parse_tw_filters(b["filters"])))
    if sets:
        vals.append(cid)
        run("UPDATE " + C.KIND_TABLE[kind] + " SET " + ", ".join(sets) + " WHERE id=?", vals)
    return {"ok": True}


@api("/api/channels/{kind}/{cid:int}/refresh", "POST", auth="user")
async def refresh_channel(req):
    kind = _kind(req)
    cid = req.p("cid")
    row = _own_row(req, kind, cid)
    if not rate_ok("refresh:" + req.username, 12):
        fail(429, "تحديثات كثيرة، انتظر دقيقة")
    if kind == "kick":
        info = await S.kick_fetch(row["slug"])
        if not info:
            fail(400, "تعذّر الجلب من كيك حالياً — حاول بعد قليل")
        av = await cache_remote_image(info["avatar"]) if info["avatar"] else row["avatar"]
        bn = await cache_remote_image(info["banner"]) if info["banner"] else row["banner"]
        run("UPDATE kick_channels SET name=?,avatar=?,banner=?,live=?,title=?,viewers=?,thumb=? WHERE id=?",
            (info["name"] or row["name"], av, bn, 1 if info["live"] else 0, info["title"], info["viewers"], info["thumb"], cid))
    elif kind == "tt":
        info = await S.tt_fetch(row["slug"])
        if not info:
            fail(400, "تعذّر الجلب من تيك توك حالياً — حاول لاحقاً")
        av = await cache_remote_image(info["avatar"]) if info["avatar"] else row["avatar"]
        run("UPDATE tt_channels SET name=?,avatar=? WHERE id=?", (info["name"] or row["name"], av, cid))
    elif kind == "tg":
        info = await tg.tg_get_chat_info(row["chat_id"], force=True)
        if not info:
            fail(400, "تعذّر الجلب — تأكد أن البوت مضاف كمشرف")
        run("UPDATE tg_channels SET name=?,username=?,avatar=? WHERE id=?", (info["name"], info["username"] or row["username"], info["avatar"] or row["avatar"], cid))
    elif kind == "yt":
        info = await S.yt_resolve(row["channel_id"])
        if not info:
            fail(400, "تعذّر الجلب")
        av = await cache_remote_image(info.get("avatar") or "") or row["avatar"]
        bn = await cache_remote_image(info.get("banner") or "") or row["banner"]
        run("UPDATE yt_channels SET name=?,avatar=?,banner=?,handle=CASE WHEN handle='' THEN ? ELSE handle END WHERE id=?",
            (info["name"] or row["name"], av, bn, info.get("handle") or "", cid))
    else:
        if not S.tw_available():
            fail(400, "مفتاح X غير مضبوط")
        if not rate_ok("twref:" + req.username, 5):
            fail(429, "عدد كبير من التحديثات، انتظر دقيقة")
        info, err, st = await S.tw_resolve(row["username"])
        if not info:
            fail(400, err or "تعذّر الجلب")
        av = await cache_remote_image(info["avatar"]) if info["avatar"] else row["avatar"]
        bn = await cache_remote_image(info["banner"]) if info["banner"] else row["banner"]
        run("UPDATE tw_channels SET name=?,avatar=?,banner=?,user_id=? WHERE id=?", (info["name"], av, bn, info["user_id"], cid))
    return {"ok": True, "row": q1("SELECT * FROM " + C.KIND_TABLE[kind] + " WHERE id=?", (cid,))}


@api("/api/channels/{kind}/{cid:int}/test", "POST", auth="user")
async def test_channel(req):
    """إرسال تجريبي (جديد): يرسل شكل التنبيه لحسابك الشخصي في تيليجرام فقط — بدون إزعاج قنواتك"""
    kind = _kind(req, allow_tg=False)
    row = _own_row(req, kind, req.p("cid"))
    if not C.TELEGRAM_TOKEN:
        fail(400, "توكن تيليجرام غير مضبوط")
    tid = req.user.get("linked_tg_id")
    if not tid:
        fail(400, "اربط حسابك في تيليجرام أولاً (من صفحة تيليجرام) حتى يصلك الإرسال التجريبي")
    if not rate_ok("test:" + req.username, 4):
        fail(429, "انتظر دقيقة بين التجارب")
    msg_text, msg_img = S.split_msg_img(row["msg"])
    name = row.get("name") or ""
    if kind == "kick":
        url, tpl, btn = "https://kick.com/" + row["slug"], msg_text or cfg("tpl_kick"), row["btn_text"] or cfg("btn_kick", "شاهد البث")
        text = tpl.replace("{name}", name).replace("{title}", row.get("title") or "عنوان البث التجريبي").replace("{url}", url)
        img = msg_img or row.get("banner") or row.get("thumb") or ""
    elif kind == "tt":
        url, tpl, btn = "https://www.tiktok.com/@" + row["slug"] + "/live", msg_text or cfg("tpl_tt"), row["btn_text"] or cfg("btn_tt", "شاهد البث")
        text = tpl.replace("{name}", name).replace("{title}", row.get("title") or "عنوان البث التجريبي").replace("{url}", url)
        img = msg_img or row.get("thumb") or ""
    elif kind == "yt":
        vid = row.get("last_video") or ""
        url = ("https://youtube.com/watch?v=" + vid) if vid else ("https://youtube.com/channel/" + row["channel_id"])
        tpl, btn = msg_text or cfg("tpl_yt"), row["btn_text"] or cfg("btn_yt", "شاهد الفيديو")
        text = tpl.replace("{name}", name).replace("{title}", "عنوان الفيديو التجريبي").replace("{url}", url)
        img = msg_img or (("https://i.ytimg.com/vi/" + vid + "/maxresdefault.jpg") if vid else "")
    else:
        url = "https://x.com/" + row["username"]
        tpl, btn = msg_text or cfg("tpl_tw", "<b>{name}</b>\n\n{text}"), row["btn_text"] or cfg("btn_tw", "عرض التغريدة")
        text = (tpl.replace("{name}", htmllib.escape(name, quote=False)).replace("{username}", row["username"])
                .replace("{text}", "هذا نص تغريدة تجريبية 👋").replace("{url}", url))
        img = msg_img
    ok = await tg.tg_send(tid, "🧪 <b>إرسال تجريبي</b>\n\n" + text, img, btn, url)
    if not ok:
        fail(400, "تعذّر الإرسال — افتح البوت واضغط Start ثم أعد المحاولة")
    return {"ok": True}


@api("/api/channels/tg/{cid:int}/messages", auth="user")
async def tg_messages(req):
    cid = req.p("cid")
    row = q1("SELECT id,name,added_by FROM tg_channels WHERE id=?", (cid,))
    if not row:
        fail(404, "غير موجود")
    if not req.owner and row["added_by"] != req.username:
        fail(403, "غير مصرح")
    return {"name": row["name"], "rows": q("SELECT source,source_name,text,image,url,ok,ts FROM tg_sent_log WHERE tg_id=? ORDER BY id DESC LIMIT 25", (cid,))}
