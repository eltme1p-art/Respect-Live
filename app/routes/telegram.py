"""ربط حساب تيليجرام، توثيق القنوات، والـ webhook."""
import asyncio
import re
import secrets

from .. import config as C
from ..db import q, q1, run, tx, cfg, now
from ..http import api, fail, Json
from ..security import rate_ok, log_sec, maintenance_blocks
from ..services import telegram as tg
from ..services.extras import check_limit, limit_info, add_notif
from ..services.sources import find_default


def default_tg_info(chat_id):
    d = find_default("tg", chat_id)
    if not d:
        return None
    return {"name": d["name"] or d["identifier"], "username": d.get("alias") or "", "avatar": d["avatar"] or "", "chat_id": d["identifier"], "type": "channel"}


# ═══ ربط الحساب (للعضوية) ═══
@api("/api/link-tg/start", "POST", auth="user")
async def link_start(req):
    if not C.TELEGRAM_TOKEN:
        fail(400, "توكن تيليجرام غير مضبوط")
    if not rate_ok("linktg:" + req.username, 8):
        fail(429, "عدد كبير من المحاولات، انتظر دقيقة")
    b = await req.json()
    await tg.tg_bot_id()
    blink = tg.bot_link()
    tg_username = (b.get("tg_username") or "").strip().lstrip("@")[:64]
    t = now()
    if not tg_username:
        if not blink:
            fail(400, "تعذّر معرفة رابط البوت — تأكد من توكن تيليجرام أو أضف رابط البوت من لوحة الإدارة")
        token = secrets.token_urlsafe(12)
        with tx() as c:
            c.execute("DELETE FROM tg_link_codes WHERE site_username=? AND status='pending'", (req.username,))
            cur = c.execute("INSERT INTO tg_link_codes(site_username, tg_user_id, tg_username, tg_first_name, code, status, created, expires, token) VALUES(?,?,?,?,?,'pending',?,?,?)",
                            (req.username, "", "", "", "", t, t + C.LINK_CODE_TTL, token))
            lid = cur.lastrowid
        return {"ok": True, "mode": "deeplink", "link_id": lid, "link": tg.bot_link("link_" + token), "bot_link": blink, "expires": C.LINK_CODE_TTL}
    if not re.match(r"^[A-Za-z][A-Za-z0-9_]{3,31}$", tg_username):
        fail(400, "يوزر تيليجرام غير صالح")
    r = q1("SELECT * FROM tg_bot_users WHERE username=?", (tg_username.lower(),))
    tg_user_id, first_name = (r["tg_id"], r["first_name"] or "") if r else ("", "")
    if not tg_user_id:
        j = await tg.tg_api("getChat", {"chat_id": "@" + tg_username})
        res = j.get("result") if j.get("ok") else None
        if res and res.get("type") == "private":
            tg_user_id, first_name = str(res.get("id", "")), res.get("first_name", "") or ""
    if not tg_user_id:
        fail(404, "البوت لم يتعرّف على هذا اليوزر بعد.\n\nافتح البوت واضغط Start مرة واحدة ثم أعد المحاولة — أو استخدم «الربط التلقائي» وهو الأسهل.", need_start=True, bot_link=blink)
    code = "{:06d}".format(secrets.randbelow(1000000))
    with tx() as c:
        c.execute("DELETE FROM tg_link_codes WHERE site_username=? AND status='pending'", (req.username,))
        lid = c.execute("INSERT INTO tg_link_codes(site_username, tg_user_id, tg_username, tg_first_name, code, status, created, expires, token) VALUES(?,?,?,?,?,'pending',?,?,'')",
                        (req.username, tg_user_id, "@" + tg_username, first_name, code, t, t + C.LINK_CODE_TTL)).lastrowid
    if not await tg.send_link_code_dm(tg_user_id, code):
        run("DELETE FROM tg_link_codes WHERE id=?", (lid,))
        fail(400, "تعذّر إرسال الرسالة — افتح البوت واضغط Start أولاً (ثم تأكد أنك لم تحظره).", need_start=True, bot_link=blink)
    log_sec(req.username, "link_tg_start", "@" + tg_username, req.ip)
    return {"ok": True, "mode": "code", "link_id": lid, "tg_username": "@" + tg_username, "tg_name": first_name}


