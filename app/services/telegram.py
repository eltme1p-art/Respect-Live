"""تيليجرام: الإرسال، معلومات القنوات، التوثيق، ربط الحسابات، webhook/polling."""
import asyncio
import html as htmllib
import re
import secrets

from .. import config as C
from .. import state
from ..db import q1, run, tx, cfg, now
from ..security import log_sec
from .images import store_image

API = "https://api.telegram.org/bot"
ALLOWED_UPDATES = ["message", "callback_query", "my_chat_member", "channel_post"]


def _url(method):
    return API + C.TELEGRAM_TOKEN + "/" + method


async def tg_api(method, body=None, timeout=15):
    if not C.TELEGRAM_TOKEN:
        return {"ok": False, "description": "no token"}
    try:
        r = await state.http().post(_url(method), json=body or {}, timeout=timeout)
        return r.json()
    except Exception as e:
        print("[TG API] " + method + " " + str(e))
        return {"ok": False, "description": str(e)[:120]}


async def tg_send(chat_id, text, image="", btn="", url=""):
    if not C.TELEGRAM_TOKEN:
        return False
    if image and image.startswith("/"):
        image = (C.PUBLIC_URL + image) if C.PUBLIC_URL else ""
    markup = {"inline_keyboard": [[{"text": btn[:60], "url": url}]]} if (btn and url and url.startswith("http")) else None
    base = {"chat_id": str(chat_id), "parse_mode": "HTML"}
    if markup:
        base["reply_markup"] = markup
    text = text or "."
    if image:
        if len(text) > 1024:
            await tg_api("sendPhoto", {"chat_id": str(chat_id), "photo": image})
            j = await tg_api("sendMessage", {**base, "text": text[:4096]})
            return bool(j.get("ok"))
        j = await tg_api("sendPhoto", {**base, "photo": image, "caption": text})
        if j.get("ok"):
            return True
        print("[TG sendPhoto] failed: " + str(j.get("description", ""))[:200])
    j = await tg_api("sendMessage", {**base, "text": text[:4096], "disable_web_page_preview": False})
    if not j.get("ok") and "parse" in str(j.get("description", "")).lower():
        # HTML غير صالح → نرسل نصاً عادياً بدل الفشل
        plain = htmllib.unescape(re.sub(r"<[^>]+>", "", text))
        j = await tg_api("sendMessage", {"chat_id": str(chat_id), "text": plain[:4096], **({"reply_markup": markup} if markup else {})})
    return bool(j.get("ok"))


def tg_log(tg_id, chat_id, source, source_name, text, image, url, ok):
    try:
        plain = htmllib.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()[:300]
        with tx() as c:
            c.execute("INSERT INTO tg_sent_log(tg_id,chat_id,source,source_name,text,image,url,ok,ts) VALUES(?,?,?,?,?,?,?,?,?)",
                      (tg_id, str(chat_id), (source or "")[:12], (source_name or "")[:80], plain, (image or "")[:500], (url or "")[:500], 1 if ok else 0, now()))
            c.execute("DELETE FROM tg_sent_log WHERE tg_id=? AND id NOT IN (SELECT id FROM tg_sent_log WHERE tg_id=? ORDER BY id DESC LIMIT ?)", (tg_id, tg_id, C.TG_LOG_KEEP))
    except Exception as e:
        print("[TG log] " + str(e))


async def tg_deliver(rows, text, image, btn, url, source, source_name=""):
    """يرسل مرة واحدة لكل chat_id (منع التكرار) ويسجّل في سجل كل قناة. يرجع {chat_id: نجاح}"""
    results = {}
    for tg in rows:
        cid = tg["chat_id"]
        if cid not in results:
            try:
                results[cid] = bool(await tg_send(cid, text, image, btn, url))
            except Exception:
                results[cid] = False
            state.STATS["tg_sent" if results[cid] else "tg_failed"] += 1
        tg_log(tg["id"], cid, source, source_name, text, image, url, results[cid])
    return results


