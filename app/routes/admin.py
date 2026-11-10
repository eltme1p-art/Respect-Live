"""لوحة الإدارة: الإعدادات، المستخدمون، المقترحة، تويتر، النظام، النسخ الاحتياطي."""
import os
import platform
import re
import sys
import time

from starlette.responses import Response

from .. import config as C
from .. import state
from .. import jobs
from ..db import q, q1, run, val, tx, cfg, cfg_int, set_cfg, backup_bytes, now
from ..http import api, fail, opt_int, truthy
from ..security import hash_pw, new_salt, kill_sessions, log_sec
from ..services import sources as S
from ..services import telegram as tg
from ..services import discord_bridge as dcb
from ..services.extras import groq_available, groq_rewrite, groq_source, push_available
from ..services.images import cache_remote_image, store_image
from .content import _read_upload

GLASS_RANGES = {
    "glass_transparency": (0, 100, 50), "glass_blur": (0, 60, 22), "glass_sat": (100, 300, 185),
    "glass_sheen": (0, 200, 100), "glass_rim": (0, 200, 100), "glass_shadow": (0, 200, 100), "glass_orbs": (0, 100, 55),
    "glass_corner": (0, 200, 100), "glass_radius": (0, 200, 100),
}
GLASS_FLAGS = ["glass_unify_alpha", "glass_unify_blur"]
FEATURES = {"fx_press_zoom": "0", "fx_page_transition": "1", "nav_labels": "1", "pwa_enhance": "1",
            "tiktok_enabled": "1", "feat_haptics": "0", "feat_install_prompt": "1"}
SETTING_KEYS = ["site_name", "site_sub", "hero_title", "hero_accent", "hero_text",
                "tpl_kick", "tpl_yt", "tpl_discord", "tpl_twitter", "tpl_youtube_dc", "tpl_tg_verify", "tpl_tg_success", "tpl_tg_link",
                "btn_kick", "btn_yt", "btn_tg", "btn_discord", "lim_kick", "lim_yt", "lim_tg", "guest_mode", "guest_blur",
                "site_theme", "site_logo", "site_c1", "site_c2", "site_ac", "maintenance", "maintenance_text", "maintenance_title",
                "bot_invite_url", "bot_name_custom", "groq_model", "registration_enabled", "default_lim_kick", "default_lim_yt", "default_lim_tg",
                "bonus_lim_kick", "bonus_lim_yt", "bonus_lim_tg", "required_channel_id", "required_channel_url", "required_channel_name",
                "required_channel_msg", "signup_welcome_title", "signup_welcome_text", "tpl_tw", "btn_tw", "default_lim_tw", "bonus_lim_tw", "lim_tw",
                "ui_mode_prompt", "ui_default_mode", "bot_tg_link", "login_anim_enabled", "login_anim_secs",
                "tpl_tt", "btn_tt", "default_lim_tt", "bonus_lim_tt", "lim_tt", "announce_bar"] + list(GLASS_RANGES) + GLASS_FLAGS + list(FEATURES)
PUBLIC_SETTING_KEYS = {"site_name", "site_sub", "hero_title", "hero_accent", "hero_text", "tpl_kick", "tpl_yt", "tpl_tw", "tpl_tt",
                       "btn_kick", "btn_yt", "btn_tw", "btn_tt", "btn_tg", "btn_discord", "site_theme", "site_logo", "required_channel_url",
                       "required_channel_name", "required_channel_msg"}
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clamp(v, lo, hi, d):
    try:
        n = int(float(str(v).strip()))
    except Exception:
        n = d
    return max(lo, min(hi, n))


def get_glass():
    g = {k[6:]: _clamp(cfg(k, str(d)), lo, hi, d) for k, (lo, hi, d) in GLASS_RANGES.items()}
    g["unify_alpha"] = cfg("glass_unify_alpha", "0") == "1"
    g["unify_blur"] = cfg("glass_unify_blur", "0") == "1"
    return g


def get_features():
    return {k: cfg(k, d) == "1" for k, d in FEATURES.items()}


@api("/api/settings", auth="user")
async def settings_get(req):
    keys = SETTING_KEYS if req.owner else PUBLIC_SETTING_KEYS
    out = {k: cfg(k) for k in keys}
    if req.owner:
        out["groq_configured"] = groq_available()
        out["groq_source"] = groq_source()
    return out


