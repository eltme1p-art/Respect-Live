"""التسجيل، الدخول، الحساب."""
import re

from .. import config as C
from .. import state
from ..db import q, q1, run, val, cfg, cfg_int, now
from ..http import api, fail, Json
from ..security import (hash_pw, check_pw, new_salt, rate_ok, rate_hit_count, log_sec, new_session, kill_sessions)
from ..services.extras import get_user_limits, usage_counts, push_available, groq_available
from ..services.sources import tw_available
from ..services import discord_bridge as dcb

USER_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")


def _set_cookie(req, resp, tok):
    resp.set_cookie(C.COOKIE_NAME, tok, max_age=C.SESSION_TTL, httponly=True, samesite="lax", secure=req.secure, path="/")


@api("/api/register-status")
async def register_status(req):
    return {"enabled": cfg("registration_enabled", "1") == "1", "site_name": cfg("site_name", C.SITE_NAME),
            "required_channel_url": cfg("required_channel_url", ""), "welcome_title": cfg("signup_welcome_title", "مرحباً بك!"),
            "welcome_text": cfg("signup_welcome_text", "")}


@api("/api/register", "POST")
async def register(req):
    if cfg("registration_enabled", "1") != "1":
        fail(403, "التسجيل مغلق حالياً")
    f = await req.form()
    un = (f.get("username") or "").strip()
    pw = str(f.get("password") or "")
    display = str(f.get("display") or "")
    if not USER_RE.match(un):
        fail(400, "اسم المستخدم 3-30 حرف (a-z 0-9 _ . -)")
    if len(pw) < 6:
        fail(400, "كلمة المرور 6 أحرف على الأقل")
    if len(pw) > 200:
        fail(400, "كلمة المرور طويلة جداً")
    if not rate_ok("reg:" + req.ip, 3):
        fail(429, "عدد كبير من المحاولات، انتظر دقيقة")
    if un.lower() == C.ADMIN_USERNAME.lower():
        fail(400, "هذا الاسم محجوز")
    if q1("SELECT 1 x FROM users WHERE lower(username)=lower(?)", (un,)):
        fail(409, "الاسم مستخدم مسبقاً")
    salt = new_salt()
    dk = max(1, cfg_int("default_lim_kick", 10))
    dy = max(1, cfg_int("default_lim_yt", 5))
    dt = max(0, cfg_int("default_lim_tg", 1))
    run("INSERT INTO users(username,display,pass_hash,salt,role,active,banned,lim_kick,lim_yt,lim_tg,can_discord,created) VALUES(?,?,?,?,'user',1,0,?,?,?,0,?)",
        (un, (display or un)[:60].strip() or un, hash_pw(pw, salt), salt, dk, dy, dt, now()))
    tok = new_session(un)
    log_sec(un, "register_ok", "", req.ip)
    resp = Json({"ok": True, "username": un, "message": "تم إنشاء الحساب! اربط حسابك في تيليجرام وانضم للقناة الرسمية للحصول على صلاحيات مضاعفة."})
    _set_cookie(req, resp, tok)
    return resp


@api("/api/login", "POST")
async def login(req):
    f = await req.form()
    u = str(f.get("u") or f.get("username") or "").strip()[:60]
    p = str(f.get("p") or f.get("password") or "")
    # حماية من التخمين: لكل IP ولكل اسم مستخدم
    if rate_hit_count("lf:" + req.ip) >= 20 or rate_hit_count("lfu:" + u.lower()) >= 10:
        log_sec(u, "login_throttled", "", req.ip)
        fail(429, "محاولات كثيرة خاطئة — انتظر 15 دقيقة ثم حاول")
    row = q1("SELECT * FROM users WHERE username=?", (u,)) or q1("SELECT * FROM users WHERE lower(username)=lower(?)", (u,))

    def bad(reason):
        rate_ok("lf:" + req.ip, 10 ** 6, 900)
        rate_ok("lfu:" + u.lower(), 10 ** 6, 900)
        log_sec(u, "login_fail", reason, req.ip)
        fail(401, "بيانات خاطئة")
    if not row:
        bad("no user")
    if row["banned"]:
        log_sec(u, "login_banned", "", req.ip)
        fail(403, "حساب محظور")
    if not row["active"]:
        fail(403, "حساب معطل")
    if not check_pw(p, row["salt"], row["pass_hash"]):
        bad("bad pass")
    tok = new_session(row["username"])
    run("UPDATE users SET last_login=? WHERE id=?", (now(), row["id"]))
    log_sec(row["username"], "login_ok", (req.r.headers.get("user-agent") or "")[:120], req.ip)
    resp = Json({"ok": True, "user": {"username": row["username"], "role": row["role"]}})
    _set_cookie(req, resp, tok)
    return resp


