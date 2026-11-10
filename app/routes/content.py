"""الأخبار، التنبيهات، الاقتراحات، Push، رفع الصور، الإرسال اليدوي، الذكاء الاصطناعي."""
import asyncio
import re

from starlette.responses import Response

from .. import config as C
from ..db import q, q1, run, val, tx, cfg, placeholders, now
from ..http import api, fail, ids_list, Json
from ..security import rate_ok, maintenance_blocks
from ..services import telegram as tg
from ..services.extras import (push_available, push_send_to_user, groq_available, groq_rewrite, groq_source, add_notif, push_bg)
from ..services.images import sniff_mime, store_image


# ═══ الأخبار ═══
@api("/api/news", auth="optional")
async def news(req):
    rows = q("SELECT * FROM news WHERE enabled=1 ORDER BY id DESC LIMIT 30")
    read_ids = {r["news_id"] for r in q("SELECT news_id FROM news_read WHERE username=?", (req.username,))} if req.user else set()
    for r in rows:
        r["is_read"] = r["id"] in read_ids
    return {"rows": rows, "unread_count": sum(1 for r in rows if not r["is_read"]) if req.user else 0}


@api("/api/news/{nid:int}/read", "POST", auth="user")
async def news_read(req):
    run("INSERT OR REPLACE INTO news_read(username, news_id, ts) VALUES(?,?,?)", (req.username, req.p("nid"), now()))
    return {"ok": True}


@api("/api/news/read-all", "POST", auth="user")
async def news_read_all(req):
    with tx() as c:
        for r in q("SELECT id FROM news WHERE enabled=1"):
            c.execute("INSERT OR REPLACE INTO news_read(username, news_id, ts) VALUES(?,?,?)", (req.username, r["id"], now()))
    return {"ok": True}


@api("/api/admin/news", auth="owner")
async def admin_news(req):
    return {"rows": q("SELECT * FROM news ORDER BY id DESC LIMIT 200")}


@api("/api/admin/news", "POST", auth="owner")
async def admin_news_create(req):
    b = await req.json()
    title = (b.get("title") or "").strip()[:200]
    if not title:
        fail(400, "العنوان مطلوب")
    nid = run("INSERT INTO news(title, body, image, kind, enabled, created) VALUES(?,?,?,?,1,?)",
              (title, (b.get("body") or "").strip()[:4000], (b.get("image") or "").strip()[:500], (b.get("kind") or "news")[:30], now())).lastrowid
    if b.get("push"):
        for u in q("SELECT DISTINCT username FROM push_subs"):
            push_bg(u["username"], title, (b.get("body") or "")[:200], b.get("image") or "", "/news", "news")
    return {"ok": True, "id": nid}


@api("/api/admin/news/{nid:int}", "PATCH", auth="owner")
async def admin_news_patch(req):
    b = await req.json()
    sets, vals = [], []
    for k, lim in (("title", 200), ("body", 4000), ("image", 500), ("kind", 30)):
        if k in b:
            sets.append(k + "=?"); vals.append(str(b[k])[:lim])
    if "enabled" in b:
        sets.append("enabled=?"); vals.append(1 if b["enabled"] else 0)
    if sets:
        vals.append(req.p("nid"))
        run("UPDATE news SET " + ", ".join(sets) + " WHERE id=?", vals)
    return {"ok": True}


@api("/api/admin/news/{nid:int}", "DELETE", auth="owner")
async def admin_news_delete(req):
    with tx() as c:
        c.execute("DELETE FROM news WHERE id=?", (req.p("nid"),))
        c.execute("DELETE FROM news_read WHERE news_id=?", (req.p("nid"),))
    return {"ok": True}


# ═══ التنبيهات ═══
@api("/api/notifs", auth="user")
async def notifs(req):
    unread = val("SELECT COUNT(*) FROM notifs WHERE username=? AND is_read=0", (req.username,), 0)
    if req.query.get("count"):
        return {"unread": unread}
    kind = (req.query.get("kind") or "").strip()[:20]
    if kind:
        rows = q("SELECT * FROM notifs WHERE username=? AND kind=? ORDER BY ts DESC LIMIT 80", (req.username, kind))
    else:
        rows = q("SELECT * FROM notifs WHERE username=? ORDER BY ts DESC LIMIT 80", (req.username,))
    return {"rows": rows, "unread": unread}


@api("/api/notifs/read-all", "POST", auth="user")
async def notifs_read_all(req):
    run("UPDATE notifs SET is_read=1 WHERE username=?", (req.username,))
    return {"ok": True}


@api("/api/notifs/{nid:int}/read", "POST", auth="user")
async def notif_read(req):
    run("UPDATE notifs SET is_read=1 WHERE id=? AND username=?", (req.p("nid"), req.username))
    return {"ok": True}


@api("/api/notifs/{nid:int}", "DELETE", auth="user")
async def notif_delete(req):
    run("DELETE FROM notifs WHERE id=? AND username=?", (req.p("nid"), req.username))
    return {"ok": True}