@api("/api/link-tg/{lid:int}/status", auth="user")
async def link_poll(req):
    row = q1("SELECT status, expires FROM tg_link_codes WHERE id=? AND site_username=?", (req.p("lid"), req.username))
    me = q1("SELECT is_member, linked_tg_id FROM users WHERE username=?", (req.username,)) or {}
    if not row:
        return {"status": "none"}
    st = row["status"]
    if st == "pending" and row["expires"] < now():
        st = "expired"
    return {"status": st, "is_member": bool(me.get("is_member")), "linked": bool(me.get("linked_tg_id"))}


@api("/api/link-tg/{lid:int}/verify", "POST", auth="user")
async def link_verify(req):
    lid = req.p("lid")
    code = ((await req.json()).get("code") or "").strip()
    if not re.match(r"^\d{6}$", code):
        fail(400, "الرمز 6 أرقام")
    if not rate_ok("linkcode:" + req.username, 8):
        fail(429, "محاولات كثيرة، انتظر دقيقة")
    row = q1("SELECT * FROM tg_link_codes WHERE id=? AND site_username=?", (lid, req.username))
    if not row:
        fail(404, "طلب غير موجود")
    if row["status"] != "pending":
        fail(400, "انتهت صلاحية الطلب")
    if row["expires"] < now():
        run("UPDATE tg_link_codes SET status='expired' WHERE id=?", (lid,))
        fail(400, "انتهت المهلة")
    if not secrets.compare_digest(row["code"], code):
        fail(400, "الرمز غير صحيح")
    with tx() as c:
        c.execute("UPDATE users SET linked_tg_id=?, linked_tg_username=?, linked_tg_name=?, member_checked=0 WHERE username=?",
                  (row["tg_user_id"], row["tg_username"], row["tg_first_name"], req.username))
        c.execute("UPDATE tg_link_codes SET status='used' WHERE id=?", (lid,))
    req_ch = cfg("required_channel_id", "").strip()
    is_mem = await tg.tg_check_membership(row["tg_user_id"], req_ch) if req_ch else False
    run("UPDATE users SET is_member=?, member_checked=? WHERE username=?", (1 if is_mem else 0, now(), req.username))
    log_sec(req.username, "link_tg_ok", row["tg_username"], req.ip)
    return {"ok": True, "is_member": is_mem, "message": "✅ تم ربط الحساب بنجاح." + (" 🎁 حصلت على صلاحيات مضاعفة لأنك عضو في القناة!" if is_mem else " ⚠️ أنت لست عضواً في القناة المطلوبة — انضم عبر الرابط لتفعيل الصلاحيات المضاعفة.")}


@api("/api/link-tg/status", auth="user")
async def link_status(req):
    u = req.user
    return {"linked_tg_id": u.get("linked_tg_id", ""), "linked_tg_username": u.get("linked_tg_username", ""), "linked_tg_name": u.get("linked_tg_name", ""),
            "is_member": bool(u.get("is_member", 0)), "required_channel_url": cfg("required_channel_url", ""), "required_channel_name": cfg("required_channel_name", "")}


@api("/api/link-tg/refresh-membership", "POST", auth="user")
async def link_refresh(req):
    if not req.user.get("linked_tg_id"):
        fail(400, "لم تربط حساب تيليجرام بعد")
    req_ch = cfg("required_channel_id", "").strip()
    if not req_ch:
        fail(400, "لم يتم ضبط القناة المطلوبة")
    is_mem = await tg.tg_check_membership(req.user["linked_tg_id"], req_ch)
    run("UPDATE users SET is_member=?, member_checked=? WHERE username=?", (1 if is_mem else 0, now(), req.username))
    return {"ok": True, "is_member": is_mem}


@api("/api/link-tg/unlink", "POST", auth="user")
async def link_unlink(req):
    run("UPDATE users SET linked_tg_id='', linked_tg_username='', linked_tg_name='', is_member=0, member_checked=0 WHERE username=?", (req.username,))
    return {"ok": True}