async def tg_save_photo(file_id):
    if not C.TELEGRAM_TOKEN:
        return ""
    j = await tg_api("getFile", {"file_id": file_id})
    if not j.get("ok"):
        return ""
    try:
        r = await state.http().get("https://api.telegram.org/file/bot" + C.TELEGRAM_TOKEN + "/" + j["result"]["file_path"], timeout=20)
        if r.status_code != 200 or len(r.content) > C.MAX_IMAGE_SIZE:
            return ""
        return store_image(r.content, "image/jpeg", "system")
    except Exception:
        return ""


async def cache_chat(chat):
    name = chat.get("title") or chat.get("username") or str(chat.get("id", ""))
    username = ("@" + chat["username"]) if chat.get("username") else ""
    photo = chat.get("photo") or {}
    photo_id = photo.get("big_file_id") or photo.get("small_file_id") or ""
    photo_uid = photo.get("big_file_unique_id") or photo.get("small_file_unique_id") or ""
    cid = str(chat.get("id", ""))
    avatar = ""
    old = q1("SELECT avatar, photo_uid FROM tg_known_channels WHERE chat_id=?", (cid,)) if cid else None
    if photo_id:
        if old and old["avatar"] and photo_uid and old["photo_uid"] == photo_uid:
            avatar = old["avatar"]
        else:
            avatar = await tg_save_photo(photo_id)
        if not avatar and old:
            avatar = old["avatar"] or ""
    elif old:
        avatar = old["avatar"] or ""
    ctype = chat.get("type", "")
    if cid:
        try:
            run("""INSERT INTO tg_known_channels(chat_id, username, name, avatar, type, last_seen, photo_uid) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(chat_id) DO UPDATE SET username=excluded.username, name=excluded.name, avatar=excluded.avatar,
                type=excluded.type, last_seen=excluded.last_seen, photo_uid=excluded.photo_uid""",
                (cid, username, name, avatar, ctype, now(), photo_uid))
        except Exception as e:
            print("[TG cache save] " + str(e))
    return {"name": name, "username": username, "avatar": avatar, "chat_id": cid, "type": ctype}


async def tg_get_chat_info(chat_input, force=False):
    if not C.TELEGRAM_TOKEN:
        return None
    s = str(chat_input or "").strip()
    if not s:
        return None
    uname = numeric = None
    m = re.search(r"t\.me/([A-Za-z0-9_]{5,})", s)
    if m:
        uname = m.group(1)
    elif s.startswith("@"):
        uname = s[1:]
    elif re.match(r"^-?\d+$", s):
        numeric = s
    elif re.match(r"^[A-Za-z0-9_]{5,}$", s):
        uname = s
    if (uname or numeric) and not force:
        row = None
        if uname:
            row = q1("SELECT * FROM tg_known_channels WHERE lower(username)=lower(?) OR lower(username)=lower(?)", ("@" + uname, uname))
        else:
            row = q1("SELECT * FROM tg_known_channels WHERE chat_id=?", (numeric,))
            if not row and numeric.startswith("-100"):
                row = q1("SELECT * FROM tg_known_channels WHERE chat_id=?", (numeric[4:],))
        if row:
            return {"name": row["name"], "username": row["username"], "avatar": row["avatar"], "chat_id": row["chat_id"], "type": row["type"]}
    attempts = []
    if uname:
        attempts += ["@" + uname, uname]
    if numeric:
        attempts.append(numeric)
        if numeric.startswith("-100"):
            attempts += [numeric[4:], "-" + numeric[4:]]
        elif numeric.startswith("-"):
            attempts += ["-100" + numeric[1:], numeric[1:]]
        else:
            attempts += ["-100" + numeric, "-" + numeric]
    seen, last_err = set(), ""
    for a in attempts:
        if a in seen:
            continue
        seen.add(a)
        j = await tg_api("getChat", {"chat_id": a})
        if j.get("ok") and j.get("result"):
            return await cache_chat(j["result"])
        last_err = j.get("description", "")
    print("[TG getChat] '" + s + "' failed: " + str(last_err))
    return None