@api("/api/settings", "POST", auth="owner")
async def settings_save(req):
    b = await req.json()
    changed = []
    for k in SETTING_KEYS:
        if k not in b:
            continue
        v = str(b[k] if b[k] is not None else "")[:4000]
        if k in GLASS_RANGES:
            v = str(_clamp(v, *GLASS_RANGES[k]))
        elif k in GLASS_FLAGS or k in FEATURES or k in ("guest_mode", "registration_enabled", "maintenance", "ui_mode_prompt", "login_anim_enabled"):
            v = "1" if truthy(v) else "0"
        elif k == "login_anim_secs":
            v = str(_clamp(v, 1, 20, 3))
        elif k == "ui_default_mode" and v not in ("full", "lite"):
            v = "full"
        elif k in ("site_c1", "site_c2", "site_ac") and v and not HEX_RE.match(v):
            continue
        elif k.startswith(("default_lim_", "bonus_lim_", "lim_")):
            v = str(_clamp(v, 0, 9999, 0))
        set_cfg(k, v)
        changed.append(k)
    if changed:
        log_sec(req.username, "settings_save", ",".join(changed)[:280], req.ip)
    return {"ok": True, "changed": len(changed)}


@api("/api/admin/site-logo", "POST", auth="owner")
async def site_logo(req):
    data, mime = await _read_upload(req, 512000)
    url = store_image(data, mime, "site_logo")
    set_cfg("site_logo", url)
    return {"ok": True, "url": url}


@api("/api/admin/site-logo", "DELETE", auth="owner")
async def site_logo_del(req):
    set_cfg("site_logo", "")
    return {"ok": True}


@api("/api/admin/maintenance", "POST", auth="owner")
async def maintenance(req):
    b = await req.json()
    on = bool(b.get("enabled"))
    set_cfg("maintenance", "1" if on else "0")
    if b.get("title"):
        set_cfg("maintenance_title", str(b["title"])[:200])
    if b.get("text"):
        set_cfg("maintenance_text", str(b["text"])[:500])
    log_sec(req.username, "maintenance_" + ("on" if on else "off"), "", req.ip)
    return {"ok": True, "maintenance": on}


@api("/api/admin/groq", "POST", auth="owner")
async def admin_groq(req):
    b = await req.json()
    if "api_key" in b:
        key = str(b["api_key"]).strip()[:200]
        if key and not key.startswith("gsk_"):
            fail(400, "المفتاح يبدأ بـ gsk_")
        set_cfg("groq_api_key", key)
    if "model" in b:
        set_cfg("groq_model", str(b["model"]).strip()[:100] or "llama-3.3-70b-versatile")
    if b.get("test"):
        out = await groq_rewrite("اختبار الاتصال", "أعد التحية فقط", None)
        return {"ok": bool(out), "test": out or "فشل الاختبار"}
    return {"ok": True, "available": groq_available()}


# ═══ القنوات المقترحة ═══
@api("/api/admin/default-channels", auth="owner")
async def defaults_list(req):
    kind = req.query.get("kind")
    if kind in C.KINDS:
        return {"rows": q("SELECT * FROM default_channels WHERE kind=? ORDER BY id DESC", (kind,))}
    return {"rows": q("SELECT * FROM default_channels ORDER BY kind, id DESC")}