# ═══ توثيق ملكية القناة ═══
@api("/api/tg/verify/start", "POST", auth="user")
async def verify_start(req):
    if maintenance_blocks(req.user):
        fail(503, "الموقع في صيانة — لا يمكن التوثيق حالياً")
    if not C.TELEGRAM_TOKEN:
        fail(400, "توكن تيليجرام غير مضبوط")
    if not rate_ok("tgv:" + req.username, 5):
        fail(429, "عدد كبير من المحاولات، انتظر دقيقة")
    chat_input = ((await req.json()).get("chat_id") or "").strip()
    chat_id = tg.norm_chat(chat_input)
    if not chat_id:
        if re.search(r"t\.me/(\+|joinchat)", chat_input):
            fail(400, "روابط الدعوة الخاصة غير مدعومة — اكتب رقم القناة (يبدأ بـ -100) أو @يوزر القناة العامة")
        fail(400, "معرّف القناة غير صالح — اكتب @يوزر القناة أو رابط t.me أو الرقم")
    info = await tg.tg_get_chat_info(chat_id) or default_tg_info(chat_id)
    if not info:
        bl = tg.bot_link()
        fail(400, "تعذّر الوصول للقناة.\n\nتأكد من:\n• إضافة البوت كمشرف في القناة" + ((" (" + bl + ")") if bl else "") +
             "\n• كتابة المعرّف بشكل صحيح\n• نشر أي رسالة في القناة أولاً", bot_link=bl)
    if q1("SELECT 1 x FROM tg_channels WHERE chat_id=? AND added_by=?", (info["chat_id"], req.username)):
        fail(409, "أنت أضفت هذه القناة مسبقاً")
    if not check_limit(req.username, "tg", req.user["role"]):
        fail(400, "وصلت الحد (" + str(limit_info(req.username, "tg", req.user["role"])["limit"]) + ")")
    if q1("SELECT id FROM tg_verifications WHERE tg_chat_id=? AND site_username=? AND status IN ('pending','awaiting_admin') AND expires>?", (info["chat_id"], req.username, now())):
        run("UPDATE tg_verifications SET status='cancelled' WHERE tg_chat_id=? AND site_username=? AND status IN ('pending','awaiting_admin')", (info["chat_id"], req.username))
    ok_bot, why = await tg.tg_bot_admin_state(info["chat_id"])
    if not ok_bot:
        fail(400, why, bot_link=tg.bot_link())
    admins, err = await tg.tg_get_full_admins(info["chat_id"])
    if admins is None:
        fail(400, "تعذّر جلب مشرفي القناة.\n" + (err or ""))
    if not admins:
        admins, _ = await tg.tg_get_full_admins(info["chat_id"], strict=False)
    if not admins:
        fail(400, "لا يوجد مشرف بشري يستطيع النشر في القناة — تأكد أن أحد المشرفين يستطيع النشر وأن البوت مشرف")
    t = now()
    vid = run("INSERT INTO tg_verifications(site_username,tg_username,tg_user_id,tg_chat_id,tg_chat_name,tg_chat_avatar,tg_chat_username,status,created,expires) VALUES(?,?,?,?,?,?,?,'awaiting_admin',?,?)",
              (req.username, "", "", info["chat_id"], info["name"], info["avatar"], info.get("username") or "", t, t + C.VERIFY_TTL)).lastrowid
    return {"ok": True, "verify_id": vid, "chat_name": info["name"], "chat_avatar": info["avatar"], "admins": admins, "auto_admin_id": admins[0]["id"], "expires": C.VERIFY_TTL}


@api("/api/tg/verify/{vid:int}/send", "POST", auth="user")
async def verify_send(req):
    vid = req.p("vid")
    admin_id = ((await req.json()).get("admin_id") or "").strip()
    if not admin_id:
        fail(400, "لم يتم اختيار مشرف")
    row = q1("SELECT * FROM tg_verifications WHERE id=? AND site_username=?", (vid, req.username))
    if not row:
        fail(404, "طلب غير موجود")
    if row["status"] not in ("awaiting_admin", "pending"):
        fail(400, "حالة غير صحيحة")
    if row["expires"] < now():
        fail(400, "انتهت المهلة")
    admins, _ = await tg.tg_get_full_admins(row["tg_chat_id"])
    if not admins:
        admins, _ = await tg.tg_get_full_admins(row["tg_chat_id"], strict=False)
    valid = next((a for a in (admins or []) if a["id"] == admin_id), None)
    if not valid:
        fail(400, "هذا المشرف لا يملك صلاحيات كافية")
    run("UPDATE tg_verifications SET tg_user_id=?, tg_username=?, status='pending', expires=? WHERE id=?", (admin_id, valid["username"], now() + C.VERIFY_TTL, vid))
    msg_id = await tg.send_verify_dm(vid, admin_id, req.username, row["tg_chat_name"])
    if not msg_id:
        run("UPDATE tg_verifications SET status='awaiting_admin' WHERE id=?", (vid,))
        bl = tg.bot_link()
        fail(400, "تعذّر الإرسال — المشرف لازم يفتح البوت ويضغط Start أولاً" + ((" (" + bl + ")") if bl else ""), bot_link=bl)
    run("UPDATE tg_verifications SET tg_msg_id=? WHERE id=?", (msg_id, vid))
    return {"ok": True, "admin_name": valid["name"]}