async def tg_get_full_admins(chat_id, strict=True):
    j = await tg_api("getChatAdministrators", {"chat_id": chat_id})
    if not j.get("ok"):
        return None, j.get("description", "تعذّر جلب المشرفين")
    admins = []
    for m in j.get("result", []):
        status = m.get("status", "")
        user = m.get("user", {})
        if not user or user.get("is_bot"):
            continue
        is_owner = status == "creator"
        ok = is_owner
        if status == "administrator":
            req = (["can_manage_chat", "can_post_messages", "can_edit_messages", "can_delete_messages", "can_invite_users", "can_restrict_members", "can_pin_messages", "can_change_info"]
                   if strict else ["can_post_messages"])
            ok = all(m.get(p, False) for p in req)
        if ok:
            admins.append({"id": str(user["id"]),
                           "name": " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or user.get("username", "") or str(user["id"]),
                           "username": ("@" + user["username"]) if user.get("username") else "", "is_owner": is_owner})
    admins.sort(key=lambda a: (not a["is_owner"], a["name"]))
    return admins, None


async def tg_check_membership(tg_user_id, chat_id):
    if not tg_user_id or not chat_id:
        return False
    j = await tg_api("getChatMember", {"chat_id": chat_id, "user_id": tg_user_id})
    if not j.get("ok"):
        return False
    return j["result"].get("status", "") in ("member", "administrator", "creator")


async def tg_bot_id():
    if state.TG_BOT["id"]:
        return state.TG_BOT["id"]
    j = await tg_api("getMe", {})
    if j.get("ok"):
        state.TG_BOT["id"] = str(j["result"]["id"])
        state.TG_BOT["username"] = j["result"].get("username", "")
        state.TG_BOT["name"] = j["result"].get("first_name", "")
    return state.TG_BOT["id"]


async def tg_bot_admin_state(chat_id):
    bid = await tg_bot_id()
    if not bid:
        return False, "تعذّر الاتصال بتيليجرام، حاول بعد قليل"
    j = await tg_api("getChatMember", {"chat_id": chat_id, "user_id": int(bid)})
    if not j.get("ok"):
        return False, "البوت غير موجود في القناة — أضفه كمشرف أولاً ثم أعد المحاولة"
    r = j.get("result") or {}
    st = r.get("status")
    if st not in ("administrator", "creator"):
        return False, "البوت موجود لكنه ليس مشرفاً — ارفعه إلى مشرف في القناة"
    if st == "administrator" and r.get("can_post_messages") is False:
        return False, "أعطِ البوت صلاحية «نشر الرسائل» في القناة"
    return True, ""


def bot_link(start=""):
    custom = (cfg("bot_tg_link", "") or "").strip().split("?")[0].rstrip("/")
    un = state.TG_BOT.get("username", "")
    base = custom or (("https://t.me/" + un) if un else "")
    if base and start:
        base += "?start=" + start
    return base


def remember_user(frm):
    try:
        if not frm or frm.get("is_bot") or not frm.get("id"):
            return
        run("INSERT INTO tg_bot_users(tg_id,username,first_name,last_seen) VALUES(?,?,?,?) ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, last_seen=excluded.last_seen",
            (str(frm["id"]), (frm.get("username") or "").lower(), frm.get("first_name") or "", now()))
    except Exception as e:
        print("[TG remember] " + str(e))


def norm_chat(s):
    s = (s or "").strip()
    m = re.match(r"(?:https?://)?t\.me/c/(\d{5,})", s)
    if m:
        return "-100" + m.group(1)
    m = re.match(r"(?:https?://)?t\.me/s/([A-Za-z][\w]{3,})", s)
    if m:
        return "@" + m.group(1)
    m = re.match(r"(?:https?://)?t\.me/([A-Za-z][\w]{3,})", s)
    if m:
        return "@" + m.group(1)
    if re.match(r"^-?\d+$", s):
        return s
    if re.match(r"^@[A-Za-z][\w]{3,}$", s):
        return s
    if re.match(r"^[A-Za-z][\w]{3,}$", s):
        return "@" + s
    return None