async def _default_from_input(kind, raw, cname=""):
    alias = ""
    if kind == "kick":
        ident = S.norm_kick(raw)
        if not ident:
            return None, "غير صالح"
        info = await S.kick_fetch(ident)
        name, avatar = (cname or info["name"], info["avatar"]) if info else (cname or ident, "")
        alias = ident
    elif kind == "tt":
        ident = S.norm_tt(raw)
        if not ident:
            return None, "غير صالح"
        info = await S.tt_fetch(ident)
        name, avatar = (cname or info["name"], info["avatar"]) if info else (cname or ident, "")
        alias = ident
    elif kind == "yt":
        info = await S.yt_resolve(raw)
        if not info:
            return None, "تعذّر التعرف"
        ident, name, avatar = info["channel_id"], cname or info["name"] or info["channel_id"], info.get("avatar") or ""
        alias = (info.get("handle") or "").lower()
    elif kind == "tw":
        ident = S.norm_tw(raw)
        if not ident:
            return None, "اسم حساب غير صالح"
        name, avatar = cname or ident, ""
        if S.tw_available():
            info, err, st = await S.tw_resolve(ident)
            if info:
                name, avatar, ident = cname or info["name"], info["avatar"], info["username"]
            elif st in (404, 403):
                return None, err
        ident = ident.lower()
        alias = ident
    else:
        ident = tg.norm_chat(raw)
        if not ident:
            return None, "غير صالح"
        info = await tg.tg_get_chat_info(ident) or {}
        name, avatar = cname or info.get("name") or ident, info.get("avatar") or ""
        if info.get("chat_id"):
            ident = info["chat_id"]
        alias = (info.get("username") or (raw if raw.startswith("@") else "")).lower()
    return (ident, name, await cache_remote_image(avatar), alias), ""


def _save_default(kind, ident, name, avatar, alias):
    if q1("SELECT 1 x FROM default_channels WHERE kind=? AND lower(identifier)=lower(?)", (kind, ident)):
        return False
    run("INSERT INTO default_channels(kind,identifier,name,avatar,alias,enabled,created) VALUES(?,?,?,?,?,1,?)", (kind, ident, name, avatar, alias, now()))
    return True


@api("/api/admin/default-channels", "POST", auth="owner")
async def defaults_add(req):
    b = await req.json()
    kind = b.get("kind")
    if kind not in C.KINDS:
        fail(400, "نوع غير صالح")
    raw = (b.get("identifier") or "").strip()
    if not raw:
        fail(400, "المعرّف مطلوب")
    res, err = await _default_from_input(kind, raw, (b.get("name") or "").strip())
    if not res:
        fail(400, err)
    if not _save_default(kind, *res):
        fail(409, "موجودة مسبقاً")
    return {"ok": True}


@api("/api/admin/default-channels/bulk", "POST", auth="owner")
async def defaults_bulk(req):
    b = await req.json()
    kind = b.get("kind")
    if kind not in C.KINDS:
        fail(400, "نوع غير صالح")
    lines = [l.strip() for l in (b.get("text") or "").split("\n") if l.strip()][:100]
    if not lines:
        fail(400, "لا نص")
    added = failed = 0
    errors = []
    for line in lines:
        try:
            parts = [p.strip() for p in line.split("|")]
            res, err = await _default_from_input(kind, parts[0], parts[1] if len(parts) > 1 else "")
            if not res:
                failed += 1
                errors.append(parts[0] + ": " + err)
                continue
            if not _save_default(kind, *res):
                failed += 1
                errors.append(res[1] + ": موجودة")
                continue
            added += 1
        except Exception as e:
            failed += 1
            errors.append(line[:30] + ": " + str(e)[:40])
    return {"ok": True, "added": added, "failed": failed, "errors": errors}


@api("/api/admin/default-channels/{cid:int}", "DELETE", auth="owner")
async def defaults_del(req):
    run("DELETE FROM default_channels WHERE id=?", (req.p("cid"),))
    return {"ok": True}


@api("/api/admin/default-channels/{cid:int}", "PATCH", auth="owner")
async def defaults_patch(req):
    b = await req.json()
    sets, vals = [], []
    if "enabled" in b:
        sets.append("enabled=?"); vals.append(1 if b["enabled"] else 0)
    if "name" in b:
        sets.append("name=?"); vals.append(str(b["name"])[:80])
    if sets:
        vals.append(req.p("cid"))
        run("UPDATE default_channels SET " + ", ".join(sets) + " WHERE id=?", vals)
    return {"ok": True}


# ═══ تويتر ═══
@api("/api/admin/twitter", auth="owner")
async def tw_get(req):
    day = time.strftime("%Y%m%d", time.gmtime())
    key = S.get_tw_key()
    return {"configured": bool(key), "source": "env" if C.TWITTER_ENV_KEY else ("db" if cfg("twitter_bearer", "") else "none"),
            "key_hint": ("••••" + key[-4:]) if key else "", "interval": cfg_int("tw_interval", 300), "daily_cap": cfg_int("tw_daily_cap", 500),
            "reads_today": cfg_int("tw_reads_" + day, 0), "last_error": state.TW["last_error"], "last_ok": state.TW["last_ok"],
            "paused": state.TW["pause_until"] > time.time(), "accounts": val("SELECT COUNT(*) FROM tw_channels", (), 0),
            "unique_accounts": val("SELECT COUNT(DISTINCT lower(username)) FROM tw_channels WHERE enabled=1 AND auto_send=1", (), 0)}