@api("/api/tg/verify/{vid:int}", auth="user")
async def verify_status(req):
    vid = req.p("vid")
    row = q1("SELECT * FROM tg_verifications WHERE id=? AND site_username=?", (vid, req.username))
    if not row:
        fail(404, "غير موجود")
    if row["status"] in ("pending", "awaiting_admin") and row["expires"] < now():
        run("UPDATE tg_verifications SET status='expired' WHERE id=?", (vid,))
        row["status"] = "expired"
    return {"status": row["status"], "chat_name": row["tg_chat_name"], "chat_avatar": row["tg_chat_avatar"], "expires_in": max(0, row["expires"] - now())}


@api("/api/tg/verify/{vid:int}/code", "POST", auth="user")
async def verify_code(req):
    vid = req.p("vid")
    code = ((await req.json()).get("code") or "").strip()
    if not re.match(r"^\d{6}$", code):
        fail(400, "الرمز 6 أرقام")
    if not rate_ok("tgvcode:" + req.username, 8):
        fail(429, "محاولات كثيرة، انتظر دقيقة")
    row = q1("SELECT * FROM tg_verifications WHERE id=? AND site_username=?", (vid, req.username))
    if not row:
        fail(404, "طلب غير موجود")
    if row["status"] == "used":
        fail(400, "مستخدم")
    if row["status"] != "confirmed":
        fail(400, "لم يتم التأكيد من تيليجرام بعد")
    if row["expires"] < now():
        fail(400, "انتهت الصلاحية")
    if not secrets.compare_digest(row["code"] or "", code):
        fail(400, "رمز خاطئ")
    if q1("SELECT 1 x FROM tg_channels WHERE chat_id=? AND added_by=?", (row["tg_chat_id"], req.username)):
        fail(409, "مضافة مسبقاً")
    with tx() as c:
        c.execute("INSERT INTO tg_channels(chat_id,username,name,avatar,banner,enabled,verified,owner_tg_id,owner_tg_username,added_by,created) VALUES(?,?,?,?,?,1,1,?,?,?,?)",
                  (row["tg_chat_id"], row.get("tg_chat_username") or "", row["tg_chat_name"], row["tg_chat_avatar"], "", row["tg_user_id"], row["tg_username"], req.username, now()))
        c.execute("UPDATE tg_verifications SET status='used' WHERE id=?", (vid,))
    log_sec(req.username, "tg_verify_ok", row["tg_chat_id"], req.ip)
    try:
        tpl = cfg("tpl_tg_success") or "✅ <b>تم الربط بنجاح</b>\n\nالقناة: <b>{chat_name}</b>\nالمستخدم: <code>{site_user}</code>"
        if row["tg_user_id"]:
            await tg.tg_api("sendMessage", {"chat_id": row["tg_user_id"], "parse_mode": "HTML",
                                            "text": tpl.replace("{chat_name}", row["tg_chat_name"] or "").replace("{site_user}", req.username)})
        add_notif(req.username, "تم ربط القناة", "تم ربط قناة " + (row["tg_chat_name"] or "") + " بنجاح بحسابك", "", "", "", "tg_verify")
    except Exception as e:
        print("[TG success] " + str(e))
    return {"ok": True}


@api("/api/tg/verify/{vid:int}/cancel", "POST", auth="user")
async def verify_cancel(req):
    run("UPDATE tg_verifications SET status='cancelled' WHERE id=? AND site_username=? AND status IN ('pending','awaiting_admin')", (req.p("vid"), req.username))
    return {"ok": True}


# ═══ Webhook ═══
@api("/api/telegram/webhook", "POST")
async def webhook(req):
    sec = req.r.headers.get("x-telegram-bot-api-secret-token", "")
    if not secrets.compare_digest(sec, C.TG_WEBHOOK_SECRET):
        return Json({"ok": False}, 401)
    upd = await req.json()
    if upd:
        asyncio.create_task(tg.handle_update(upd))
    return {"ok": True}


@api("/api/telegram/webhook-info", auth="owner")
async def webhook_info(req):
    return await tg.tg_api("getWebhookInfo", {})


@api("/api/telegram/setup-webhook", "POST", auth="owner")
async def setup_webhook(req):
    if not C.PUBLIC_URL:
        fail(400, "PUBLIC_URL غير مضبوط")
    return await tg.set_webhook()


@api("/api/telegram/known-channels", auth="owner")
async def known_channels(req):
    return {"rows": q("SELECT * FROM tg_known_channels ORDER BY last_seen DESC LIMIT 100")}