@api("/api/logout", "POST")
async def logout(req):
    if req.cookie:
        run("DELETE FROM sessions WHERE token=?", (req.cookie,))
    resp = Json({"ok": True})
    resp.delete_cookie(C.COOKIE_NAME, path="/")
    return resp


@api("/api/me", auth="optional")
async def me(req):
    u = req.user
    if not u:
        return Json({"error": "غير مسجل", "auth": False}, 401)
    owner = u["role"] == "owner"
    lim = get_user_limits(u["username"], u["role"])
    usage = usage_counts(u["username"])
    return {
        "user": {"username": u["username"], "display": u["display"], "role": u["role"], "avatar": u.get("avatar", ""), "can_discord": u.get("can_discord", 0) == 1,
                 "linked_tg_id": u.get("linked_tg_id", ""), "linked_tg_username": u.get("linked_tg_username", ""), "linked_tg_name": u.get("linked_tg_name", ""),
                 "is_member": bool(u.get("is_member", 0)), "ui_mode": u.get("ui_mode") or "", "created": u.get("created") or 0},
        "login_anim": cfg("login_anim_enabled", "0") == "1" and bool(cfg("login_anim_code", "").strip()),
        "limits": lim, "usage": usage,
        "tpl_kick": cfg("tpl_kick"), "tpl_yt": cfg("tpl_yt"), "tpl_tw": cfg("tpl_tw"), "tpl_tt": cfg("tpl_tt"), "btn_tw": cfg("btn_tw", "عرض التغريدة"),
        "tpl_discord": cfg("tpl_discord"), "tpl_twitter": cfg("tpl_twitter"), "tpl_youtube_dc": cfg("tpl_youtube_dc"),
        "btn_kick": cfg("btn_kick", "شاهد البث"), "btn_yt": cfg("btn_yt", "شاهد الفيديو"), "btn_tt": cfg("btn_tt", "شاهد البث"),
        "btn_tg": cfg("btn_tg", "عرض القناة"), "btn_discord": cfg("btn_discord", "عرض الروم"),
        "site_name": cfg("site_name", C.SITE_NAME), "site_logo": cfg("site_logo", ""), "site_theme": cfg("site_theme", "default"),
        "has_telegram": bool(C.TELEGRAM_TOKEN), "has_discord": bool(C.DISCORD_TOKEN), "has_push": push_available(), "has_groq": groq_available(),
        "bot_ready": dcb.is_ready() if owner else False, "bot_name_custom": cfg("bot_name_custom", "Respect Live"),
        "bot_invite_url": cfg("bot_invite_url", "") if owner else "", "self_bot_mode": state.DC["self_bot"] if owner else False,
        "has_twitter": tw_available(),
        "required_channel_url": cfg("required_channel_url", ""), "required_channel_name": cfg("required_channel_name", ""),
        "required_channel_msg": cfg("required_channel_msg", ""),
        "maintenance": cfg("maintenance", "0") == "1", "maintenance_title": cfg("maintenance_title", "صيانة مؤقتة"), "maintenance_text": cfg("maintenance_text", ""),
    }


@api("/api/me/account", auth="user")
async def me_account(req):
    un = req.username
    row = q1("SELECT created,last_login FROM users WHERE username=?", (un,)) or {}
    acts = q("SELECT ts,action,ip,detail FROM security_log WHERE username=? AND action IN ('login_ok','login_fail','register_ok','tg_verify_ok','password_change','sessions_revoked','link_tg_ok','login_throttled') ORDER BY id DESC LIMIT 12", (un,))
    for a in acts:
        ip = a.get("ip") or ""
        a["ip"] = (ip.rsplit(".", 1)[0] + ".•") if ip.count(".") == 3 else (ip[:10] + "…" if ip else "")
        a["device"] = _device(a.pop("detail", "") if a["action"] == "login_ok" else "")
    return {"created": row.get("created") or 0, "last_login": row.get("last_login") or 0,
            "sessions": val("SELECT COUNT(*) FROM sessions WHERE username=? AND expires>?", (un, now()), 0),
            "devices": val("SELECT COUNT(*) FROM push_subs WHERE username=?", (un,), 0), "activity": acts}


def _device(ua):
    ua = (ua or "").lower()
    if not ua:
        return ""
    os_ = "iPhone" if "iphone" in ua else "iPad" if "ipad" in ua else "Android" if "android" in ua else "Mac" if "mac os" in ua else "Windows" if "windows" in ua else "Linux" if "linux" in ua else ""
    br = "Edge" if "edg/" in ua else "Chrome" if "chrome" in ua else "Firefox" if "firefox" in ua else "Safari" if "safari" in ua else ""
    return " · ".join(x for x in (os_, br) if x)