@api("/api/admin/twitter", "POST", auth="owner")
async def tw_set(req):
    b = await req.json()
    if "api_key" in b and not C.TWITTER_ENV_KEY:
        key = str(b["api_key"]).strip()[:700]
        if key.lower().startswith("bearer "):
            key = key[7:].strip()
        if key and len(key) < 30:
            fail(400, "المفتاح قصير جداً — انسخ الـ Bearer Token كاملاً")
        set_cfg("twitter_bearer", key)
        state.TW["pause_until"] = 0
        state.TW["last_error"] = ""
    if "interval" in b:
        set_cfg("tw_interval", _clamp(b["interval"], 60, 3600, 300))
    if "daily_cap" in b:
        set_cfg("tw_daily_cap", _clamp(b["daily_cap"], 0, 100000, 500))
    if b.get("test"):
        if not S.tw_available():
            return {"ok": False, "error": "أضف المفتاح أولاً"}
        state.TW["pause_until"] = 0
        st, j, err = await S.tw_get("/users/by/username/XDevelopers", {"user.fields": "name"})
        if st == 200 and j.get("data"):
            return {"ok": True, "test": "ok", "detail": "الاتصال ناجح ✅ (" + (j["data"].get("name") or "") + ")"}
        return {"ok": False, "error": err or "فشل الاتصال بتويتر"}
    return {"ok": True, "configured": S.tw_available()}


# ═══ المستخدمون ═══
USER_COLS = "id,username,display,avatar,role,active,banned,lim_kick,lim_yt,lim_tg,lim_tw,can_discord,created,last_login,linked_tg_id,linked_tg_username,linked_tg_name,is_member,member_checked"


@api("/api/admin/users", auth="owner")
async def users_list(req):
    rows = q("SELECT " + USER_COLS + " FROM users ORDER BY id")
    counts = {}
    for k, t in C.KIND_TABLE.items():
        for r in q("SELECT added_by, COUNT(*) n FROM " + t + " GROUP BY added_by"):
            counts.setdefault(r["added_by"], {})[k] = r["n"]
    for r in rows:
        r["counts"] = counts.get(r["username"], {})
    return {"rows": rows}


@api("/api/admin/users/{uid:int}/details", auth="owner")
async def user_details(req):
    user = q1("SELECT " + USER_COLS + " FROM users WHERE id=?", (req.p("uid"),))
    if not user:
        fail(404, "غير موجود")
    un = user["username"]
    return {"user": user,
            "kick": q("SELECT id,slug,name,avatar,live,viewers,title,enabled,created FROM kick_channels WHERE added_by=? ORDER BY id DESC", (un,)),
            "tt": q("SELECT id,slug,name,avatar,live,viewers,enabled,created FROM tt_channels WHERE added_by=? ORDER BY id DESC", (un,)),
            "yt": q("SELECT id,channel_id,name,avatar,enabled,created FROM yt_channels WHERE added_by=? ORDER BY id DESC", (un,)),
            "tw": q("SELECT id,username,name,avatar,enabled,created FROM tw_channels WHERE added_by=? ORDER BY id DESC", (un,)),
            "tg": q("SELECT id,chat_id,username,name,avatar,verified,enabled,created FROM tg_channels WHERE added_by=? ORDER BY id DESC", (un,)),
            "discord_feeds": q("SELECT id,channel_id,channel_name,display_name,enabled,created FROM discord_feeds WHERE added_by=? ORDER BY id DESC", (un,)),
            "feed_subs": q("SELECT fs.id, fs.feed_id, fs.tg_channel_id, df.channel_name, t.name as tg_name FROM feed_subs fs LEFT JOIN discord_feeds df ON df.id=fs.feed_id LEFT JOIN tg_channels t ON t.id=fs.tg_channel_id WHERE fs.username=?", (un,)),
            "notifs_count": val("SELECT COUNT(*) FROM notifs WHERE username=?", (un,), 0),
            "sessions": val("SELECT COUNT(*) FROM sessions WHERE username=? AND expires>?", (un, now()), 0),
            "activity": q("SELECT ts,action,ip FROM security_log WHERE username=? ORDER BY id DESC LIMIT 10", (un,))}