@api("/api/notifs/clear", "POST", auth="user")
async def notifs_clear(req):
    run("DELETE FROM notifs WHERE username=?", (req.username,))
    return {"ok": True}


# ═══ الاقتراحات ═══
@api("/api/suggestions", "POST", auth="user")
async def suggest(req):
    text = ((await req.json()).get("text") or "").strip()
    if not text:
        fail(400, "النص فارغ")
    if len(text) > 1000:
        fail(400, "الحد 1000 حرف")
    if not rate_ok("sug:" + req.username, 3):
        fail(429, "عدد كبير، انتظر قليلاً")
    if q1("SELECT 1 x FROM suggestions WHERE username=? AND text=? AND ts>?", (req.username, text, now() - 86400)):
        fail(409, "أرسلت نفس الاقتراح مسبقاً — شكراً لك")
    run("INSERT INTO suggestions(username,text,is_read,ts) VALUES(?,?,0,?)", (req.username, text, now()))
    return {"ok": True}


@api("/api/admin/suggestions", auth="owner")
async def admin_sug(req):
    return {"rows": q("SELECT * FROM suggestions ORDER BY ts DESC LIMIT 200"), "unread": val("SELECT COUNT(*) FROM suggestions WHERE is_read=0", (), 0)}


@api("/api/admin/suggestions/{sid:int}", "PATCH", auth="owner")
async def admin_sug_patch(req):
    b = await req.json()
    if "is_read" in b:
        run("UPDATE suggestions SET is_read=? WHERE id=?", (1 if b["is_read"] else 0, req.p("sid")))
    return {"ok": True}


@api("/api/admin/suggestions/{sid:int}", "DELETE", auth="owner")
async def admin_sug_del(req):
    run("DELETE FROM suggestions WHERE id=?", (req.p("sid"),))
    return {"ok": True}


# ═══ Push ═══
@api("/api/push/key")
async def push_key(req):
    if not push_available():
        fail(404, "Push غير مفعّل")
    return {"key": C.VAPID_PUBLIC}


@api("/api/push/subscribe", "POST", auth="user")
async def push_sub(req):
    if not push_available():
        fail(400, "Push غير مفعّل")
    b = await req.json()
    ep, keys = b.get("endpoint") or "", b.get("keys") or {}
    p, a = keys.get("p256dh") or "", keys.get("auth") or ""
    if not ep.startswith("https://") or not p or not a:
        fail(400, "بيانات ناقصة")
    run("INSERT INTO push_subs(username,endpoint,p256dh,auth,ts) VALUES(?,?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET username=excluded.username,p256dh=excluded.p256dh,auth=excluded.auth,ts=excluded.ts",
        (req.username, ep[:600], p[:200], a[:200], now()))
    return {"ok": True}


@api("/api/push/unsubscribe", "POST", auth="user")
async def push_unsub(req):
    run("DELETE FROM push_subs WHERE endpoint=? AND username=?", ((await req.json()).get("endpoint") or "", req.username))
    return {"ok": True}


@api("/api/push/test", "POST", auth="user")
async def push_test(req):
    if not push_available():
        fail(400, "Push غير مفعّل")
    sent = await push_send_to_user(req.username, "تجربة ✅", "الإشعارات تعمل على هذا الجهاز", "", "/notifications", "test")
    if sent == 0:
        fail(404, "لا يوجد اشتراك فعّال على هذا الجهاز")
    return {"ok": True, "sent": sent}