@api("/api/me/password", "POST", auth="user")
async def me_password(req):
    if not rate_ok("pwchg:" + req.username, 5):
        fail(429, "عدد كبير من المحاولات، انتظر دقيقة")
    b = await req.json()
    old, new = str(b.get("old") or ""), str(b.get("new") or "")
    if len(new) < 6:
        fail(400, "كلمة المرور الجديدة 6 أحرف على الأقل")
    if len(new) > 200:
        fail(400, "كلمة المرور طويلة جداً")
    row = q1("SELECT salt,pass_hash FROM users WHERE username=?", (req.username,))
    if not row or not check_pw(old, row["salt"], row["pass_hash"]):
        log_sec(req.username, "password_change_fail", "bad old", req.ip)
        fail(400, "كلمة المرور الحالية غير صحيحة")
    salt = new_salt()
    run("UPDATE users SET salt=?, pass_hash=? WHERE username=?", (salt, hash_pw(new, salt), req.username))
    kill_sessions(req.username, except_token=req.cookie or "-")
    log_sec(req.username, "password_change", "", req.ip)
    return {"ok": True}


@api("/api/me/sessions/revoke-others", "POST", auth="user")
async def revoke_others(req):
    n = kill_sessions(req.username, except_token=req.cookie or "-")
    log_sec(req.username, "sessions_revoked", str(n), req.ip)
    return {"ok": True, "revoked": n}


@api("/api/me/profile", "PATCH", auth="user")
async def me_profile(req):
    b = await req.json()
    sets, vals = [], []
    if "display" in b:
        d = str(b["display"]).strip()[:60]
        if d:
            sets.append("display=?")
            vals.append(d)
    if "avatar" in b:
        a = str(b["avatar"]).strip()[:500]
        if a and not (a.startswith("/api/image/") or a.startswith("https://")):
            fail(400, "رابط صورة غير صالح")
        sets.append("avatar=?")
        vals.append(a)
    if sets:
        vals.append(req.username)
        run("UPDATE users SET " + ", ".join(sets) + " WHERE username=?", vals)
    return {"ok": True}


@api("/api/me/ui-mode", "POST", auth="user")
async def me_ui_mode(req):
    m = str((await req.json()).get("mode") or "")
    if m not in ("full", "lite"):
        fail(400, "وضع غير صالح")
    run("UPDATE users SET ui_mode=? WHERE username=?", (m, req.username))
    return {"ok": True, "mode": m}


@api("/api/me/deliveries", auth="user")
async def me_deliveries(req):
    """سجل موحّد لكل ما أُرسل لقنواتي في تيليجرام (جديد)"""
    owner = req.owner and req.query.get("all") == "1"
    src = (req.query.get("source") or "").strip()[:12]
    where = "1=1" if owner else "t.added_by=?"
    params = [] if owner else [req.username]
    if src:
        where += " AND l.source=?"
        params.append(src)
    rows = q("SELECT l.id,l.source,l.source_name,l.text,l.image,l.url,l.ok,l.ts,t.name tg_name,t.avatar tg_avatar,t.id tg_id "
             "FROM tg_sent_log l JOIN tg_channels t ON t.id=l.tg_id WHERE " + where + " ORDER BY l.id DESC LIMIT 80", tuple(params))
    total = len(rows)
    ok = sum(1 for r in rows if r["ok"])
    return {"rows": rows, "total": total, "ok": ok, "failed": total - ok}


@api("/api/login-anim", auth="user")
async def login_anim(req):
    code = cfg("login_anim_code", "")
    on = cfg("login_anim_enabled", "0") == "1" and bool(code.strip())
    return {"enabled": on, "code": code if on else "", "secs": max(1, min(20, cfg_int("login_anim_secs", 3)))}


@api("/api/admin/login-anim", auth="owner")
async def admin_login_anim_get(req):
    return {"enabled": cfg("login_anim_enabled", "0") == "1", "code": cfg("login_anim_code", ""), "secs": max(1, min(20, cfg_int("login_anim_secs", 3)))}


@api("/api/admin/login-anim", "POST", auth="owner")
async def admin_login_anim_set(req):
    from ..db import set_cfg
    b = await req.json()
    if "code" in b:
        code = str(b.get("code") or "")
        if len(code) > 40000:
            fail(400, "الكود أطول من 40000 حرف")
        set_cfg("login_anim_code", code)
    if "enabled" in b:
        set_cfg("login_anim_enabled", "1" if b.get("enabled") else "0")
    if "secs" in b:
        try:
            s = max(1, min(20, int(b.get("secs"))))
        except Exception:
            s = 3
        set_cfg("login_anim_secs", s)
    return {"ok": True}