@api("/api/admin/users", "POST", auth="owner")
async def user_add(req):
    b = await req.json()
    un = (b.get("username") or "").strip()
    pw = str(b.get("password") or "")
    if not re.match(r"^[A-Za-z0-9_.-]{3,30}$", un):
        fail(400, "اسم غير صالح (3-30 حرف إنجليزي)")
    if len(pw) < 6:
        fail(400, "كلمة المرور 6 أحرف على الأقل")
    if un.lower() == C.ADMIN_USERNAME.lower():
        fail(400, "محجوز")
    if q1("SELECT 1 x FROM users WHERE lower(username)=lower(?)", (un,)):
        fail(409, "الاسم مستخدم")
    salt = new_salt()
    run("INSERT INTO users(username,display,pass_hash,salt,role,active,banned,lim_kick,lim_yt,lim_tg,lim_tw,can_discord,created) VALUES(?,?,?,?,'user',1,0,?,?,?,?,?,?)",
        (un, (b.get("display") or un)[:60], hash_pw(pw, salt), salt, opt_int(b.get("lim_kick")), opt_int(b.get("lim_yt")), opt_int(b.get("lim_tg")),
         opt_int(b.get("lim_tw")), 1 if b.get("can_discord") else 0, now()))
    log_sec(req.username, "admin_user_add", un, req.ip)
    return {"ok": True}


@api("/api/admin/users/{uid:int}", "PATCH", auth="owner")
async def user_patch(req):
    row = q1("SELECT * FROM users WHERE id=?", (req.p("uid"),))
    if not row:
        fail(404, "غير موجود")
    b = await req.json()
    is_self = row["username"] == req.username
    is_root = row["username"].lower() == C.ADMIN_USERNAME.lower()
    sets, vals = [], []
    if "banned" in b and not is_self and not is_root:
        sets.append("banned=?"); vals.append(1 if b["banned"] else 0)
    if "active" in b and not is_self and not is_root:
        sets.append("active=?"); vals.append(1 if b["active"] else 0)
    if "role" in b and not is_root and not is_self:
        sets.append("role=?"); vals.append("owner" if b["role"] == "owner" else "user")
    if "display" in b:
        sets.append("display=?"); vals.append(str(b["display"])[:60] or row["username"])
    for k in ("lim_kick", "lim_yt", "lim_tg", "lim_tw"):
        if k in b:
            sets.append(k + "=?"); vals.append(opt_int(b[k]))
    if "can_discord" in b:
        sets.append("can_discord=?"); vals.append(1 if b["can_discord"] else 0)
    pw_ch = False
    if b.get("password"):
        if len(str(b["password"])) < 6:
            fail(400, "كلمة المرور 6 أحرف على الأقل")
        salt = new_salt()
        sets += ["pass_hash=?", "salt=?"]
        vals += [hash_pw(str(b["password"]), salt), salt]
        pw_ch = True
    if sets:
        vals.append(req.p("uid"))
        run("UPDATE users SET " + ", ".join(sets) + " WHERE id=?", vals)
    if pw_ch or "banned" in b or "active" in b or b.get("logout"):
        kill_sessions(row["username"])
    log_sec(req.username, "admin_user_edit", row["username"], req.ip)
    return {"ok": True}