async def send_verify_dm(vid, tg_user_id, site_username, chat_name):
    tpl = cfg("tpl_tg_verify") or "🔐 <b>طلب توثيق قناة</b>\n\nالمستخدم <code>{site_user}</code> يحاول ربط قناة <b>{chat_name}</b>.\n\n<b>هل أنت من يحاول ذلك؟</b>"
    text = tpl.replace("{site_user}", htmllib.escape(site_username, quote=False)).replace("{chat_name}", htmllib.escape(chat_name or "", quote=False))
    kb = {"inline_keyboard": [[{"text": "✅ نعم، أنا من يحاول", "callback_data": "verify_y:" + str(vid)}], [{"text": "❌ لا، ليس أنا", "callback_data": "verify_n:" + str(vid)}]]}
    j = await tg_api("sendMessage", {"chat_id": tg_user_id, "text": text, "parse_mode": "HTML", "reply_markup": kb})
    return j["result"]["message_id"] if j.get("ok") else 0


async def send_link_code_dm(tg_user_id, code):
    tpl = cfg("tpl_tg_link") or "🔐 <b>ربط حساب</b>\n\nرمز التحقق الخاص بك:\n\n<code>{code}</code>"
    j = await tg_api("sendMessage", {"chat_id": tg_user_id, "text": tpl.replace("{code}", code), "parse_mode": "HTML"})
    return bool(j.get("ok"))


async def _answer(cq, text="", alert=False):
    body = {"callback_query_id": cq["id"]}
    if text:
        body["text"] = text
    if alert:
        body["show_alert"] = True
    await tg_api("answerCallbackQuery", body)


async def handle_update(update):
    try:
        await _handle_update(update)
    except Exception as e:
        print("[TG update] " + repr(e))


async def _handle_update(update):
    for key in ("my_chat_member", "channel_post"):
        obj = update.get(key)
        if obj:
            chat = obj.get("chat", {})
            if chat.get("type") == "channel":
                await cache_chat(chat)
            return
    cq = update.get("callback_query")
    if cq:
        remember_user(cq.get("from"))
        data = cq.get("data", "")
        from_id = str(cq["from"]["id"])
        msg_id = cq["message"]["message_id"]
        chat_id = cq["message"]["chat"]["id"]
        if data.startswith("verify_y:") or data.startswith("verify_n:"):
            try:
                vid = int(data.split(":")[1])
            except Exception:
                return await _answer(cq)
            row = q1("SELECT * FROM tg_verifications WHERE id=?", (vid,))
            if not row:
                return await _answer(cq, "انتهت الجلسة")
            if row["tg_user_id"] and row["tg_user_id"] != from_id:
                return await _answer(cq, "هذا ليس طلبك", True)
            if data.startswith("verify_n:"):
                run("UPDATE tg_verifications SET status='cancelled' WHERE id=?", (vid,))
                await tg_api("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": "❌ <b>تم الإلغاء</b>", "parse_mode": "HTML"})
                return await _answer(cq, "تم الإلغاء")
            if row["status"] != "pending":
                return await _answer(cq, "تم بالفعل")
            if row["expires"] < now():
                run("UPDATE tg_verifications SET status='expired' WHERE id=?", (vid,))
                return await _answer(cq, "انتهت المهلة")
            code = "{:06d}".format(secrets.randbelow(1000000))
            run("UPDATE tg_verifications SET code=?, status='confirmed', expires=? WHERE id=?", (code, now() + 300, vid))
            await tg_api("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "parse_mode": "HTML",
                                              "text": "✅ <b>تم التأكيد</b>\n\nأدخل هذا الرمز في الموقع:\n\n<code>" + code + "</code>\n\n<i>صالح لمدة 5 دقائق</i>"})
            return await _answer(cq, "✅ تم")
        return await _answer(cq)
    msg = update.get("message")
    if msg:
        chat = msg.get("chat", {})
        if chat.get("type") != "private":
            return
        text = (msg.get("text") or "").strip()
        frm = msg.get("from") or {}
        remember_user(frm)
        if text.startswith("/start"):
            payload = text[6:].strip()
            if payload.startswith("link_"):
                return await handle_link_start(frm, chat.get("id"), payload[5:])
            bot_name = cfg("bot_name_custom", "Respect Live")
            welcome = ("👋 أهلاً بك في <b>" + htmllib.escape(bot_name, quote=False) + "</b>!\n\n"
                       "• لربط حسابك: استخدم زر ربط الحساب في الموقع.\n• لتوثيق قناتك: استخدم زر توثيق القناة في الموقع.\n\n"
                       "✅ تم تفعيل البوت لحسابك — الآن تستطيع استلام رموز التحقق.")
            await tg_api("sendMessage", {"chat_id": chat.get("id"), "text": welcome, "parse_mode": "HTML"})