# ═══ الصور ═══
async def _read_upload(req, max_size):
    form = await req.form()
    file = form.get("file")
    if not file or not hasattr(file, "read"):
        fail(400, "لا ملف")
    data = await file.read()
    if len(data) > max_size:
        fail(413, "الصورة أكبر من " + (str(max_size // 1024) + "KB" if max_size < 1024 * 1024 else str(max_size // (1024 * 1024)) + "MB"))
    mime = sniff_mime(data, (getattr(file, "content_type", "") or "").lower())
    if not mime:
        fail(400, "الملف ليس صورة مدعومة (PNG / JPG / WEBP / GIF)")
    return data, mime


@api("/api/upload", "POST", auth="user")
async def upload(req):
    if maintenance_blocks(req.user):
        fail(503, "الموقع في صيانة")
    if not rate_ok("upload:" + req.username, 8):
        fail(429, "رفع كثير، انتظر دقيقة")
    data, mime = await _read_upload(req, C.MAX_IMAGE_SIZE)
    url = store_image(data, mime, req.username)
    return {"ok": True, "id": url.rsplit("/", 1)[-1], "url": url}


_IMG_RE = re.compile(r"^[A-Za-z0-9_-]{10,40}$")


@api("/api/image/{img_id}")
async def get_image(req):
    img_id = req.p("img_id")
    if not _IMG_RE.match(img_id or ""):
        fail(400, "معرّف غير صالح")
    etag = '"' + img_id + '"'
    if req.r.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"etag": etag, "cache-control": "public, max-age=31536000, immutable"})
    row = q1("SELECT mime,data FROM images WHERE id=?", (img_id,))
    if not row:
        fail(404, "غير موجود")
    mime = row["mime"] if row["mime"] in ("image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif", "image/avif") else "application/octet-stream"
    return Response(content=row["data"], media_type=mime, headers={
        "cache-control": "public, max-age=31536000, immutable", "etag": etag,
        "x-content-type-options": "nosniff", "content-security-policy": "default-src 'none'; sandbox"})


# ═══ الإرسال اليدوي ═══
@api("/api/send/prefill", auth="user")
async def send_prefill(req):
    if req.owner:
        tgs = q("SELECT id,name,username,avatar,enabled,added_by FROM tg_channels ORDER BY id DESC")
        users = q("SELECT id,username,display,avatar FROM users WHERE active=1 AND banned=0 ORDER BY username")
    else:
        tgs = q("SELECT id,name,username,avatar,enabled FROM tg_channels WHERE added_by=? ORDER BY id DESC", (req.username,))
        users = []
    return {"tgs": tgs, "users": users, "is_owner": req.owner}


@api("/api/send", "POST", auth="user")
async def send(req):
    if maintenance_blocks(req.user):
        fail(503, "الموقع في صيانة — لا يمكن الإرسال حالياً")
    if not rate_ok("send:" + req.username, 10):
        fail(429, "عدد كبير، انتظر قليلاً")
    b = await req.json()
    text = (b.get("text") or "").strip()[:4000]
    image = (b.get("image") or "").strip()[:500]
    btn_text = (b.get("btn_text") or "").strip()[:60]
    btn_url = (b.get("btn_url") or "").strip()[:2000]
    if btn_url and not btn_url.startswith(("https://", "http://", "tg://")):
        fail(400, "رابط الزر يجب أن يبدأ بـ https://")
    if not text and not image:
        fail(400, "لا يوجد محتوى")
    out = {"tg_sent": 0, "tg_failed": 0, "users": 0}
    tgm = b.get("tg") or {}
    mode, ids = tgm.get("mode", "none"), ids_list(tgm.get("ids"), 200)
    rows = []
    if C.TELEGRAM_TOKEN and mode == "all":
        rows = q("SELECT * FROM tg_channels WHERE enabled=1") if req.owner else q("SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (req.username,))
    elif C.TELEGRAM_TOKEN and mode == "pick" and ids:
        if req.owner:
            rows = q("SELECT * FROM tg_channels WHERE id IN (" + placeholders(len(ids)) + ")", tuple(ids))
        else:
            rows = q("SELECT * FROM tg_channels WHERE added_by=? AND id IN (" + placeholders(len(ids)) + ")", (req.username, *ids))
    res = await tg.tg_deliver(rows, text, image, btn_text, btn_url, "manual", "")
    out["tg_sent"] = sum(1 for v in res.values() if v)
    out["tg_failed"] = sum(1 for v in res.values() if not v)
    um = b.get("users") or {}
    if req.owner and um.get("mode", "none") != "none":
        if um.get("mode") == "all":
            us = q("SELECT username FROM users WHERE active=1 AND banned=0")
        else:
            uids = ids_list(um.get("ids"), 1000)
            us = q("SELECT username FROM users WHERE active=1 AND banned=0 AND id IN (" + placeholders(len(uids)) + ")", tuple(uids)) if uids else []
        title = (b.get("title") or "").strip()[:120] or "رسالة من الإدارة"
        with tx() as c:
            for t in us:
                c.execute("INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) VALUES(?,?,?,?,?,?,'admin',?,0)",
                          (t["username"], title, re.sub(r"<[^>]+>", "", text)[:500], image, btn_text, btn_url, now()))
        for t in us:
            push_bg(t["username"], title, re.sub(r"<[^>]+>", "", text)[:200], image, btn_url or "/notifications", "admin")
        out["users"] = len(us)
    return {"ok": True, "result": out}


# ═══ الذكاء الاصطناعي ═══
@api("/api/ai/status", auth="user")
async def ai_status(req):
    return {"available": groq_available(), "model": cfg("groq_model", "llama-3.3-70b-versatile"), "source": groq_source()}


@api("/api/ai/rewrite", "POST", auth="user")
async def ai_rewrite(req):
    if not rate_ok("ai:" + req.username, 10):
        fail(429, "عدد كبير، انتظر قليلاً")
    if not groq_available():
        fail(400, "Groq غير مفعّل")
    b = await req.json()
    text = (b.get("text") or "").strip()
    if not text:
        fail(400, "لا نص")
    out = await groq_rewrite(text[:4000], str(b.get("prompt") or "")[:2000])
    if not out:
        fail(502, "فشل الاتصال بـ Groq")
    return {"ok": True, "text": out}