@api("/api/admin/users/{uid:int}", "DELETE", auth="owner")
async def user_delete(req):
    row = q1("SELECT * FROM users WHERE id=?", (req.p("uid"),))
    if not row:
        fail(404, "غير موجود")
    if row["username"] == req.username or row["username"].lower() == C.ADMIN_USERNAME.lower():
        fail(400, "لا يمكن حذف هذا الحساب")
    un = row["username"]
    with tx() as c:
        c.execute("DELETE FROM tg_sent_log WHERE tg_id IN (SELECT id FROM tg_channels WHERE added_by=?)", (un,))
        c.execute("DELETE FROM feed_subs WHERE username=? OR tg_channel_id IN (SELECT id FROM tg_channels WHERE added_by=?)", (un, un))
        for t in ("kick_channels", "yt_channels", "tg_channels", "tw_channels", "tt_channels", "recent_videos"):
            c.execute("DELETE FROM " + t + " WHERE added_by=?", (un,))
        for t in ("notifs", "sessions", "suggestions", "push_subs", "news_read"):
            c.execute("DELETE FROM " + t + " WHERE username=?", (un,))
        c.execute("DELETE FROM tg_link_codes WHERE site_username=?", (un,))
        c.execute("DELETE FROM tg_verifications WHERE site_username=?", (un,))
        c.execute("DELETE FROM users WHERE id=?", (req.p("uid"),))
    log_sec(req.username, "admin_user_delete", un, req.ip)
    return {"ok": True}


# ═══ الإحصائيات والنظام ═══
@api("/api/admin/stats", auth="owner")
async def admin_stats(req):
    def n(sql, p=()):
        return val(sql, p, 0)
    s = {"users_total": n("SELECT COUNT(*) FROM users"), "users_active": n("SELECT COUNT(*) FROM users WHERE active=1 AND banned=0"),
         "users_banned": n("SELECT COUNT(*) FROM users WHERE banned=1"), "users_linked_tg": n("SELECT COUNT(*) FROM users WHERE linked_tg_id != ''"),
         "users_members": n("SELECT COUNT(*) FROM users WHERE is_member=1"), "users_new_7d": n("SELECT COUNT(*) FROM users WHERE created>?", (now() - 7 * 86400,)),
         "users_active_24h": n("SELECT COUNT(*) FROM users WHERE last_login>?", (now() - 86400,)),
         "kick_total": n("SELECT COUNT(*) FROM kick_channels"), "kick_live": n("SELECT COUNT(DISTINCT slug) FROM kick_channels WHERE live=1"),
         "tt_total": n("SELECT COUNT(*) FROM tt_channels"), "tt_live": n("SELECT COUNT(DISTINCT slug) FROM tt_channels WHERE live=1"),
         "yt_total": n("SELECT COUNT(*) FROM yt_channels"), "tw_total": n("SELECT COUNT(*) FROM tw_channels"),
         "tg_total": n("SELECT COUNT(*) FROM tg_channels"), "tg_verified": n("SELECT COUNT(*) FROM tg_channels WHERE verified=1"),
         "feeds_total": n("SELECT COUNT(*) FROM discord_feeds"), "feed_subs_total": n("SELECT COUNT(*) FROM feed_subs WHERE enabled=1"),
         "suggestions_unread": n("SELECT COUNT(*) FROM suggestions WHERE is_read=0"), "push_subs": n("SELECT COUNT(*) FROM push_subs"),
         "defaults_total": n("SELECT COUNT(*) FROM default_channels"), "tg_known": n("SELECT COUNT(*) FROM tg_known_channels"),
         "news_total": n("SELECT COUNT(*) FROM news WHERE enabled=1"),
         "sent_24h": n("SELECT COUNT(*) FROM tg_sent_log WHERE ts>? AND ok=1", (now() - 86400,)),
         "failed_24h": n("SELECT COUNT(*) FROM tg_sent_log WHERE ts>? AND ok=0", (now() - 86400,))}
    # منحنى الإرسال آخر 7 أيام
    day0 = now() - 6 * 86400
    per = {r["d"]: (r["ok"], r["bad"]) for r in q("SELECT CAST((ts-?)/86400 AS INTEGER) d, SUM(ok) ok, SUM(1-ok) bad FROM tg_sent_log WHERE ts>=? GROUP BY d", (day0 - day0 % 86400, day0 - day0 % 86400))}
    s["sent_series"] = [{"d": i, "ok": (per.get(i) or (0, 0))[0] or 0, "bad": (per.get(i) or (0, 0))[1] or 0} for i in range(7)]
    s.update({"discord_ready": dcb.is_ready(), "discord_channels": len(state.DC["channels"]), "auto_discovery": not bool(C.WATCH_CHANNELS),
              "has_telegram": bool(C.TELEGRAM_TOKEN), "has_discord": bool(C.DISCORD_TOKEN), "has_push": push_available(), "has_groq": groq_available(),
              "has_twitter": S.tw_available(), "groq_source": groq_source(), "maintenance": cfg("maintenance", "0") == "1",
              "self_bot_mode": state.DC["self_bot"], "bot_info": state.DC["bot"], "public_url": C.PUBLIC_URL,
              "webhook_set": bool(C.PUBLIC_URL and C.TELEGRAM_TOKEN), "tg_bot": state.TG_BOT.get("username", "")})
    return s