async def handle_link_start(frm, chat_id, token):
    token = re.sub(r"[^A-Za-z0-9_-]", "", token or "")[:64]
    row = q1("SELECT * FROM tg_link_codes WHERE token=? AND status='pending'", (token,)) if token else None
    if not row or row["expires"] < now():
        await tg_api("sendMessage", {"chat_id": chat_id, "parse_mode": "HTML",
                                     "text": "⚠️ رابط الربط منتهي أو غير صالح.\n\nارجع للموقع واضغط «ربط حساب تيليجرام» لإنشاء رابط جديد."})
        return
    tg_id = str(frm.get("id") or chat_id)
    uname = ("@" + frm["username"]) if frm.get("username") else ""
    first = frm.get("first_name") or ""
    with tx() as c:
        c.execute("UPDATE tg_link_codes SET tg_user_id=?, tg_username=?, tg_first_name=?, status='used' WHERE id=?", (tg_id, uname, first, row["id"]))
        c.execute("UPDATE users SET linked_tg_id=?, linked_tg_username=?, linked_tg_name=?, member_checked=0 WHERE username=?", (tg_id, uname, first, row["site_username"]))
    is_mem = False
    req_ch = cfg("required_channel_id", "").strip()
    if req_ch:
        try:
            is_mem = await tg_check_membership(tg_id, req_ch)
        except Exception:
            is_mem = False
    run("UPDATE users SET is_member=?, member_checked=? WHERE username=?", (1 if is_mem else 0, now(), row["site_username"]))
    log_sec(row["site_username"], "link_tg_ok", uname or tg_id, "")
    txt = "✅ <b>تم ربط حسابك بنجاح</b>\n\nحسابك في الموقع: <code>" + htmllib.escape(row["site_username"], quote=False) + "</code>\n"
    if is_mem:
        txt += "\n🎁 أنت عضو في القناة الرسمية — صلاحياتك مضاعفة."
    elif cfg("required_channel_url", ""):
        txt += "\n⚠️ للحصول على صلاحيات مضاعفة انضم للقناة الرسمية:\n" + cfg("required_channel_url", "")
    txt += "\n\nارجع للموقع، سيتحدّث تلقائياً."
    await tg_api("sendMessage", {"chat_id": chat_id, "text": txt, "parse_mode": "HTML", "disable_web_page_preview": True})


_poll_task = None


async def set_webhook():
    url = C.PUBLIC_URL + "/api/telegram/webhook"
    return await tg_api("setWebhook", {"url": url, "allowed_updates": ALLOWED_UPDATES, "secret_token": C.TG_WEBHOOK_SECRET, "drop_pending_updates": False})


async def setup():
    global _poll_task
    if not C.TELEGRAM_TOKEN:
        return
    if C.PUBLIC_URL:
        j = await set_webhook()
        if j.get("ok"):
            print("[TG] ✅ Webhook set: " + C.PUBLIC_URL + "/api/telegram/webhook")
            return
        print("[TG] ❌ Webhook failed: " + str(j))
    else:
        print("[TG] ⚠️ PUBLIC_URL غير موجود — سيستخدم polling")
    await tg_api("deleteWebhook", {})
    _poll_task = asyncio.create_task(poll_loop())


async def poll_loop():
    offset = 0
    print("[TG] Polling started")
    while True:
        try:
            r = await state.http().post(_url("getUpdates"), json={"offset": offset, "timeout": 30, "allowed_updates": ALLOWED_UPDATES}, timeout=40)
            j = r.json()
            if j.get("ok"):
                for u in j["result"]:
                    offset = u["update_id"] + 1
                    asyncio.create_task(handle_update(u))
        except asyncio.CancelledError:
            return
        except Exception as e:
            print("[TG poll] " + str(e)[:120])
            await asyncio.sleep(5)
        await asyncio.sleep(0.5)


def stop():
    if _poll_task:
        _poll_task.cancel()