@api("/api/admin/system", auth="owner")
async def admin_system(req):
    """صحة النظام (جديد): المهام الدورية، حجم القاعدة، وقت التشغيل"""
    try:
        db_size = os.path.getsize(C.DB_PATH) + (os.path.getsize(C.DB_PATH + "-wal") if os.path.exists(C.DB_PATH + "-wal") else 0)
    except Exception:
        db_size = 0
    return {"uptime": int(time.time() - state.STARTED), "started": int(state.STARTED), "jobs": jobs.status(), "db_size": db_size,
            "db_path": C.DB_PATH, "images": val("SELECT COUNT(*) FROM images", (), 0), "images_size": val("SELECT COALESCE(SUM(size),0) FROM images", (), 0),
            "python": sys.version.split()[0], "platform": platform.system() + " " + platform.release(), "stats": state.STATS,
            "tg_bot": state.TG_BOT, "discord_ready": dcb.is_ready(), "public_url": C.PUBLIC_URL,
            "volume_hint": not C.DB_PATH.startswith("/app/data") and bool(os.getenv("RAILWAY_ENVIRONMENT"))}


@api("/api/admin/backup", auth="owner")
async def admin_backup(req):
    """تحميل نسخة احتياطية كاملة من قاعدة البيانات (جديد)"""
    data = backup_bytes()
    log_sec(req.username, "db_backup", str(len(data)), req.ip)
    fn = "respect-live-backup-" + time.strftime("%Y%m%d-%H%M", time.gmtime()) + ".db"
    return Response(content=data, media_type="application/octet-stream",
                    headers={"content-disposition": 'attachment; filename="' + fn + '"', "cache-control": "no-store"})


@api("/api/admin/cleanup-images", "POST", auth="owner")
async def cleanup_images(req):
    """حذف الصور غير المستخدمة لتخفيف حجم القاعدة (جديد)"""
    used = set()
    for tbl, cols in (("kick_channels", ("avatar", "banner", "msg")), ("yt_channels", ("avatar", "banner", "msg")), ("tw_channels", ("avatar", "banner", "msg")),
                      ("tt_channels", ("avatar", "msg")), ("tg_channels", ("avatar", "banner")), ("default_channels", ("avatar",)), ("users", ("avatar",)),
                      ("news", ("image",)), ("notifs", ("image",)), ("discord_feeds", ("fixed_image", "keyword_rules")), ("settings", ("v",)), ("tg_known_channels", ("avatar",))):
        for col in cols:
            for r in q("SELECT " + col + " v FROM " + tbl + " WHERE " + col + " LIKE '%/api/image/%'"):
                for m in re.finditer(r"/api/image/([A-Za-z0-9_-]{10,40})", r["v"] or ""):
                    used.add(m.group(1))
    week = now() - 7 * 86400
    cands = [r["id"] for r in q("SELECT id FROM images WHERE created<?", (week,))]
    dead = [i for i in cands if i not in used]
    with tx() as c:
        for i in dead:
            c.execute("DELETE FROM images WHERE id=?", (i,))
            c.execute("DELETE FROM img_cache WHERE img_id=?", (i,))
    try:
        run("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass
    return {"ok": True, "deleted": len(dead)}


@api("/api/admin/security", auth="owner")
async def admin_security(req):
    act = (req.query.get("action") or "").strip()[:40]
    user = (req.query.get("user") or "").strip()[:60]
    where, p = ["1=1"], []
    if act:
        where.append("action LIKE ?"); p.append(act + "%")
    if user:
        where.append("username=?"); p.append(user)
    return {"rows": q("SELECT ts,username,action,detail,ip FROM security_log WHERE " + " AND ".join(where) + " ORDER BY id DESC LIMIT 300", tuple(p)),
            "fails_24h": val("SELECT COUNT(*) FROM security_log WHERE action='login_fail' AND ts>?", (now() - 86400,), 0)}
