"""Respect Live — نظام مراقبة كامل (Self-bot + Groq AI)"""
import os, re, json, time, hashlib, secrets, sqlite3, asyncio
from contextlib import asynccontextmanager
from typing import Optional
import httpx
import discord
from fastapi import FastAPI, Request, Response, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response as FastResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_hex(32))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")  # ⚠️ user token للـ self-bot
GROQ_API_KEY_ENV = os.getenv("GROQ_API_KEY", "")    # اختياري — لو ما حبيت تخزنه في DB
WATCH_CHANNELS = [c.strip() for c in os.getenv("DISCORD_WATCH_CHANNELS", "").split(",") if c.strip()]
ALLOWED_GUILDS = [g.strip() for g in os.getenv("DISCORD_ALLOWED_GUILDS", "").split(",") if g.strip()]

# 🆕 متغيرات جديدة
SELF_BOT_MODE = os.getenv("SELF_BOT_MODE", "1") == "1"           # تفعيل وضع السيلف-بوت
DISCORD_ENABLE = os.getenv("DISCORD_ENABLE", "1") == "1"         # تشغيل البوت كلياً
DISCORD_FALLBACK_BOT = os.getenv("DISCORD_FALLBACK_BOT", "1") == "1"  # رجوع لـ bot عادي لو فشل

VAPID_PUBLIC = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_EMAIL = os.getenv("VAPID_EMAIL", "mailto:admin@example.com")
SITE_NAME = os.getenv("SITE_NAME", "Respect Live")
DB_PATH = os.getenv("DB_PATH", "respect.db")
SESSION_TTL = 7 * 24 * 3600
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
MAX_PER_MIN_TG = 30
MAX_PER_MIN_CH = 15
BATCH_KICK = 30
BATCH_YT = 30
MAX_IMAGE_SIZE = 2 * 1024 * 1024

THEMES = [
    {"id": "default", "n": "الافتراضي", "c1": "#030508", "c2": "#0a0f18", "ac": "#0b55ea"},
    {"id": "saudi", "n": "اليوم الوطني السعودي", "c1": "#033a20", "c2": "#0b7a3e", "ac": "#ffffff"},
    {"id": "founding", "n": "يوم التأسيس", "c1": "#3a290b", "c2": "#0b5c3a", "ac": "#e6b85c"},
    {"id": "ramadan", "n": "رمضان", "c1": "#0a1733", "c2": "#1d3a6e", "ac": "#f5c04a"},
    {"id": "fitr", "n": "عيد الفطر", "c1": "#0d3434", "c2": "#1d6b57", "ac": "#ffd166"},
    {"id": "adha", "n": "عيد الأضحى", "c1": "#2a1a0a", "c2": "#6a4720", "ac": "#f0b84d"},
]

def db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, display TEXT DEFAULT '', avatar TEXT DEFAULT '', pass_hash TEXT DEFAULT '', salt TEXT DEFAULT '', role TEXT DEFAULT 'user', active INTEGER DEFAULT 1, banned INTEGER DEFAULT 0, lim_kick INTEGER, lim_yt INTEGER, lim_tg INTEGER, can_discord INTEGER DEFAULT 0, created INTEGER, last_login INTEGER);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT NOT NULL, created INTEGER, expires INTEGER);
CREATE INDEX IF NOT EXISTS idx_sessions_exp ON sessions(expires);
CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS default_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, identifier TEXT NOT NULL, name TEXT DEFAULT '', avatar TEXT DEFAULT '', enabled INTEGER DEFAULT 1, created INTEGER, UNIQUE(kind, identifier));
CREATE INDEX IF NOT EXISTS idx_def_kind ON default_channels(kind, enabled);
CREATE TABLE IF NOT EXISTS kick_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL, name TEXT DEFAULT '', avatar TEXT DEFAULT '', banner TEXT DEFAULT '', msg TEXT DEFAULT '', btn_text TEXT DEFAULT '', enabled INTEGER DEFAULT 1, auto_send INTEGER DEFAULT 1, live INTEGER DEFAULT 0, title TEXT DEFAULT '', viewers INTEGER DEFAULT 0, thumb TEXT DEFAULT '', last_check INTEGER DEFAULT 0, added_by TEXT NOT NULL, created INTEGER, UNIQUE(slug, added_by));
CREATE INDEX IF NOT EXISTS idx_kick_by ON kick_channels(added_by);
CREATE INDEX IF NOT EXISTS idx_kick_check ON kick_channels(enabled, last_check);
CREATE TABLE IF NOT EXISTS yt_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT NOT NULL, handle TEXT DEFAULT '', name TEXT DEFAULT '', avatar TEXT DEFAULT '', banner TEXT DEFAULT '', msg TEXT DEFAULT '', btn_text TEXT DEFAULT '', enabled INTEGER DEFAULT 1, auto_send INTEGER DEFAULT 1, last_video TEXT DEFAULT '', last_check INTEGER DEFAULT 0, added_by TEXT NOT NULL, created INTEGER, UNIQUE(channel_id, added_by));
CREATE INDEX IF NOT EXISTS idx_yt_by ON yt_channels(added_by);
CREATE INDEX IF NOT EXISTS idx_yt_check ON yt_channels(enabled, last_check);
CREATE TABLE IF NOT EXISTS tg_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, username TEXT DEFAULT '', name TEXT DEFAULT '', avatar TEXT DEFAULT '', banner TEXT DEFAULT '', enabled INTEGER DEFAULT 1, added_by TEXT NOT NULL, created INTEGER, UNIQUE(chat_id, added_by));
CREATE INDEX IF NOT EXISTS idx_tg_by ON tg_channels(added_by);
CREATE TABLE IF NOT EXISTS discord_feeds (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT NOT NULL, channel_name TEXT DEFAULT '', guild_id TEXT DEFAULT '', template TEXT DEFAULT '', btn_text TEXT DEFAULT 'عرض الروم', source_type TEXT DEFAULT 'generic', target_tg_ids TEXT DEFAULT '', enabled INTEGER DEFAULT 1, use_original INTEGER DEFAULT 1, ignore_bots TEXT DEFAULT '', keyword_rules TEXT DEFAULT '', fixed_image TEXT DEFAULT '', room_url TEXT DEFAULT '', use_ai INTEGER DEFAULT 0, ai_prompt TEXT DEFAULT '', added_by TEXT NOT NULL, created INTEGER, UNIQUE(channel_id, added_by));
CREATE INDEX IF NOT EXISTS idx_df_by ON discord_feeds(added_by);
CREATE INDEX IF NOT EXISTS idx_df_ch ON discord_feeds(channel_id, enabled);
CREATE TABLE IF NOT EXISTS discord_seen (message_id TEXT PRIMARY KEY, ts INTEGER);
CREATE INDEX IF NOT EXISTS idx_ds_ts ON discord_seen(ts);
CREATE TABLE IF NOT EXISTS discord_bots (id TEXT PRIMARY KEY, name TEXT DEFAULT '', avatar TEXT DEFAULT '', first_seen INTEGER, last_seen INTEGER, seen_count INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS notifs (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, title TEXT DEFAULT '', body TEXT DEFAULT '', image TEXT DEFAULT '', btn_text TEXT DEFAULT '', btn_url TEXT DEFAULT '', kind TEXT DEFAULT 'admin', ts INTEGER, is_read INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_notifs ON notifs(username, ts);
CREATE TABLE IF NOT EXISTS recent_videos (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT NOT NULL, ch_name TEXT DEFAULT '', title TEXT DEFAULT '', thumb TEXT DEFAULT '', url TEXT DEFAULT '', ts INTEGER, added_by TEXT NOT NULL, UNIQUE(video_id, added_by));
CREATE INDEX IF NOT EXISTS idx_rv_by ON recent_videos(added_by, ts);
CREATE TABLE IF NOT EXISTS suggestions (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, text TEXT NOT NULL, is_read INTEGER DEFAULT 0, ts INTEGER);
CREATE INDEX IF NOT EXISTS idx_sug_ts ON suggestions(ts DESC);
CREATE TABLE IF NOT EXISTS push_subs (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, endpoint TEXT UNIQUE NOT NULL, p256dh TEXT NOT NULL, auth TEXT NOT NULL, ts INTEGER);
CREATE INDEX IF NOT EXISTS idx_push_user ON push_subs(username);
CREATE TABLE IF NOT EXISTS images (id TEXT PRIMARY KEY, mime TEXT NOT NULL, data BLOB NOT NULL, size INTEGER NOT NULL, uploaded_by TEXT, created INTEGER);
CREATE TABLE IF NOT EXISTS rate_limits (k TEXT PRIMARY KEY, cnt INTEGER, ts INTEGER);
CREATE TABLE IF NOT EXISTS security_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, username TEXT, action TEXT, detail TEXT, ip TEXT);
CREATE INDEX IF NOT EXISTS idx_sec_ts ON security_log(ts);
"""

def init_db():
    c = db()
    c.executescript(SCHEMA)
    # Migrations
    additions = [
        ("users", "can_discord", "INTEGER DEFAULT 0"),
        ("users", "avatar", "TEXT DEFAULT ''"),
        ("kick_channels", "btn_text", "TEXT DEFAULT ''"),
        ("kick_channels", "auto_send", "INTEGER DEFAULT 1"),
        ("yt_channels", "btn_text", "TEXT DEFAULT ''"),
        ("yt_channels", "auto_send", "INTEGER DEFAULT 1"),
        ("yt_channels", "banner", "TEXT DEFAULT ''"),
        ("tg_channels", "banner", "TEXT DEFAULT ''"),
        ("discord_feeds", "btn_text", "TEXT DEFAULT 'عرض الروم'"),
        ("discord_feeds", "target_tg_ids", "TEXT DEFAULT ''"),
        ("discord_feeds", "guild_id", "TEXT DEFAULT ''"),
        ("discord_feeds", "use_original", "INTEGER DEFAULT 1"),
        ("discord_feeds", "ignore_bots", "TEXT DEFAULT ''"),
        ("discord_feeds", "keyword_rules", "TEXT DEFAULT ''"),
        ("discord_feeds", "fixed_image", "TEXT DEFAULT ''"),
        ("discord_feeds", "room_url", "TEXT DEFAULT ''"),
        ("discord_feeds", "use_ai", "INTEGER DEFAULT 0"),
        ("discord_feeds", "ai_prompt", "TEXT DEFAULT ''"),
    ]
    for tbl, col, typ in additions:
        try:
            cols = [r["name"] for r in c.execute(f"PRAGMA table_info({tbl})").fetchall()]
            if col not in cols:
                c.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")
                c.commit()
                print(f"[DB] Added {col} to {tbl}")
        except Exception as e:
            print(f"[DB] ALTER {tbl}.{col}: {e}")
    salt = secrets.token_hex(16)
    new_hash = hash_pw(ADMIN_PASSWORD, salt)
    existing = c.execute("SELECT 1 FROM users WHERE username=?", (ADMIN_USERNAME,)).fetchone()
    if not existing:
        c.execute("INSERT INTO users(username,display,pass_hash,salt,role,active,banned,can_discord,created) VALUES(?,?,?,?,'owner',1,0,1,?)", (ADMIN_USERNAME, ADMIN_USERNAME, new_hash, salt, now()))
        print(f"[DB] Admin created: {ADMIN_USERNAME}")
    else:
        c.execute("UPDATE users SET pass_hash=?, salt=?, role='owner', active=1, banned=0, can_discord=1 WHERE username=?", (new_hash, salt, ADMIN_USERNAME))
        print("[DB] Admin synced")
    defaults = {
        "site_name": SITE_NAME, "site_sub": "STREAM MONITOR · OFFICIAL",
        "hero_title": "مراقبة", "hero_accent": "القنوات.",
        "hero_text": "تابع قنواتك على كيك ويوتيوب وتيليجرام في مكان واحد.",
        "tpl_kick": "<b>{name}</b>\nبدأ بثاً مباشراً الآن\n\n<b>{title}</b>",
        "tpl_yt": "<b>{name}</b>\nنشر فيديو جديداً\n\n<b>{title}</b>",
        "tpl_discord": "<b>{name}</b>\n\n{content}",
        "tpl_twitter": "<b>{name}</b>\n\n{content}",
        "tpl_youtube_dc": "<b>{title}</b>\n\n{name}",
        "btn_kick": "شاهد البث", "btn_yt": "شاهد الفيديو",
        "btn_tg": "عرض القناة", "btn_discord": "عرض الروم",
        "lim_kick": "10", "lim_yt": "5", "lim_tg": "3",
        "guest_mode": "1", "guest_blur": "14",
        "site_theme": "default", "site_logo": "",
        "site_c1": "#030508", "site_c2": "#0a0f18", "site_ac": "#0b55ea",
        "maintenance": "0", "maintenance_text": "الموقع في صيانة مؤقتة — نرجع قريباً",
        "bot_invite_url": "", "bot_name_custom": "Respect Live Bot",
        "groq_api_key": "", "groq_model": "llama-3.3-70b-versatile",
    }
    for k, v in defaults.items():      # ✅ صحيح
    c.execute("INSERT OR IGNORE INTO settings(k,v) VALUES(?,?)", (k, v))
    c.commit()
    c.close()
    print("[DB] Ready")

def now():
    return int(time.time())

def cfg(k, d=""):
    c = db()
    r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    c.close()
    return r["v"] if r else d

def set_cfg(k, v):
    c = db()
    c.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
    c.commit()
    c.close()

def hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 100000).hex()

def log_sec(username, action, detail="", ip=""):
    try:
        c = db()
        c.execute("INSERT INTO security_log(ts,username,action,detail,ip) VALUES(?,?,?,?,?)", (now(), username or "anon", action[:60], detail[:300], ip[:60]))
        c.execute("DELETE FROM security_log WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY id DESC) rn FROM security_log) WHERE rn > 5000)")
        c.commit()
        c.close()
    except Exception:
        pass

def get_site_theme():
    tid = cfg("site_theme", "default")
    if tid == "custom":
        return {"id": "custom", "n": "مخصص", "c1": cfg("site_c1", "#030508"), "c2": cfg("site_c2", "#0a0f18"), "ac": cfg("site_ac", "#0b55ea")}
    for t in THEMES:
        if t["id"] == tid:
            return t
    return THEMES[0]

_rate_map = {}
def rate_ok(key, max_per_min=MAX_PER_MIN_TG):
    t = time.time()
    lst = _rate_map.setdefault(key, [])
    lst[:] = [x for x in lst if t - x < 60]
    if len(lst) >= max_per_min:
        return False
    lst.append(t)
    return True

def auth(request):
    tok = request.cookies.get("rl_sid")
    if not tok or len(tok) > 200:
        return None
    c = db()
    row = c.execute("SELECT s.username, u.* FROM sessions s JOIN users u ON u.username=s.username WHERE s.token=? AND s.expires>? AND u.active=1 AND u.banned=0", (tok, now())).fetchone()
    c.close()
    return dict(row) if row else None

def new_session(username):
    tok = secrets.token_urlsafe(32)
    c = db()
    c.execute("INSERT INTO sessions(token,username,created,expires) VALUES(?,?,?,?)", (tok, username, now(), now() + SESSION_TTL))
    c.commit()
    c.close()
    return tok

def kill_sessions(username):
    c = db()
    c.execute("DELETE FROM sessions WHERE username=?", (username,))
    c.commit()
    c.close()

def require_auth(request):
    u = auth(request)
    if not u:
        raise HTTPException(401, "غير مسجل")
    return u

def require_owner(request):
    u = require_auth(request)
    if u["role"] != "owner":
        raise HTTPException(403, "غير مصرح")
    return u

def require_discord_access(request):
    u = require_auth(request)
    if u.get("role") == "owner":
        return u
    if u.get("can_discord") == 1:
        return u
    raise HTTPException(403, "غير مصرح")

def get_user_limits(username, role):
    if role == "owner":
        return {"kick": 9999, "yt": 9999, "tg": 9999}
    c = db()
    u = c.execute("SELECT lim_kick, lim_yt, lim_tg FROM users WHERE username=?", (username,)).fetchone()
    c.close()
    defaults = {"kick": int(cfg("lim_kick", "10")), "yt": int(cfg("lim_yt", "5")), "tg": int(cfg("lim_tg", "3"))}
    if not u:
        return defaults
    return {
        "kick": u["lim_kick"] if u["lim_kick"] is not None else defaults["kick"],
        "yt": u["lim_yt"] if u["lim_yt"] is not None else defaults["yt"],
        "tg": u["lim_tg"] if u["lim_tg"] is not None else defaults["tg"],
    }

def check_limit(username, kind, role, adding=1):
    if role == "owner":
        return True
    limit = get_user_limits(username, role).get(kind, 10)
    table = {"kick": "kick_channels", "yt": "yt_channels", "tg": "tg_channels"}[kind]
    c = db()
    n = c.execute(f"SELECT COUNT(*) n FROM {table} WHERE added_by=?", (username,)).fetchone()["n"]
    c.close()
    return (n + adding) <= limit

def limit_info(username, kind, role):
    table = {"kick": "kick_channels", "yt": "yt_channels", "tg": "tg_channels"}[kind]
    limit = get_user_limits(username, role).get(kind, 10)
    c = db()
    used = c.execute(f"SELECT COUNT(*) n FROM {table} WHERE added_by=?", (username,)).fetchone()["n"]
    c.close()
    return {"used": used, "limit": limit, "remaining": max(0, limit - used)}

# ═══════════════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════════════
async def tg_send(chat_id, text, image="", btn="", url=""):
    if not TELEGRAM_TOKEN:
        return False
    markup = {"inline_keyboard": [[{"text": btn[:60], "url": url}]]} if (btn and url) else None
    base = {"chat_id": str(chat_id), "parse_mode": "HTML"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            if image:
                r = await c.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto", json={**base, "photo": image, "caption": (text or ".")[:1024], "reply_markup": markup})
                if r.status_code == 200:
                    return True
            r = await c.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={**base, "text": (text or ".")[:4096], "reply_markup": markup})
            return r.status_code == 200
    except Exception as e:
        print(f"[TG] {e}")
        return False

async def tg_api(method, body):
    if not TELEGRAM_TOKEN:
        return {"ok": False}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}", json=body or {})
            return r.json()
    except Exception as e:
        print(f"[TG API] {e}")
        return {"ok": False}

async def tg_save_photo(file_id):
    if not TELEGRAM_TOKEN:
        return ""
    j = await tg_api("getFile", {"file_id": file_id})
    if not j.get("ok"):
        return ""
    file_path = j["result"]["file_path"]
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}")
            if r.status_code != 200:
                return ""
            content = r.content
    except Exception:
        return ""
    if len(content) > MAX_IMAGE_SIZE:
        return ""
    img_id = secrets.token_urlsafe(16)
    c = db()
    c.execute("INSERT INTO images(id,mime,data,size,uploaded_by,created) VALUES(?,?,?,?,?,?)", (img_id, "image/jpeg", content, len(content), "system", now()))
    c.commit()
    c.close()
    return f"/api/image/{img_id}"

async def tg_get_chat_info(chat_id):
    j = await tg_api("getChat", {"chat_id": chat_id})
    if not j.get("ok"):
        return None
    chat = j.get("result", {})
    name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username") or str(chat_id)
    username = ("@" + chat["username"]) if chat.get("username") else ""
    photo = chat.get("photo") or {}
    photo_id = photo.get("big_file_id") or photo.get("small_file_id") or ""
    avatar_url = ""
    if photo_id:
        avatar_url = await tg_save_photo(photo_id)
    return {"name": name, "username": username, "avatar": avatar_url, "chat_id": str(chat.get("id", chat_id))}

def norm_chat(s):
    s = (s or "").strip()
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

# ═══════════════════════════════════════════════════════════
# KICK
# ═══════════════════════════════════════════════════════════
async def kick_fetch(slug):
    h = {"User-Agent": UA, "Accept": "application/json", "Referer": "https://kick.com/"}
    async with httpx.AsyncClient(timeout=15, headers=h) as c:
        for v in ("v2", "v1"):
            try:
                r = await c.get(f"https://kick.com/api/{v}/channels/{slug}")
                if r.status_code == 404:
                    continue
                if r.status_code != 200:
                    continue
                j = r.json()
                ls = j.get("livestream") or {}
                u = j.get("user") or {}
                bn = j.get("banner_image")
                if isinstance(bn, dict):
                    bn = bn.get("url") or ""
                return {"name": u.get("username") or slug, "avatar": u.get("profile_pic") or "", "banner": bn or "", "live": bool(ls.get("is_live")), "title": ls.get("session_title") or "", "viewers": ls.get("viewer_count") or 0, "thumb": ((ls.get("thumbnail") or {}).get("url")) or ""}
            except Exception as e:
                print(f"[KICK] {e}")
    return None

# ═══════════════════════════════════════════════════════════
# YOUTUBE
# ═══════════════════════════════════════════════════════════
async def yt_feed(channel_id):
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}) as c:
            r = await c.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
            if r.status_code != 200:
                return None
            items = []
            for m in re.finditer(r"<entry>(.*?)</entry>", r.text, re.S):
                e = m.group(1)
                vid = (re.search(r"<yt:videoId>([^<]+)", e) or [None, ""])[1]
                title = (re.search(r"<title>([^<]*)", e) or [None, ""])[1]
                pub = (re.search(r"<published>([^<]+)", e) or [None, ""])[1]
                if vid:
                    items.append({"id": vid, "title": title, "pub": pub})
            return items
    except Exception as e:
        print(f"[YT] {e}")
        return None

async def yt_resolve(input_str):
    input_str = (input_str or "").strip()[:300]
    if not input_str:
        return None
    m = re.search(r"UC[\w-]{22}", input_str)
    if m:
        cid = m.group(0)
        try:
            async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}) as c:
                r = await c.get(f"https://www.youtube.com/channel/{cid}")
                html = r.text
            title = (re.search(r'<meta property="og:title" content="([^"]*)"', html) or [None, cid])[1]
            avatar = (re.search(r'<meta property="og:image" content="([^"]*)"', html) or [None, ""])[1]
            banner = (re.search(r'"banner":{"imageBannerViewModel":{"image":{"sources":\[\{"url":"([^"]*)"', html) or [None, ""])[1]
            return {"channel_id": cid, "name": title, "avatar": avatar, "banner": banner}
        except Exception:
            return {"channel_id": cid, "name": cid, "avatar": "", "banner": ""}
    h = re.search(r"@([\w.\-]+)", input_str)
    if h:
        try:
            async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}) as c:
                r = await c.get(f"https://www.youtube.com/@{h.group(1)}")
                html = r.text
            cid_m = re.search(r'"externalId":"(UC[\w-]{22})"', html) or re.search(r'"channelId":"(UC[\w-]{22})"', html)
            if not cid_m:
                return None
            cid = cid_m.group(1)
            title = (re.search(r'<meta property="og:title" content="([^"]*)"', html) or [None, cid])[1]
            avatar = (re.search(r'<meta property="og:image" content="([^"]*)"', html) or [None, ""])[1]
            banner = (re.search(r'"banner":{"imageBannerViewModel":{"image":{"sources":\[\{"url":"([^"]*)"', html) or [None, ""])[1]
            return {"channel_id": cid, "name": title, "avatar": avatar, "banner": banner}
        except Exception:
            return None
    return None

# ═══════════════════════════════════════════════════════════
# PUSH
# ═══════════════════════════════════════════════════════════
def push_available():
    return bool(VAPID_PUBLIC and VAPID_PRIVATE)

async def push_send_to_user(username, title, body, image="", url="/", tag=""):
    if not push_available():
        return 0
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return 0
    c = db()
    subs = c.execute("SELECT * FROM push_subs WHERE username=?", (username,)).fetchall()
    c.close()
    if not subs:
        return 0
    payload = json.dumps({"title": title[:80], "body": body[:200], "image": image or "", "url": url or "/", "tag": tag or "rl"})
    sent = 0
    for sub in subs:
        try:
            webpush(subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}, data=payload, vapid_private_key=VAPID_PRIVATE, vapid_claims={"sub": VAPID_EMAIL}, timeout=10)
            sent += 1
        except WebPushException as e:
            code = getattr(e.response, "status_code", None) if hasattr(e, "response") else None
            if code in (404, 410):
                c = db()
                c.execute("DELETE FROM push_subs WHERE id=?", (sub["id"],))
                c.commit()
                c.close()
        except Exception:
            pass
    return sent

# ═══════════════════════════════════════════════════════════
# 🆕 TEXT PROCESSING
# ═══════════════════════════════════════════════════════════
_MENTION_RE = re.compile(r"<@[!&]?\d+>")
_ROLE_MENTION = re.compile(r"<@&\d+>")
_CHANNEL_MENTION = re.compile(r"<#\d+>")
_CUSTOM_EMOJI = re.compile(r"<a?:\w+:\d+>")

def clean_mentions(text):
    """يزيل كل أنواع المنشن من النص"""
    if not text:
        return ""
    t = str(text)
    t = _MENTION_RE.sub("", t)
    t = _ROLE_MENTION.sub("", t)
    t = _CHANNEL_MENTION.sub("", t)
    t = re.sub(r"@everyone\b", "", t)
    t = re.sub(r"@here\b", "", t)
    t = _CUSTOM_EMOJI.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def extract_discord_message(msg):
    """استخراج كامل من رسالة ديسكورد (content + embeds + attachments)"""
    author = msg.author.display_name or msg.author.name or ""
    author_no_at = re.sub(r"^@", "", author).strip()
    author_username = getattr(msg.author, "name", "")
    author_id = str(msg.author.id)
    is_bot = bool(getattr(msg.author, "bot", False))

    raw_content = (msg.content or "").strip()
    content = clean_mentions(raw_content)

    embed_title = ""
    embed_desc = ""
    embed_author = ""
    embed_image = ""
    embed_url = ""
    embed_footer = ""
    embed_fields = []
    if msg.embeds:
        e = msg.embeds[0]
        if e.author and e.author.name:
            embed_author = e.author.name
        if e.title:
            embed_title = e.title.strip()
        if e.description:
            embed_desc = clean_mentions(e.description.strip())
        if e.url:
            embed_url = e.url
        if e.footer and e.footer.text:
            embed_footer = e.footer.text
        if e.fields:
            for f in e.fields:
                embed_fields.append({"name": f.name or "", "value": f.value or ""})
        if e.image and e.image.url:
            embed_image = e.image.url
        elif e.thumbnail and e.thumbnail.url:
            embed_image = e.thumbnail.url

    attach_images = []
    if msg.attachments:
        for a in msg.attachments:
            if a.content_type and a.content_type.startswith("image/"):
                attach_images.append(a.url)

    final_image = embed_image or (attach_images[0] if attach_images else "")

    final_text = content or embed_desc or embed_title or ""
    if embed_title and embed_desc and embed_title not in embed_desc:
        final_text = embed_title + "\n\n" + embed_desc
    elif embed_title and not embed_desc:
        final_text = embed_title

    return {
        "author": author[:200],
        "author_no_at": author_no_at[:200],
        "author_username": author_username[:100],
        "author_id": author_id,
        "is_bot": is_bot,
        "content": content[:4000],
        "content_raw": raw_content[:4000],
        "title": embed_title[:300],
        "description": embed_desc[:4000],
        "embed_author": embed_author[:200],
        "embed_url": embed_url,
        "embed_footer": embed_footer[:300],
        "embed_fields": embed_fields[:10],
        "image": final_image,
        "attach_images": attach_images[:5],
        "final_text": final_text[:4000],
        "guild_id": str(msg.guild.id) if msg.guild else "",
        "guild_name": msg.guild.name if msg.guild else "",
        "channel_id": str(msg.channel.id),
        "channel_name": getattr(msg.channel, "name", "") or "",
        "message_id": str(msg.id),
        "message_url": f"https://discord.com/channels/{msg.guild.id}/{msg.channel.id}/{msg.id}" if msg.guild else "",
    }

def match_keyword_image(rules_json, text, default_image=""):
    """يطابق الكلمات المفتاحية ويرجع الصورة المناسبة"""
    if not rules_json:
        return default_image
    try:
        rules = json.loads(rules_json)
    except Exception:
        return default_image
    if not isinstance(rules, list):
        return default_image
    text_lower = (text or "").lower()
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        kws = rule.get("keywords") or []
        if not isinstance(kws, list):
            continue
        for kw in kws:
            kw = str(kw).strip().lower()
            if kw and kw in text_lower:
                return rule.get("image", "") or default_image
    return default_image

def build_discord_text(template, data, site_name=""):
    """يبني النص النهائي من القالب والبيانات"""
    if not template:
        template = "<b>{name}</b>\n\n{content}"
    vars_map = {
        "name": data.get("author_no_at") or data.get("author") or "",
        "author": data.get("author") or "",
        "author_no_at": data.get("author_no_at") or "",
        "username": data.get("author_username") or "",
        "user_id": data.get("author_id") or "",
        "content": data.get("content") or "",
        "content_raw": data.get("content_raw") or "",
        "description": data.get("description") or "",
        "title": data.get("title") or "",
        "footer": data.get("embed_footer") or "",
        "channel": data.get("channel_name") or "",
        "channel_id": data.get("channel_id") or "",
        "guild": data.get("guild_name") or "",
        "guild_id": data.get("guild_id") or "",
        "url": data.get("embed_url") or data.get("message_url") or "",
        "message_url": data.get("message_url") or "",
        "site": site_name,
    }
    def repl(m):
        k = m.group(1)
        return str(vars_map.get(k, m.group(0)))
    return re.sub(r"\{(\w+)\}", repl, str(template))

# ═══════════════════════════════════════════════════════════
# 🆕 GROQ AI
# ═══════════════════════════════════════════════════════════
def get_groq_key():
    return GROQ_API_KEY_ENV or cfg("groq_api_key", "")

def groq_available():
    return bool(get_groq_key())

async def groq_rewrite(text, ai_prompt="", model=None):
    """يعيد صياغة النص عبر Groq"""
    key = get_groq_key()
    if not key:
        return None
    model = model or cfg("groq_model", "llama-3.3-70b-versatile")
    system = ai_prompt.strip() if ai_prompt else "أنت مساعد يعيد صياغة الرسائل بأسلوب واضح ومختصر بالعربية. أعد الرسالة كما هي إن كانت واضحة. لا تكتب أي مقدمة أو خاتمة، أعد النص فقط."
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"authorization": f"Bearer {key}", "content-type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": text[:4000]},
                    ],
                    "temperature": 0.4,
                    "max_tokens": 1024,
                },
            )
            if r.status_code != 200:
                print(f"[Groq] {r.status_code} {r.text[:200]}")
                return None
            j = r.json()
            return (j.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    except Exception as e:
        print(f"[Groq] {e}")
        return None
        # ═══════════════════════════════════════════════════════════
# 🆕 DISCORD BOT — SELF-BOT MODE + FALLBACK
# ═══════════════════════════════════════════════════════════
discord_client = None
_SELF_BOT = False
_DISCORD_MODE = "disabled"  # disabled | self-bot | bot | failed

def _build_discord_client():
    """يبني عميل الديسكورد حسب الإعدادات — self-bot أو bot عادي"""
    global discord_client, _SELF_BOT, _DISCORD_MODE

    if not DISCORD_ENABLE:
        print("[Discord] ⛔ معطّل عبر DISCORD_ENABLE=0")
        _DISCORD_MODE = "disabled"
        return None

    if not DISCORD_TOKEN:
        print("[Discord] ⚠️ لا يوجد توكن — تخطي")
        _DISCORD_MODE = "disabled"
        return None

    intents = discord.Intents(guilds=True, guild_messages=True, message_content=True)

    # محاولة self-bot أولاً لو مفعّل
    if SELF_BOT_MODE:
        try:
            client = discord.Client(self_bot=True, intents=intents)
            _SELF_BOT = True
            _DISCORD_MODE = "self-bot"
            print("[Discord] ✅ Self-bot mode enabled")
            return client
        except TypeError:
            print("[Discord] ⚠️ Self-bot غير متاح — مكتبة discord.py-self غير مثبتة")
            print("[Discord]    ثبّتها: pip install discord.py-self")
            if not DISCORD_FALLBACK_BOT:
                print("[Discord] ⛔ Fallback معطّل — إيقاف البوت")
                _DISCORD_MODE = "failed"
                return None

    # fallback: bot عادي
    try:
        client = discord.Client(intents=intents)
        _SELF_BOT = False
        _DISCORD_MODE = "bot"
        print("[Discord] ✅ Bot mode enabled (توكن بوت رسمي)")
        return client
    except Exception as e:
        print(f"[Discord] ❌ فشل بناء العميل: {e}")
        _DISCORD_MODE = "failed"
        return None

discord_client = _build_discord_client()

_DISCORD_CHANNELS_CACHE = {}
_DISCORD_GUILDS_CACHE = {}
_DISCORD_BOT_INFO = {"id": "", "name": "", "avatar": ""}

def _refresh_discord_cache():
    global _DISCORD_CHANNELS_CACHE, _DISCORD_GUILDS_CACHE, _DISCORD_BOT_INFO
    _DISCORD_CHANNELS_CACHE = {}
    _DISCORD_GUILDS_CACHE = {}
    if not discord_client or not discord_client.is_ready():
        return
    u = discord_client.user
    if u:
        _DISCORD_BOT_INFO = {"id": str(u.id), "name": u.name, "avatar": str(u.display_avatar.url) if u.display_avatar else ""}
    for g in discord_client.guilds:
        _DISCORD_GUILDS_CACHE[str(g.id)] = {"name": g.name, "id": str(g.id)}
        if ALLOWED_GUILDS and str(g.id) not in ALLOWED_GUILDS:
            continue
        for ch in g.text_channels:
            _DISCORD_CHANNELS_CACHE[str(ch.id)] = {"name": ch.name, "guild": g.name, "guild_id": str(g.id), "guild_name": g.name}
    print(f"[Discord] Cache: {len(_DISCORD_CHANNELS_CACHE)} channels in {len(_DISCORD_GUILDS_CACHE)} guilds")

if discord_client:
    @discord_client.event
    async def on_ready():
        print(f"[Discord] ✅ Logged in as {discord_client.user}")
        print(f"[Discord] Mode: {'SELF-BOT' if _SELF_BOT else 'BOT'}")
        _refresh_discord_cache()

    @discord_client.event
    async def on_guild_channel_create(channel):
        _refresh_discord_cache()

    @discord_client.event
    async def on_guild_channel_delete(channel):
        _refresh_discord_cache()

    @discord_client.event
    async def on_guild_join(guild):
        _refresh_discord_cache()

    @discord_client.event
    async def on_guild_remove(guild):
        _refresh_discord_cache()

def _get_feeds_for_channel(ch_id):
    c = db()
    feeds = c.execute("SELECT * FROM discord_feeds WHERE channel_id=? AND enabled=1", (ch_id,)).fetchall()
    c.close()
    return feeds

def _feed_ignores_bot(feed, author_id):
    """هل هذا الـ feed يتجاهل هذا البوت؟"""
    try:
        ig = feed["ignore_bots"] or ""
        if not ig:
            return False
        bots = json.loads(ig)
        if not isinstance(bots, list):
            return False
        return str(author_id) in [str(x) for x in bots]
    except Exception:
        return False

def _track_bot(msg):
    """يتتبع البوتات التي ترسل في الرومات"""
    try:
        if not getattr(msg.author, "bot", False):
            return
        aid = str(msg.author.id)
        name = msg.author.name or msg.author.display_name or ""
        avatar = str(msg.author.display_avatar.url) if getattr(msg.author, "display_avatar", None) else ""
        c = db()
        existing = c.execute("SELECT seen_count FROM discord_bots WHERE id=?", (aid,)).fetchone()
        if existing:
            c.execute("UPDATE discord_bots SET last_seen=?, seen_count=seen_count+1, name=?, avatar=? WHERE id=?", (now(), name, avatar, aid))
        else:
            c.execute("INSERT INTO discord_bots(id,name,avatar,first_seen,last_seen,seen_count) VALUES(?,?,?,?,?,1)", (aid, name, avatar, now(), now()))
        c.commit()
        c.close()
    except Exception:
        pass

if discord_client:
    @discord_client.event
    async def on_message(msg):
        # تجاهل رسائل نفس الحساب
        if discord_client.user and msg.author.id == discord_client.user.id:
            return
        if not msg.guild:
            return
        if ALLOWED_GUILDS and str(msg.guild.id) not in ALLOWED_GUILDS:
            return

        ch_id = str(msg.channel.id)

        # تتبع البوتات
        if getattr(msg.author, "bot", False):
            _track_bot(msg)

        # ابحث عن feeds لهذا الروم
        feeds = _get_feeds_for_channel(ch_id)
        if not feeds:
            return

        # منع التكرار
        c = db()
        if c.execute("SELECT 1 FROM discord_seen WHERE message_id=?", (str(msg.id),)).fetchone():
            c.close()
            return
        c.execute("INSERT INTO discord_seen(message_id,ts) VALUES(?,?)", (str(msg.id), now()))
        c.commit()
        c.close()

        # استخراج البيانات
        data = extract_discord_message(msg)
        if not data["final_text"] and not data["image"]:
            return

        site_name = cfg("site_name", SITE_NAME)

        for feed in feeds:
            owner = feed["added_by"]

            # تجاهل البوتات المحددة
            if data["is_bot"] and _feed_ignores_bot(feed, data["author_id"]):
                continue

            if not rate_ok(f"discord:{owner}", max_per_min=MAX_PER_MIN_TG):
                continue

            # اختيار النص
            use_original = feed["use_original"] if "use_original" in feed.keys() else 1
            if use_original:
                text = data["final_text"] or ""
                if data["author_no_at"]:
                    text = f"<b>{data['author_no_at']}</b>\n\n{text}"
                if feed["template"]:
                    text = build_discord_text(feed["template"], data, site_name)
            else:
                tpl = feed["template"]
                if not tpl:
                    src = feed["source_type"]
                    if src == "twitter":
                        tpl = cfg("tpl_twitter") or cfg("tpl_discord")
                    elif src == "youtube":
                        tpl = cfg("tpl_youtube_dc") or cfg("tpl_discord")
                    else:
                        tpl = cfg("tpl_discord")
                text = build_discord_text(tpl, data, site_name)

            # AI rewrite
            if feed["use_ai"] if "use_ai" in feed.keys() else 0:
                if groq_available():
                    try:
                        ai_out = await groq_rewrite(text, feed["ai_prompt"] or "")
                        if ai_out:
                            text = ai_out
                    except Exception as e:
                        print(f"[AI Feed] {e}")

            # الصورة
            final_image = ""
            kw_rules = feed["keyword_rules"] if "keyword_rules" in feed.keys() else ""
            if kw_rules:
                final_image = match_keyword_image(kw_rules, text, "")
            if not final_image:
                fixed = feed["fixed_image"] if "fixed_image" in feed.keys() else ""
                if fixed:
                    final_image = fixed
                else:
                    final_image = data["image"]

            # الزر
            btn_text = feed["btn_text"] or cfg("btn_discord", "عرض الروم")
            room_url = feed["room_url"] if "room_url" in feed.keys() and feed["room_url"] else data["message_url"]

            # القنوات المستهدفة
            target_ids = []
            try:
                raw = feed["target_tg_ids"] or ""
                target_ids = [int(x) for x in json.loads(raw)] if raw else []
            except Exception:
                target_ids = []

            c2 = db()
            if target_ids:
                placeholders = ",".join("?" * len(target_ids))
                tgs = c2.execute(f"SELECT * FROM tg_channels WHERE added_by=? AND enabled=1 AND id IN ({placeholders})", (owner, *target_ids)).fetchall()
            else:
                tgs = c2.execute("SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (owner,)).fetchall()

            c2.execute(
                "INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) VALUES(?,?,?,?,?,?,'discord',?,0)",
                (owner, data["author_no_at"] or "رسالة ديسكورد", strip_html_simple(text)[:500], final_image, btn_text, room_url, now()),
            )
            c2.commit()
            c2.close()

            asyncio.create_task(push_send_to_user(owner, data["author_no_at"] or "رسالة ديسكورد", strip_html_simple(text)[:200], final_image, room_url, "discord"))

            for tg in tgs:
                await tg_send(tg["chat_id"], text, final_image, btn_text, room_url)

def strip_html_simple(s):
    return re.sub(r"<[^>]+>", "", str(s or "")).strip()

# ═══════════════════════════════════════════════════════════
# JOBS
# ═══════════════════════════════════════════════════════════
async def job_kick():
    c = db()
    rows = c.execute("SELECT * FROM kick_channels WHERE enabled=1 AND last_check<? ORDER BY last_check LIMIT ?", (now() - 90, BATCH_KICK)).fetchall()
    c.close()
    if not rows:
        return
    infos = {}
    sem = asyncio.Semaphore(8)
    async def f(r):
        async with sem:
            infos[r["slug"]] = await kick_fetch(r["slug"])
    await asyncio.gather(*(f(r) for r in rows), return_exceptions=True)
    updates, events = [], []
    t = now()
    for r in rows:
        info = infos.get(r["slug"])
        if not info:
            updates.append((t, r["id"]))
            continue
        updates.append((info["name"], info["avatar"], info["banner"], 1 if info["live"] else 0, info["title"], info["viewers"], info["thumb"], t, r["id"]))
        if info["live"] and not r["live"] and r["auto_send"]:
            events.append((r, info))
    c = db()
    for u in updates:
        if len(u) == 2:
            c.execute("UPDATE kick_channels SET last_check=? WHERE id=?", u)
        else:
            c.execute("UPDATE kick_channels SET name=?,avatar=?,banner=?,live=?,title=?,viewers=?,thumb=?,last_check=? WHERE id=?", u)
    c.commit()
    c.close()
    async def notify(r, info):
        tpl = r["msg"] or cfg("tpl_kick")
        text = tpl.replace("{name}", info["name"]).replace("{title}", info["title"]).replace("{url}", f"https://kick.com/{r['slug']}")
        btn_text = r["btn_text"] or cfg("btn_kick", "شاهد البث")
        c2 = db()
        tgs = c2.execute("SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (r["added_by"],)).fetchall()
        c2.execute("INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) VALUES(?,?,?,?,?,?,'kick',?,0)", (r["added_by"], info["name"] + " يبث الآن", info["title"], info["banner"] or info["thumb"], btn_text, f"https://kick.com/{r['slug']}", t))
        c2.commit()
        c2.close()
        asyncio.create_task(push_send_to_user(r["added_by"], info["name"] + " يبث الآن", info["title"] or "بث مباشر الآن", info["banner"] or info["thumb"], f"https://kick.com/{r['slug']}", f"kick:{r['id']}"))
        for tg in tgs:
            await tg_send(tg["chat_id"], text, info["banner"] or info["thumb"], btn_text, f"https://kick.com/{r['slug']}")
    await asyncio.gather(*(notify(r, info) for r, info in events), return_exceptions=True)

async def job_yt():
    c = db()
    rows = c.execute("SELECT * FROM yt_channels WHERE enabled=1 AND last_check<? ORDER BY last_check LIMIT ?", (now() - 300, BATCH_YT)).fetchall()
    c.close()
    if not rows:
        return
    feeds = {}
    sem = asyncio.Semaphore(8)
    async def f(r):
        async with sem:
            feeds[r["channel_id"]] = await yt_feed(r["channel_id"])
    await asyncio.gather(*(f(r) for r in rows), return_exceptions=True)
    updates, new_vids = [], []
    t = now()
    for r in rows:
        items = feeds.get(r["channel_id"])
        if not items:
            updates.append((t, r["id"]))
            continue
        latest = items[0]["id"]
        if r["last_video"] and latest != r["last_video"] and r["auto_send"]:
            fresh = []
            for it in items:
                if it["id"] == r["last_video"]:
                    break
                fresh.append(it)
            for v in reversed(fresh[:3]):
                new_vids.append((r, v))
        updates.append((latest, t, r["id"]))
    c = db()
    for u in updates:
        if len(u) == 2:
            c.execute("UPDATE yt_channels SET last_check=? WHERE id=?", u)
        else:
            c.execute("UPDATE yt_channels SET last_video=?,last_check=? WHERE id=?", u)
    c.commit()
    c.close()
    async def notify(r, v):
        thumb = f"https://i.ytimg.com/vi/{v['id']}/maxresdefault.jpg"
        url = f"https://youtube.com/watch?v={v['id']}"
        tpl = r["msg"] or cfg("tpl_yt")
        text = tpl.replace("{name}", r["name"]).replace("{title}", v["title"]).replace("{url}", url)
        btn_text = r["btn_text"] or cfg("btn_yt", "شاهد الفيديو")
        c2 = db()
        c2.execute("INSERT OR IGNORE INTO recent_videos(video_id,ch_name,title,thumb,url,ts,added_by) VALUES(?,?,?,?,?,?,?)", (v["id"], r["name"], v["title"], thumb, url, t, r["added_by"]))
        c2.execute("INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) VALUES(?,?,?,?,?,?,'yt',?,0)", (r["added_by"], f"فيديو جديد من {r['name']}", v["title"], thumb, btn_text, url, t))
        tgs = c2.execute("SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (r["added_by"],)).fetchall()
        c2.commit()
        c2.close()
        asyncio.create_task(push_send_to_user(r["added_by"], f"فيديو جديد من {r['name']}", v["title"], thumb, url, f"yt:{v['id']}"))
        for tg in tgs:
            await tg_send(tg["chat_id"], text, thumb, btn_text, url)
    await asyncio.gather(*(notify(r, v) for r, v in new_vids), return_exceptions=True)

async def job_cleanup():
    c = db()
    c.execute("DELETE FROM discord_seen WHERE ts<?", (now() - 7 * 86400,))
    c.execute("DELETE FROM sessions WHERE expires<?", (now(),))
    c.execute("DELETE FROM rate_limits WHERE ts<?", (now() - 3600,))
    c.execute("DELETE FROM security_log WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY id DESC) rn FROM security_log) WHERE rn > 5000)")
    c.execute("DELETE FROM recent_videos WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY added_by ORDER BY ts DESC) rn FROM recent_videos) WHERE rn > 12)")
    c.execute("DELETE FROM notifs WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY username ORDER BY ts DESC) rn FROM notifs) WHERE rn > 60)")
    c.execute("DELETE FROM suggestions WHERE ts<?", (now() - 90 * 86400,))
    c.commit()
    c.close()

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app):
    init_db()
    scheduler.add_job(job_kick, "interval", seconds=90)
    scheduler.add_job(job_yt, "interval", seconds=300)
    scheduler.add_job(job_cleanup, "interval", hours=6)
    scheduler.start()

    # 🆕 تشغيل الديسكورد حسب الإعدادات
    if discord_client and DISCORD_TOKEN:
        try:
            asyncio.create_task(discord_client.start(DISCORD_TOKEN))
            print(f"[Discord] 🚀 Starting in mode: {_DISCORD_MODE}")
        except Exception as e:
            print(f"[Discord] Start error: {e}")
    elif not DISCORD_ENABLE:
        print("[Discord] ⛔ Disabled via env")
    else:
        print("[Discord] ⚠️ No token")

    if push_available():
        print("[Push] Enabled")
    else:
        print("[Push] VAPID missing")
    if groq_available():
        print("[Groq] ✅ Enabled")
    else:
        print("[Groq] ⚠️ No API key")
    yield
    scheduler.shutdown(wait=False)

app = FastAPI(lifespan=lifespan)

# ═══════════════════════════════════════════════════════════
# API — BOOT / GUEST
# ═══════════════════════════════════════════════════════════
@app.get("/api/boot")
async def boot(request: Request):
    theme = get_site_theme()
    maintenance = cfg("maintenance", "0") == "1"
    return {
        "site_name": cfg("site_name", SITE_NAME),
        "site_sub": cfg("site_sub"),
        "hero_title": cfg("hero_title"),
        "hero_accent": cfg("hero_accent"),
        "hero_text": cfg("hero_text"),
        "guest_mode": cfg("guest_mode", "1") == "1",
        "guest_blur": int(cfg("guest_blur", "14")),
        "has_telegram": bool(TELEGRAM_TOKEN),
        "has_discord": bool(DISCORD_TOKEN),
        "has_push": push_available(),
        "has_groq": groq_available(),
        "discord_watching": len(_DISCORD_CHANNELS_CACHE),
        "theme": theme,
        "site_logo": cfg("site_logo", ""),
        "maintenance": maintenance,
        "maintenance_text": cfg("maintenance_text", "الموقع في صيانة مؤقتة — نرجع قريباً"),
        "bot_invite_url": cfg("bot_invite_url", ""),
        "bot_name_custom": cfg("bot_name_custom", "Respect Live Bot"),
        "bot_ready": discord_client.is_ready() if discord_client else False,
        "self_bot_mode": _SELF_BOT,
        "discord_mode": _DISCORD_MODE,  # 🆕
        "discord_enabled": DISCORD_ENABLE,  # 🆕
    }

@app.get("/api/guest-preview")
async def guest_preview():
    if cfg("guest_mode", "1") != "1":
        raise HTTPException(403, "وضع الزائر معطل")
    c = db()
    kc = c.execute("SELECT COUNT(*) n FROM kick_channels WHERE enabled=1").fetchone()["n"]
    yc = c.execute("SELECT COUNT(*) n FROM yt_channels WHERE enabled=1").fetchone()["n"]
    tc = c.execute("SELECT COUNT(*) n FROM tg_channels WHERE enabled=1").fetchone()["n"]
    live = c.execute("SELECT slug, name, avatar, title, viewers, thumb FROM kick_channels WHERE live=1 AND enabled=1 LIMIT 6").fetchall()
    c.close()
    return {"counts": {"kick": kc, "yt": yc, "tg": tc}, "live": [dict(r) for r in live]}

# ═══════════════════════════════════════════════════════════
# API — AUTH
# ═══════════════════════════════════════════════════════════
@app.post("/api/login")
async def login(request: Request, response: Response, u: str = Form(...), p: str = Form(...)):
    u = u.strip()[:60]
    ip = request.client.host if request.client else ""
    c = db()
    row = c.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
    c.close()
    if not row:
        log_sec(u, "login_fail", "no user", ip)
        return JSONResponse({"error": "بيانات خاطئة"}, 401)
    row = dict(row)
    if row["banned"]:
        log_sec(u, "login_banned", "", ip)
        return JSONResponse({"error": "حساب محظور"}, 403)
    if not secrets.compare_digest(hash_pw(p, row["salt"]), row["pass_hash"]):
        log_sec(u, "login_fail", "bad pass", ip)
        return JSONResponse({"error": "بيانات خاطئة"}, 401)
    if cfg("maintenance", "0") == "1" and row["role"] != "owner":
        return JSONResponse({"error": "الموقع في صيانة — حاول لاحقاً"}, 503)
    tok = new_session(row["username"])
    c = db()
    c.execute("UPDATE users SET last_login=? WHERE id=?", (now(), row["id"]))
    c.commit()
    c.close()
    log_sec(u, "login_ok", "", ip)
    response.set_cookie("rl_sid", tok, max_age=SESSION_TTL, httponly=True, samesite="lax", secure=False)
    return {"ok": True, "user": {"username": row["username"], "role": row["role"]}}

@app.post("/api/logout")
async def logout(request: Request, response: Response):
    tok = request.cookies.get("rl_sid")
    if tok:
        c = db()
        c.execute("DELETE FROM sessions WHERE token=?", (tok,))
        c.commit()
        c.close()
    response.delete_cookie("rl_sid")
    return {"ok": True}

@app.get("/api/me")
async def me(request: Request):
    u = auth(request)
    if not u:
        return JSONResponse({"error": "غير مسجل", "auth": False}, 401)
    return {
        "user": {
            "username": u["username"], "display": u["display"], "role": u["role"],
            "avatar": u.get("avatar", ""), "can_discord": u.get("can_discord", 0) == 1,
            "created": u.get("created", 0), "last_login": u.get("last_login", 0),
        },
        "limits": get_user_limits(u["username"], u["role"]),
        "usage": {
            "kick": limit_info(u["username"], "kick", u["role"])["used"],
            "yt": limit_info(u["username"], "yt", u["role"])["used"],
            "tg": limit_info(u["username"], "tg", u["role"])["used"]
        },
        "tpl_kick": cfg("tpl_kick"), "tpl_yt": cfg("tpl_yt"),
        "tpl_discord": cfg("tpl_discord"), "tpl_twitter": cfg("tpl_twitter"), "tpl_youtube_dc": cfg("tpl_youtube_dc"),
        "btn_kick": cfg("btn_kick", "شاهد البث"),
        "btn_yt": cfg("btn_yt", "شاهد الفيديو"),
        "btn_tg": cfg("btn_tg", "عرض القناة"),
        "btn_discord": cfg("btn_discord", "عرض الروم"),
        "site_name": cfg("site_name", SITE_NAME),
        "site_logo": cfg("site_logo", ""),
        "site_theme": cfg("site_theme", "default"),
        "has_telegram": bool(TELEGRAM_TOKEN),
        "has_discord": bool(DISCORD_TOKEN),
        "has_push": push_available(),
        "has_groq": groq_available(),
        "bot_ready": discord_client.is_ready() if discord_client else False,
        "bot_name_custom": cfg("bot_name_custom", "Respect Live Bot"),
        "bot_invite_url": cfg("bot_invite_url", ""),
        "self_bot_mode": _SELF_BOT,
        "discord_mode": _DISCORD_MODE,  # 🆕
        "discord_enabled": DISCORD_ENABLE,  # 🆕
    }

@app.patch("/api/me/profile")
async def update_profile(request: Request):
    u = require_auth(request)
    body = await request.json()
    sets, vals = [], []
    if "display" in body:
        d = str(body["display"]).strip()[:60]
        if d:
            sets.append("display=?")
            vals.append(d)
    if "avatar" in body:
        av = str(body["avatar"]).strip()[:500]
        sets.append("avatar=?")
        vals.append(av)
    if not sets:
        return {"ok": True}
    vals.append(u["username"])
    c = db()
    c.execute(f"UPDATE users SET {', '.join(sets)} WHERE username=?", vals)
    c.commit()
    c.close()
    return {"ok": True}

# ═══════════════════════════════════════════════════════════
# API — HOME STATS
# ═══════════════════════════════════════════════════════════
@app.get("/api/home-stats")
async def home_stats(request: Request):
    u = require_auth(request)
    c = db()
    my = {
        "kick": c.execute("SELECT COUNT(*) n FROM kick_channels WHERE added_by=?", (u["username"],)).fetchone()["n"],
        "yt": c.execute("SELECT COUNT(*) n FROM yt_channels WHERE added_by=?", (u["username"],)).fetchone()["n"],
        "tg": c.execute("SELECT COUNT(*) n FROM tg_channels WHERE added_by=?", (u["username"],)).fetchone()["n"],
        "feeds": c.execute("SELECT COUNT(*) n FROM discord_feeds WHERE added_by=?", (u["username"],)).fetchone()["n"],
        "live": c.execute("SELECT COUNT(*) n FROM kick_channels WHERE added_by=? AND live=1 AND enabled=1", (u["username"],)).fetchone()["n"],
        "notifs_unread": c.execute("SELECT COUNT(*) n FROM notifs WHERE username=? AND is_read=0", (u["username"],)).fetchone()["n"],
        "videos": c.execute("SELECT COUNT(*) n FROM recent_videos WHERE added_by=?", (u["username"],)).fetchone()["n"],
    }
    global_stats = {
        "users": c.execute("SELECT COUNT(*) n FROM users WHERE active=1 AND banned=0").fetchone()["n"],
        "total_kick": c.execute("SELECT COUNT(*) n FROM kick_channels WHERE enabled=1").fetchone()["n"],
        "total_yt": c.execute("SELECT COUNT(*) n FROM yt_channels WHERE enabled=1").fetchone()["n"],
        "total_tg": c.execute("SELECT COUNT(*) n FROM tg_channels WHERE enabled=1").fetchone()["n"],
        "total_live": c.execute("SELECT COUNT(*) n FROM kick_channels WHERE live=1 AND enabled=1").fetchone()["n"],
        "discord_channels": len(_DISCORD_CHANNELS_CACHE),
        "bot_ready": discord_client.is_ready() if discord_client else False,
    }
    live_now = c.execute(
        "SELECT slug, name, avatar, banner, thumb, title, viewers FROM kick_channels WHERE live=1 AND enabled=1 ORDER BY viewers DESC LIMIT 4"
    ).fetchall()
    videos = c.execute(
        "SELECT video_id, ch_name, title, thumb, url FROM recent_videos WHERE added_by=? ORDER BY ts DESC LIMIT 4",
        (u["username"],)
    ).fetchall()
    c.close()
    return {
        "my": my,
        "global": global_stats,
        "live_now": [dict(r) for r in live_now],
        "videos": [dict(r) for r in videos],
    }

# ═══════════════════════════════════════════════════════════
# API — CHANNELS
# ═══════════════════════════════════════════════════════════
@app.get("/api/channels/{kind}")
async def list_channels(kind: str, request: Request):
    u = require_auth(request)
    table = {"kick": "kick_channels", "yt": "yt_channels", "tg": "tg_channels"}.get(kind)
    if not table:
        raise HTTPException(404)
    c = db()
    if u["role"] == "owner":
        rows = c.execute(f"SELECT * FROM {table} ORDER BY id DESC").fetchall()
    else:
        rows = c.execute(f"SELECT * FROM {table} WHERE added_by=? ORDER BY id DESC", (u["username"],)).fetchall()
    c.close()
    return {"rows": [dict(r) for r in rows], "limits": limit_info(u["username"], kind, u["role"])}

@app.get("/api/channels/{kind}/suggestions")
async def channel_suggestions(kind: str, request: Request):
    u = require_auth(request)
    if kind not in ("kick", "yt", "tg"):
        raise HTTPException(404)
    table = {"kick": "kick_channels", "yt": "yt_channels", "tg": "tg_channels"}[kind]
    ic = {"kick": "slug", "yt": "channel_id", "tg": "chat_id"}[kind]
    c = db()
    defaults = c.execute("SELECT * FROM default_channels WHERE kind=? AND enabled=1 ORDER BY id DESC", (kind,)).fetchall()
    mine = set(r[ic] for r in c.execute(f"SELECT {ic} FROM {table} WHERE added_by=?", (u["username"],)).fetchall())
    c.close()
    return {"rows": [dict(r) for r in defaults if r["identifier"] not in mine]}

@app.post("/api/channels/{kind}")
async def add_channel(kind: str, request: Request):
    u = require_auth(request)
    if not rate_ok(f"add:{u['username']}", MAX_PER_MIN_CH):
        raise HTTPException(429, "عدد كبير من الإضافات")
    body = await request.json()
    c = db()
    t = now()
    warn = ""
    if kind == "kick":
        slug = re.sub(r"[^a-z0-9_-]", "", (body.get("slug") or "").lower().replace("@", ""))
        if not slug:
            c.close()
            return JSONResponse({"error": "اسم غير صالح"}, 400)
        if c.execute("SELECT 1 FROM kick_channels WHERE slug=? AND added_by=?", (slug, u["username"])).fetchone():
            c.close()
            return JSONResponse({"error": "مضافة مسبقاً"}, 409)
        if not check_limit(u["username"], "kick", u["role"]):
            c.close()
            i = limit_info(u["username"], "kick", u["role"])
            return JSONResponse({"error": f"وصلت الحد الأقصى ({i['limit']})"}, 400)
        info = await kick_fetch(slug)
        c.execute(
            "INSERT INTO kick_channels(slug,name,avatar,banner,msg,btn_text,enabled,auto_send,live,title,viewers,thumb,last_check,added_by,created) VALUES(?,?,?,?,?,?,1,1,?,?,?,?,?,?,?)",
            (slug, (info or {}).get("name") or slug, (info or {}).get("avatar") or "",
             (info or {}).get("banner") or "", body.get("msg", "")[:1500], body.get("btn_text", "")[:60],
             1 if (info or {}).get("live") else 0, (info or {}).get("title") or "",
             (info or {}).get("viewers") or 0, (info or {}).get("thumb") or "", t, u["username"], t)
        )
        if not TELEGRAM_TOKEN:
            warn = "⚠️ البوت غير مضاف — لن يتم إرسال الإشعارات"
    elif kind == "yt":
        info = await yt_resolve(body.get("channel_id") or body.get("input") or "")
        if not info:
            c.close()
            return JSONResponse({"error": "تعذّر التعرف على القناة"}, 400)
        cid = info["channel_id"]
        if c.execute("SELECT 1 FROM yt_channels WHERE channel_id=? AND added_by=?", (cid, u["username"])).fetchone():
            c.close()
            return JSONResponse({"error": "مضافة مسبقاً"}, 409)
        if not check_limit(u["username"], "yt", u["role"]):
            c.close()
            i = limit_info(u["username"], "yt", u["role"])
            return JSONResponse({"error": f"وصلت الحد الأقصى ({i['limit']})"}, 400)
        feed = await yt_feed(cid)
        last = feed[0]["id"] if feed else ""
        c.execute(
            "INSERT INTO yt_channels(channel_id,handle,name,avatar,banner,msg,btn_text,enabled,auto_send,last_video,last_check,added_by,created) VALUES(?,?,?,?,?,?,?,1,1,?,?,?,?)",
            (cid, "", info["name"] or cid, info.get("avatar") or "",
             info.get("banner") or "", body.get("msg", "")[:1500], body.get("btn_text", "")[:60],
             last, t, u["username"], t)
        )
        if not TELEGRAM_TOKEN:
            warn = "⚠️ البوت غير مضاف — لن يتم إرسال الإشعارات"
    elif kind == "tg":
        raw = (body.get("chat_id") or "").strip()
        cid = norm_chat(raw)
        if not cid:
            c.close()
            return JSONResponse({"error": "معرّف غير صالح"}, 400)
        if c.execute("SELECT 1 FROM tg_channels WHERE chat_id=? AND added_by=?", (cid, u["username"])).fetchone():
            c.close()
            return JSONResponse({"error": "مضافة مسبقاً"}, 409)
        if not check_limit(u["username"], "tg", u["role"]):
            c.close()
            i = limit_info(u["username"], "tg", u["role"])
            return JSONResponse({"error": f"وصلت الحد الأقصى ({i['limit']})"}, 400)
        info = await tg_get_chat_info(cid)
        name = (info or {}).get("name") or body.get("name") or cid
        uname = (info or {}).get("username") or ""
        avatar = (info or {}).get("avatar") or ""
        real_cid = (info or {}).get("chat_id") or cid
        c.execute(
            "INSERT INTO tg_channels(chat_id,username,name,avatar,banner,enabled,added_by,created) VALUES(?,?,?,?,?,1,?,?)",
            (real_cid, uname, name, avatar, "", u["username"], t)
        )
        if not TELEGRAM_TOKEN:
            warn = "⚠️ توكن تيليجرام غير مضبوط"
        elif not info:
            warn = "⚠️ لم نتمكن من جلب بيانات القناة"
    else:
        c.close()
        raise HTTPException(404)
    c.commit()
    c.close()
    return {"ok": True, "warn": warn}

@app.post("/api/channels/{kind}/bulk-add")
async def bulk_add_suggestions(kind: str, request: Request):
    u = require_auth(request)
    if kind not in ("kick", "yt", "tg"):
        raise HTTPException(404)
    body = await request.json()
    ids = body.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return JSONResponse({"error": "لا توجد قنوات"}, 400)
    ids = [int(x) for x in ids if str(x).isdigit()][:50]
    if not ids:
        return JSONResponse({"error": "معرّفات غير صالحة"}, 400)
    info_lim = limit_info(u["username"], kind, u["role"])
    if u["role"] != "owner" and info_lim["remaining"] < len(ids):
        return JSONResponse({"error": f"الحد المتبقي {info_lim['remaining']} فقط"}, 400)
    c = db()
    rows = c.execute(f"SELECT * FROM default_channels WHERE id IN ({','.join('?' * len(ids))}) AND kind=? AND enabled=1", (*ids, kind)).fetchall()
    c.close()
    if not rows:
        return JSONResponse({"error": "لا توجد قنوات"}, 404)
    added, failed, errors = 0, 0, []
    remaining = info_lim["remaining"] if u["role"] != "owner" else 9999
    for row in rows:
        if u["role"] != "owner" and remaining <= 0:
            errors.append(f"{row['name']}: وصلت الحد")
            failed += 1
            continue
        try:
            c = db()
            t = now()
            if kind == "kick":
                if c.execute("SELECT 1 FROM kick_channels WHERE slug=? AND added_by=?", (row["identifier"], u["username"])).fetchone():
                    c.close()
                    failed += 1
                    errors.append(f"{row['name']}: مضافة مسبقاً")
                    continue
                inf = await kick_fetch(row["identifier"])
                c.execute(
                    "INSERT INTO kick_channels(slug,name,avatar,banner,msg,btn_text,enabled,auto_send,live,title,viewers,thumb,last_check,added_by,created) VALUES(?,?,?,?,?,?,1,1,?,?,?,?,?,?,?)",
                    (row["identifier"], (inf or {}).get("name") or row["name"] or row["identifier"],
                     (inf or {}).get("avatar") or row["avatar"] or "", (inf or {}).get("banner") or "",
                     "", "", 1 if (inf or {}).get("live") else 0,
                     (inf or {}).get("title") or "", (inf or {}).get("viewers") or 0,
                     (inf or {}).get("thumb") or "", t, u["username"], t)
                )
            elif kind == "yt":
                if c.execute("SELECT 1 FROM yt_channels WHERE channel_id=? AND added_by=?", (row["identifier"], u["username"])).fetchone():
                    c.close()
                    failed += 1
                    errors.append(f"{row['name']}: مضافة مسبقاً")
                    continue
                feed = await yt_feed(row["identifier"])
                last = feed[0]["id"] if feed else ""
                yinfo = await yt_resolve(row["identifier"])
                banner = (yinfo or {}).get("banner") or ""
                c.execute(
                    "INSERT INTO yt_channels(channel_id,handle,name,avatar,banner,msg,btn_text,enabled,auto_send,last_video,last_check,added_by,created) VALUES(?,?,?,?,?,?,?,1,1,?,?,?,?)",
                    (row["identifier"], "", row["name"] or row["identifier"],
                     row["avatar"] or "", banner, "", "", last, t, u["username"], t)
                )
            elif kind == "tg":
                if c.execute("SELECT 1 FROM tg_channels WHERE chat_id=? AND added_by=?", (row["identifier"], u["username"])).fetchone():
                    c.close()
                    failed += 1
                    errors.append(f"{row['name']}: مضافة مسبقاً")
                    continue
                tg_info = await tg_get_chat_info(row["identifier"])
                name = (tg_info or {}).get("name") or row["name"] or row["identifier"]
                uname = (tg_info or {}).get("username") or (row["identifier"] if row["identifier"].startswith("@") else "")
                avatar = (tg_info or {}).get("avatar") or row["avatar"] or ""
                real_cid = (tg_info or {}).get("chat_id") or row["identifier"]
                c.execute(
                    "INSERT INTO tg_channels(chat_id,username,name,avatar,banner,enabled,added_by,created) VALUES(?,?,?,?,?,1,?,?)",
                    (real_cid, uname, name, avatar, "", u["username"], t)
                )
            c.commit()
            c.close()
            added += 1
            if u["role"] != "owner":
                remaining -= 1
        except Exception as e:
            failed += 1
            errors.append(f"{row['name']}: {str(e)[:60]}")
    return {"ok": True, "added": added, "failed": failed, "errors": errors}

@app.delete("/api/channels/{kind}/{cid}")
async def del_channel(kind: str, cid: int, request: Request):
    u = require_auth(request)
    table = {"kick": "kick_channels", "yt": "yt_channels", "tg": "tg_channels"}.get(kind)
    if not table:
        raise HTTPException(404)
    c = db()
    row = c.execute(f"SELECT * FROM {table} WHERE id=?", (cid,)).fetchone()
    if not row:
        c.close()
        raise HTTPException(404)
    if u["role"] != "owner" and row["added_by"] != u["username"]:
        c.close()
        raise HTTPException(403)
    c.execute(f"DELETE FROM {table} WHERE id=?", (cid,))
    c.commit()
    c.close()
    return {"ok": True}

@app.patch("/api/channels/{kind}/{cid}")
async def patch_channel(kind: str, cid: int, request: Request):
    u = require_auth(request)
    table = {"kick": "kick_channels", "yt": "yt_channels", "tg": "tg_channels"}.get(kind)
    if not table:
        raise HTTPException(404)
    body = await request.json()
    c = db()
    row = c.execute(f"SELECT * FROM {table} WHERE id=?", (cid,)).fetchone()
    if not row:
        c.close()
        raise HTTPException(404)
    if u["role"] != "owner" and row["added_by"] != u["username"]:
        c.close()
        raise HTTPException(403)
    sets, vals = [], []
    if "enabled" in body:
        sets.append("enabled=?")
        vals.append(1 if body["enabled"] else 0)
    if "auto_send" in body and kind != "tg":
        sets.append("auto_send=?")
        vals.append(1 if body["auto_send"] else 0)
    if "msg" in body and kind != "tg":
        sets.append("msg=?")
        vals.append(str(body["msg"])[:1500])
    if "btn_text" in body and kind != "tg":
        sets.append("btn_text=?")
        vals.append(str(body["btn_text"])[:60])
    if "name" in body:
        sets.append("name=?")
        vals.append(str(body["name"])[:80])
    if "avatar" in body and kind == "tg":
        sets.append("avatar=?")
        vals.append(str(body["avatar"])[:500])
    if "banner" in body and kind in ("yt", "tg"):
        sets.append("banner=?")
        vals.append(str(body["banner"])[:500])
    if sets:
        vals.append(cid)
        c.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?", vals)
        c.commit()
    c.close()
    return {"ok": True}

@app.post("/api/channels/tg/{cid}/refresh")
async def refresh_tg_channel(cid: int, request: Request):
    u = require_auth(request)
    c = db()
    row = c.execute("SELECT * FROM tg_channels WHERE id=?", (cid,)).fetchone()
    if not row:
        c.close()
        raise HTTPException(404)
    if u["role"] != "owner" and row["added_by"] != u["username"]:
        c.close()
        raise HTTPException(403)
    info = await tg_get_chat_info(row["chat_id"])
    c.close()
    if not info:
        return JSONResponse({"error": "تعذّر جلب بيانات القناة"}, 400)
    c = db()
    c.execute("UPDATE tg_channels SET name=?, username=?, avatar=?, chat_id=? WHERE id=?",
              (info["name"], info["username"] or row["username"], info["avatar"] or row["avatar"], info["chat_id"], cid))
    c.commit()
    c.close()
    return {"ok": True}

@app.post("/api/channels/yt/{cid}/refresh")
async def refresh_yt_channel(cid: int, request: Request):
    u = require_auth(request)
    c = db()
    row = c.execute("SELECT * FROM yt_channels WHERE id=?", (cid,)).fetchone()
    if not row:
        c.close()
        raise HTTPException(404)
    if u["role"] != "owner" and row["added_by"] != u["username"]:
        c.close()
        raise HTTPException(403)
    info = await yt_resolve(row["channel_id"])
    c.close()
    if not info:
        return JSONResponse({"error": "تعذّر جلب البيانات"}, 400)
    c = db()
    c.execute("UPDATE yt_channels SET name=?, avatar=?, banner=? WHERE id=?",
              (info["name"] or row["name"], info.get("avatar") or row["avatar"], info.get("banner") or row["banner"], cid))
    c.commit()
    c.close()
    return {"ok": True}

# ═══════════════════════════════════════════════════════════
# API — SEND
# ═══════════════════════════════════════════════════════════
@app.get("/api/send/prefill")
async def send_prefill(request: Request):
    u = require_auth(request)
    c = db()
    if u["role"] == "owner":
        tgs = c.execute("SELECT id, name, username, avatar, enabled, added_by FROM tg_channels ORDER BY id DESC").fetchall()
        users = c.execute("SELECT id, username, display FROM users WHERE active=1 AND banned=0 ORDER BY username").fetchall()
    else:
        tgs = c.execute("SELECT id, name, username, avatar, enabled, added_by FROM tg_channels WHERE added_by=? ORDER BY id DESC", (u["username"],)).fetchall()
        users = []
    c.close()
    return {
        "tgs": [dict(r) for r in tgs],
        "users": [dict(r) for r in users],
        "is_owner": u["role"] == "owner",
    }

@app.post("/api/send")
async def send_manual(request: Request):
    u = require_auth(request)
    if not rate_ok(f"send:{u['username']}", max_per_min=10):
        return JSONResponse({"error": "عدد كبير من الإرسالات"}, 429)
    body = await request.json()
    text = (body.get("text") or "").strip()
    image = (body.get("image") or "").strip()[:500]
    btn_text = (body.get("btn_text") or "").strip()[:60]
    btn_url = (body.get("btn_url") or "").strip()[:2000]
    if not text and not image:
        return JSONResponse({"error": "لا يوجد محتوى"}, 400)
    if btn_url and not btn_url.startswith("http"):
        return JSONResponse({"error": "رابط الزر غير صالح"}, 400)
    out = {"tg_sent": 0, "tg_failed": 0, "users": 0}
    tg_mode = (body.get("tg") or {}).get("mode", "none")
    tg_ids = (body.get("tg") or {}).get("ids", [])
    tgs_to_send = []
    if tg_mode == "all" and TELEGRAM_TOKEN:
        c = db()
        if u["role"] == "owner":
            tgs_to_send = c.execute("SELECT * FROM tg_channels WHERE enabled=1").fetchall()
        else:
            tgs_to_send = c.execute("SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (u["username"],)).fetchall()
        c.close()
    elif tg_mode == "pick" and TELEGRAM_TOKEN and tg_ids:
        ids_clean = [int(x) for x in tg_ids if str(x).isdigit()][:50]
        if ids_clean:
            c = db()
            if u["role"] == "owner":
                tgs_to_send = c.execute(f"SELECT * FROM tg_channels WHERE id IN ({','.join('?'*len(ids_clean))})", tuple(ids_clean)).fetchall()
            else:
                tgs_to_send = c.execute(f"SELECT * FROM tg_channels WHERE added_by=? AND id IN ({','.join('?'*len(ids_clean))})", (u["username"], *ids_clean)).fetchall()
            c.close()
    for tg in tgs_to_send:
        try:
            r = await tg_send(tg["chat_id"], text, image, btn_text, btn_url)
            if r:
                out["tg_sent"] += 1
            else:
                out["tg_failed"] += 1
        except Exception:
            out["tg_failed"] += 1
    users_mode = (body.get("users") or {}).get("mode", "none")
    if users_mode != "none" and u["role"] == "owner":
        users_ids = (body.get("users") or {}).get("ids", [])
        c = db()
        if users_mode == "all":
            us = c.execute("SELECT username, display FROM users WHERE active=1 AND banned=0").fetchall()
        else:
            ids_clean = [int(x) for x in users_ids if str(x).isdigit()][:500]
            us = c.execute(f"SELECT username, display FROM users WHERE active=1 AND banned=0 AND id IN ({','.join('?'*len(ids_clean))})", tuple(ids_clean)).fetchall() if ids_clean else []
        c.close()
        for target in us:
            c = db()
            c.execute(
                "INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) VALUES(?,?,?,?,?,?,'admin',?,0)",
                (target["username"], "رسالة من الإدارة", text[:500], image, btn_text, btn_url, now())
            )
            c.commit()
            c.close()
            asyncio.create_task(push_send_to_user(target["username"], "رسالة من الإدارة", text[:200], image, btn_url or "/", "admin"))
            out["users"] += 1
    return {"ok": True, "result": out}

# ═══════════════════════════════════════════════════════════
# API — DISCORD
# ═══════════════════════════════════════════════════════════
@app.get("/api/discord/channels")
async def discord_available_channels(request: Request):
    require_discord_access(request)
    return {
        "channels": _DISCORD_CHANNELS_CACHE,
        "guilds": _DISCORD_GUILDS_CACHE,
        "watching": list(_DISCORD_CHANNELS_CACHE.keys()) if not WATCH_CHANNELS else WATCH_CHANNELS,
        "auto_discovery": not bool(WATCH_CHANNELS),
        "bot_ready": discord_client.is_ready() if discord_client else False,
        "bot_info": _DISCORD_BOT_INFO,
        "bot_name_custom": cfg("bot_name_custom", "Respect Live Bot"),
        "bot_invite_url": cfg("bot_invite_url", ""),
        "self_bot_mode": _SELF_BOT,
        "discord_mode": _DISCORD_MODE,  # 🆕
    }

@app.post("/api/discord/refresh")
async def discord_refresh(request: Request):
    require_discord_access(request)
    _refresh_discord_cache()
    return {"ok": True, "channels": len(_DISCORD_CHANNELS_CACHE), "guilds": len(_DISCORD_GUILDS_CACHE), "bot_ready": discord_client.is_ready() if discord_client else False}

@app.get("/api/discord/bots")
async def discord_bots(request: Request):
    """يرجع قائمة البوتات التي ترسل في الرومات (لمساعدتها في ignore_bots)"""
    require_discord_access(request)
    c = db()
    rows = c.execute("SELECT id, name, avatar, last_seen, seen_count FROM discord_bots ORDER BY last_seen DESC LIMIT 200").fetchall()
    c.close()
    return {"rows": [dict(r) for r in rows]}

@app.get("/api/discord/feeds")
async def list_feeds(request: Request):
    u = require_discord_access(request)
    c = db()
    rows = c.execute("SELECT * FROM discord_feeds WHERE added_by=? ORDER BY id DESC", (u["username"],)).fetchall()
    tgs = c.execute("SELECT id, name, username, avatar, enabled FROM tg_channels WHERE added_by=? ORDER BY id DESC", (u["username"],)).fetchall()
    c.close()
    return {
        "rows": [dict(r) for r in rows],
        "known_channels": _DISCORD_CHANNELS_CACHE,
        "guilds": _DISCORD_GUILDS_CACHE,
        "watching": list(_DISCORD_CHANNELS_CACHE.keys()) if not WATCH_CHANNELS else WATCH_CHANNELS,
        "auto_discovery": not bool(WATCH_CHANNELS),
        "bot_ready": discord_client.is_ready() if discord_client else False,
        "bot_info": _DISCORD_BOT_INFO,
        "bot_name_custom": cfg("bot_name_custom", "Respect Live Bot"),
        "bot_invite_url": cfg("bot_invite_url", ""),
        "self_bot_mode": _SELF_BOT,
        "discord_mode": _DISCORD_MODE,  # 🆕
        "my_tgs": [dict(r) for r in tgs],
    }

@app.post("/api/discord/feeds")
async def add_feed(request: Request):
    u = require_discord_access(request)
    body = await request.json()
    ch = str(body.get("channel_id") or "").strip()
    if not ch or not ch.isdigit():
        return JSONResponse({"error": "channel_id يجب أن يكون رقماً"}, 400)
    if ch not in _DISCORD_CHANNELS_CACHE and (not WATCH_CHANNELS or ch not in WATCH_CHANNELS):
        if not _DISCORD_CHANNELS_CACHE:
            return JSONResponse({"error": "البوت لم يكتشف الرومات بعد — اضغط تحديث"}, 400)
        return JSONResponse({"error": "الروم غير موجود في السيرفر"}, 400)
    tpl = str(body.get("template") or "")[:2000]
    btn_text = str(body.get("btn_text") or "عرض الروم")[:60]
    name = str(body.get("channel_name") or "")[:100]
    source = str(body.get("source_type") or "generic")[:20]
    guild_id = str(body.get("guild_id") or "")[:30]
    use_original = 1 if body.get("use_original", True) else 0
    ignore_bots = body.get("ignore_bots") or []
    if not isinstance(ignore_bots, list):
        ignore_bots = []
    ignore_bots = [str(x) for x in ignore_bots][:50]
    keyword_rules = body.get("keyword_rules") or []
    if not isinstance(keyword_rules, list):
        keyword_rules = []
    fixed_image = str(body.get("fixed_image") or "")[:500]
    room_url = str(body.get("room_url") or "")[:500]
    use_ai = 1 if body.get("use_ai") else 0
    ai_prompt = str(body.get("ai_prompt") or "")[:2000]
    target_ids = body.get("target_tg_ids") or []
    if not isinstance(target_ids, list):
        target_ids = []
    target_ids = [int(x) for x in target_ids if str(x).isdigit()][:50]
    if not name and ch in _DISCORD_CHANNELS_CACHE:
        name = _DISCORD_CHANNELS_CACHE[ch]["name"]
    c = db()
    if c.execute("SELECT 1 FROM discord_feeds WHERE channel_id=? AND added_by=?", (ch, u["username"])).fetchone():
        c.close()
        return JSONResponse({"error": "مضاف مسبقاً"}, 409)
    c.execute(
        "INSERT INTO discord_feeds(channel_id,channel_name,guild_id,template,btn_text,source_type,target_tg_ids,enabled,use_original,ignore_bots,keyword_rules,fixed_image,room_url,use_ai,ai_prompt,added_by,created) VALUES(?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?)",
        (ch, name, guild_id, tpl, btn_text, source,
         json.dumps(target_ids), use_original,
         json.dumps(ignore_bots), json.dumps(keyword_rules),
         fixed_image, room_url, use_ai, ai_prompt, u["username"], now())
    )
    c.commit()
    c.close()
    return {"ok": True}

@app.patch("/api/discord/feeds/{fid}")
async def patch_feed(fid: int, request: Request):
    u = require_discord_access(request)
    body = await request.json()
    c = db()
    row = c.execute("SELECT * FROM discord_feeds WHERE id=?", (fid,)).fetchone()
    if not row:
        c.close()
        raise HTTPException(404)
    if u["role"] != "owner" and row["added_by"] != u["username"]:
        c.close()
        raise HTTPException(403)
    sets, vals = [], []
    if "template" in body:
        sets.append("template=?")
        vals.append(str(body["template"])[:2000])
    if "btn_text" in body:
        sets.append("btn_text=?")
        vals.append(str(body["btn_text"])[:60])
    if "enabled" in body:
        sets.append("enabled=?")
        vals.append(1 if body["enabled"] else 0)
    if "use_original" in body:
        sets.append("use_original=?")
        vals.append(1 if body["use_original"] else 0)
    if "fixed_image" in body:
        sets.append("fixed_image=?")
        vals.append(str(body["fixed_image"])[:500])
    if "room_url" in body:
        sets.append("room_url=?")
        vals.append(str(body["room_url"])[:500])
    if "use_ai" in body:
        sets.append("use_ai=?")
        vals.append(1 if body["use_ai"] else 0)
    if "ai_prompt" in body:
        sets.append("ai_prompt=?")
        vals.append(str(body["ai_prompt"])[:2000])
    if "target_tg_ids" in body:
        tids = body["target_tg_ids"] or []
        if not isinstance(tids, list):
            tids = []
        tids = [int(x) for x in tids if str(x).isdigit()][:50]
        sets.append("target_tg_ids=?")
        vals.append(json.dumps(tids))
    if "ignore_bots" in body:
        bots = body["ignore_bots"] or []
        if not isinstance(bots, list):
            bots = []
        bots = [str(x) for x in bots][:50]
        sets.append("ignore_bots=?")
        vals.append(json.dumps(bots))
    if "keyword_rules" in body:
        rules = body["keyword_rules"] or []
        if not isinstance(rules, list):
            rules = []
        sets.append("keyword_rules=?")
        vals.append(json.dumps(rules))
    if sets:
        vals.append(fid)
        c.execute(f"UPDATE discord_feeds SET {', '.join(sets)} WHERE id=?", vals)
        c.commit()
    c.close()
    return {"ok": True}

@app.delete("/api/discord/feeds/{fid}")
async def del_feed(fid: int, request: Request):
    u = require_discord_access(request)
    c = db()
    row = c.execute("SELECT * FROM discord_feeds WHERE id=?", (fid,)).fetchone()
    if not row:
        c.close()
        raise HTTPException(404)
    if u["role"] != "owner" and row["added_by"] != u["username"]:
        c.close()
        raise HTTPException(403)
    c.execute("DELETE FROM discord_feeds WHERE id=?", (fid,))
    c.commit()
    c.close()
    return {"ok": True}

# ═══════════════════════════════════════════════════════════
# API — AI / GROQ
# ═══════════════════════════════════════════════════════════
@app.get("/api/ai/status")
async def ai_status(request: Request):
    require_auth(request)
    return {
        "available": groq_available(),
        "model": cfg("groq_model", "llama-3.3-70b-versatile"),
        "source": "env" if GROQ_API_KEY_ENV else ("db" if cfg("groq_api_key", "") else "none"),
    }

@app.post("/api/ai/rewrite")
async def ai_rewrite(request: Request):
    u = require_auth(request)
    if not rate_ok(f"ai:{u['username']}", max_per_min=10):
        return JSONResponse({"error": "عدد كبير من الطلبات"}, 429)
    if not groq_available():
        return JSONResponse({"error": "Groq غير مفعّل — أضف API key من لوحة التحكم"}, 400)
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "لا يوجد نص"}, 400)
    prompt = str(body.get("prompt") or "")[:2000]
    out = await groq_rewrite(text[:4000], prompt)
    if not out:
        return JSONResponse({"error": "فشل الاتصال بـ Groq"}, 500)
    return {"ok": True, "text": out}

@app.post("/api/admin/groq")
async def admin_groq(request: Request):
    require_owner(request)
    body = await request.json()
    if "api_key" in body:
        key = str(body["api_key"]).strip()[:200]
        if key and not key.startswith("gsk_"):
            return JSONResponse({"error": "API key يجب أن يبدأ بـ gsk_"}, 400)
        set_cfg("groq_api_key", key)
    if "model" in body:
        set_cfg("groq_model", str(body["model"]).strip()[:100] or "llama-3.3-70b-versatile")
    if body.get("test"):
        test_text = "مرحباً، اختبر الاتصال"
        out = await groq_rewrite(test_text, "أعد التحية فقط", None)
        return {"ok": True, "test": out or "فشل الاختبار"}
    return {"ok": True, "available": groq_available()}

# ═══════════════════════════════════════════════════════════
# API — NOTIFICATIONS
# ═══════════════════════════════════════════════════════════
@app.get("/api/notifs")
async def notifs(request: Request):
    u = require_auth(request)
    c = db()
    unread = c.execute("SELECT COUNT(*) n FROM notifs WHERE username=? AND is_read=0", (u["username"],)).fetchone()["n"]
    if request.query_params.get("count"):
        c.close()
        return {"unread": unread}
    rows = c.execute("SELECT * FROM notifs WHERE username=? ORDER BY ts DESC LIMIT 50", (u["username"],)).fetchall()
    c.close()
    return {"rows": [dict(r) for r in rows], "unread": unread}

@app.post("/api/notifs/read-all")
async def notifs_read_all(request: Request):
    u = require_auth(request)
    c = db()
    c.execute("UPDATE notifs SET is_read=1 WHERE username=?", (u["username"],))
    c.commit()
    c.close()
    return {"ok": True}

@app.post("/api/notifs/clear")
async def notifs_clear(request: Request):
    u = require_auth(request)
    c = db()
    c.execute("DELETE FROM notifs WHERE username=?", (u["username"],))
    c.commit()
    c.close()
    return {"ok": True}

# ═══════════════════════════════════════════════════════════
# API — SUGGESTIONS
# ═══════════════════════════════════════════════════════════
@app.post("/api/suggestions")
async def submit_suggestion(request: Request):
    u = require_auth(request)
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "النص فارغ"}, 400)
    if len(text) > 1000:
        return JSONResponse({"error": "الحد 1000 حرف"}, 400)
    if not rate_ok(f"sug:{u['username']}", max_per_min=3):
        return JSONResponse({"error": "عدد كبير من الاقتراحات"}, 429)
    c = db()
    c.execute("INSERT INTO suggestions(username,text,is_read,ts) VALUES(?,?,0,?)", (u["username"], text[:1000], now()))
    c.commit()
    c.close()
    return {"ok": True}

@app.get("/api/admin/suggestions")
async def admin_suggestions(request: Request):
    require_owner(request)
    c = db()
    unread = c.execute("SELECT COUNT(*) n FROM suggestions WHERE is_read=0").fetchone()["n"]
    rows = c.execute("SELECT * FROM suggestions ORDER BY ts DESC LIMIT 200").fetchall()
    c.close()
    return {"rows": [dict(r) for r in rows], "unread": unread}

@app.patch("/api/admin/suggestions/{sid}")
async def admin_patch_suggestion(sid: int, request: Request):
    require_owner(request)
    body = await request.json()
    c = db()
    if "is_read" in body:
        c.execute("UPDATE suggestions SET is_read=? WHERE id=?", (1 if body["is_read"] else 0, sid))
        c.commit()
    c.close()
    return {"ok": True}

@app.delete("/api/admin/suggestions/{sid}")
async def admin_del_suggestion(sid: int, request: Request):
    require_owner(request)
    c = db()
    c.execute("DELETE FROM suggestions WHERE id=?", (sid,))
    c.commit()
    c.close()
    return {"ok": True}

# ═══════════════════════════════════════════════════════════
# API — PUSH
# ═══════════════════════════════════════════════════════════
@app.get("/api/push/key")
async def push_key():
    if not push_available():
        return JSONResponse({"error": "Push غير مفعّل"}, 404)
    return {"key": VAPID_PUBLIC}

@app.post("/api/push/subscribe")
async def push_subscribe(request: Request):
    u = require_auth(request)
    if not push_available():
        return JSONResponse({"error": "Push غير مفعّل"}, 400)
    body = await request.json()
    endpoint = body.get("endpoint") or ""
    keys = body.get("keys") or {}
    p256dh = keys.get("p256dh") or ""
    auth_key = keys.get("auth") or ""
    if not endpoint or not p256dh or not auth_key:
        return JSONResponse({"error": "بيانات ناقصة"}, 400)
    c = db()
    c.execute(
        "INSERT INTO push_subs(username,endpoint,p256dh,auth,ts) VALUES(?,?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET username=excluded.username,p256dh=excluded.p256dh,auth=excluded.auth,ts=excluded.ts",
        (u["username"], endpoint[:600], p256dh[:200], auth_key[:200], now())
    )
    c.commit()
    c.close()
    return {"ok": True}

@app.post("/api/push/unsubscribe")
async def push_unsubscribe(request: Request):
    u = require_auth(request)
    body = await request.json()
    c = db()
    c.execute("DELETE FROM push_subs WHERE endpoint=? AND username=?", (body.get("endpoint") or "", u["username"]))
    c.commit()
    c.close()
    return {"ok": True}

@app.post("/api/push/test")
async def push_test(request: Request):
    u = require_auth(request)
    if not push_available():
        return JSONResponse({"error": "Push غير مفعّل"}, 400)
    sent = await push_send_to_user(u["username"], "تجربة الإشعارات", "إذا وصلتك هذي، فالإشعارات تعمل ✅", "", "/", "test")
    if sent == 0:
        return JSONResponse({"error": "لا يوجد اشتراك فعّال"}, 404)
    return {"ok": True, "sent": sent}

# ═══════════════════════════════════════════════════════════
# API — UPLOAD / IMAGES
# ═══════════════════════════════════════════════════════════
@app.post("/api/upload")
async def upload_image(request: Request):
    u = require_auth(request)
    if not rate_ok(f"upload:{u['username']}", max_per_min=5):
        return JSONResponse({"error": "عدد كبير من الرفع"}, 429)
    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"error": "لم يُرفع ملف"}, 400)
    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE:
        return JSONResponse({"error": "الحجم أكبر من 2MB"}, 413)
    mime = file.content_type or "image/png"
    if not mime.startswith("image/"):
        return JSONResponse({"error": "يجب أن يكون صورة"}, 400)
    img_id = secrets.token_urlsafe(16)
    c = db()
    c.execute("INSERT INTO images(id,mime,data,size,uploaded_by,created) VALUES(?,?,?,?,?,?)", (img_id, mime, content, len(content), u["username"], now()))
    c.commit()
    c.close()
    return {"ok": True, "id": img_id, "url": f"/api/image/{img_id}"}

@app.get("/api/image/{img_id}")
async def get_image(img_id: str):
    if not re.match(r"^[A-Za-z0-9_-]{10,40}$", img_id):
        raise HTTPException(400, "معرّف غير صالح")
    c = db()
    row = c.execute("SELECT mime, data FROM images WHERE id=?", (img_id,)).fetchone()
    c.close()
    if not row:
        raise HTTPException(404, "غير موجودة")
    return FastResponse(content=row["data"], media_type=row["mime"], headers={"cache-control": "public, max-age=31536000, immutable"})

# ═══════════════════════════════════════════════════════════
# API — SETTINGS
# ═══════════════════════════════════════════════════════════
@app.get("/api/settings")
async def get_settings(request: Request):
    require_auth(request)
    keys = ["site_name", "site_sub", "hero_title", "hero_accent", "hero_text",
            "tpl_kick", "tpl_yt", "tpl_discord", "tpl_twitter", "tpl_youtube_dc",
            "btn_kick", "btn_yt", "btn_tg", "btn_discord",
            "lim_kick", "lim_yt", "lim_tg",
            "guest_mode", "guest_blur",
            "site_theme", "site_logo", "site_c1", "site_c2", "site_ac",
            "maintenance", "maintenance_text",
            "bot_invite_url", "bot_name_custom",
            "groq_model"]
    out = {k: cfg(k) for k in keys}
    out["groq_configured"] = groq_available()
    out["groq_source"] = "env" if GROQ_API_KEY_ENV else ("db" if cfg("groq_api_key", "") else "none")
    return out

@app.post("/api/settings")
async def save_settings(request: Request):
    require_owner(request)
    body = await request.json()
    allowed = ["site_name", "site_sub", "hero_title", "hero_accent", "hero_text",
               "tpl_kick", "tpl_yt", "tpl_discord", "tpl_twitter", "tpl_youtube_dc",
               "btn_kick", "btn_yt", "btn_tg", "btn_discord",
               "lim_kick", "lim_yt", "lim_tg",
               "guest_mode", "guest_blur",
               "site_theme", "site_logo", "site_c1", "site_c2", "site_ac",
               "maintenance", "maintenance_text",
               "bot_invite_url", "bot_name_custom",
               "groq_model"]
    for k in allowed:
        if k in body:
            set_cfg(k, str(body[k])[:2000])
    return {"ok": True}

@app.post("/api/admin/site-logo")
async def admin_site_logo(request: Request):
    require_owner(request)
    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"error": "لم يُرفع ملف"}, 400)
    content = await file.read()
    if len(content) > 512000:
        return JSONResponse({"error": "الحجم أكبر من 500KB"}, 413)
    mime = file.content_type or "image/png"
    if not mime.startswith("image/"):
        return JSONResponse({"error": "يجب أن يكون صورة"}, 400)
    img_id = secrets.token_urlsafe(16)
    c = db()
    c.execute("INSERT INTO images(id,mime,data,size,uploaded_by,created) VALUES(?,?,?,?,?,?)", (img_id, mime, content, len(content), "site_logo", now()))
    c.commit()
    c.close()
    url = f"/api/image/{img_id}"
    set_cfg("site_logo", url)
    return {"ok": True, "url": url}

@app.delete("/api/admin/site-logo")
async def admin_site_logo_del(request: Request):
    require_owner(request)
    set_cfg("site_logo", "")
    return {"ok": True}

# ═══════════════════════════════════════════════════════════
# API — MAINTENANCE
# ═══════════════════════════════════════════════════════════
@app.post("/api/admin/maintenance")
async def admin_maintenance(request: Request):
    require_owner(request)
    body = await request.json()
    enabled = 1 if body.get("enabled") else 0
    text = str(body.get("text") or "")[:500]
    set_cfg("maintenance", str(enabled))
    if text:
        set_cfg("maintenance_text", text)
    return {"ok": True, "maintenance": enabled == 1}

# ═══════════════════════════════════════════════════════════
# API — ADMIN DEFAULTS
# ═══════════════════════════════════════════════════════════
@app.get("/api/admin/default-channels")
async def list_default_channels(request: Request):
    require_owner(request)
    kind = request.query_params.get("kind")
    c = db()
    if kind in ("kick", "yt", "tg"):
        rows = c.execute("SELECT * FROM default_channels WHERE kind=? ORDER BY id DESC", (kind,)).fetchall()
    else:
        rows = c.execute("SELECT * FROM default_channels ORDER BY kind, id DESC").fetchall()
    c.close()
    return {"rows": [dict(r) for r in rows]}

@app.post("/api/admin/default-channels")
async def add_default_channel(request: Request):
    require_owner(request)
    body = await request.json()
    kind = body.get("kind")
    if kind not in ("kick", "yt", "tg"):
        return JSONResponse({"error": "نوع غير صالح"}, 400)
    raw = (body.get("identifier") or "").strip()
    if not raw:
        return JSONResponse({"error": "المعرّف مطلوب"}, 400)
    if kind == "kick":
        ident = re.sub(r"[^a-z0-9_-]", "", raw.lower().replace("@", ""))
        name = body.get("name") or ident
        avatar = ""
        info = await kick_fetch(ident)
        if info:
            name = info["name"]
            avatar = info["avatar"]
    elif kind == "yt":
        info = await yt_resolve(raw)
        if not info:
            return JSONResponse({"error": "تعذّر التعرف على القناة"}, 400)
        ident = info["channel_id"]
        name = info["name"] or ident
        avatar = info.get("avatar") or ""
    else:
        ident = norm_chat(raw)
        if not ident:
            return JSONResponse({"error": "معرّف غير صالح"}, 400)
        info = await tg_get_chat_info(ident)
        name = body.get("name") or (info or {}).get("name") or ident
        avatar = (info or {}).get("avatar") or ""
        if info and info.get("chat_id"):
            ident = info["chat_id"]
    c = db()
    if c.execute("SELECT 1 FROM default_channels WHERE kind=? AND identifier=?", (kind, ident)).fetchone():
        c.close()
        return JSONResponse({"error": "موجودة مسبقاً"}, 409)
    c.execute("INSERT INTO default_channels(kind,identifier,name,avatar,enabled,created) VALUES(?,?,?,?,1,?)", (kind, ident, name, avatar, now()))
    c.commit()
    c.close()
    return {"ok": True}

@app.post("/api/admin/default-channels/bulk")
async def add_default_channels_bulk(request: Request):
    require_owner(request)
    body = await request.json()
    kind = body.get("kind")
    if kind not in ("kick", "yt", "tg"):
        return JSONResponse({"error": "نوع غير صالح"}, 400)
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "لا يوجد نص"}, 400)
    lines = [l.strip() for l in text.split("\n") if l.strip()][:100]
    if not lines:
        return JSONResponse({"error": "لا توجد أسطر"}, 400)
    added, failed, errors = 0, 0, []
    for line in lines:
        try:
            parts = [p.strip() for p in line.split("|")]
            raw = parts[0]
            custom_name = parts[1] if len(parts) > 1 else ""
            if kind == "kick":
                ident = re.sub(r"[^a-z0-9_-]", "", raw.lower().replace("@", ""))
                if not ident:
                    failed += 1
                    errors.append(f"{raw}: معرّف غير صالح")
                    continue
                name = custom_name or ident
                avatar = ""
                info = await kick_fetch(ident)
                if info:
                    name = custom_name or info["name"]
                    avatar = info["avatar"]
            elif kind == "yt":
                info = await yt_resolve(raw)
                if not info:
                    failed += 1
                    errors.append(f"{raw}: تعذّر التعرف")
                    continue
                ident = info["channel_id"]
                name = custom_name or info["name"] or ident
                avatar = info.get("avatar") or ""
            else:
                ident = norm_chat(raw)
                if not ident:
                    failed += 1
                    errors.append(f"{raw}: معرّف غير صالح")
                    continue
                info = await tg_get_chat_info(ident)
                name = custom_name or (info or {}).get("name") or ident
                avatar = (info or {}).get("avatar") or ""
                if info and info.get("chat_id"):
                    ident = info["chat_id"]
            c = db()
            if c.execute("SELECT 1 FROM default_channels WHERE kind=? AND identifier=?", (kind, ident)).fetchone():
                c.close()
                failed += 1
                errors.append(f"{name}: موجودة مسبقاً")
                continue
            c.execute("INSERT INTO default_channels(kind,identifier,name,avatar,enabled,created) VALUES(?,?,?,?,1,?)", (kind, ident, name, avatar, now()))
            c.commit()
            c.close()
            added += 1
        except Exception as e:
            failed += 1
            errors.append(f"{line[:30]}: {str(e)[:40]}")
    return {"ok": True, "added": added, "failed": failed, "errors": errors}

@app.delete("/api/admin/default-channels/{cid}")
async def del_default_channel(cid: int, request: Request):
    require_owner(request)
    c = db()
    c.execute("DELETE FROM default_channels WHERE id=?", (cid,))
    c.commit()
    c.close()
    return {"ok": True}

@app.patch("/api/admin/default-channels/{cid}")
async def patch_default_channel(cid: int, request: Request):
    require_owner(request)
    body = await request.json()
    c = db()
    sets, vals = [], []
    if "enabled" in body:
        sets.append("enabled=?")
        vals.append(1 if body["enabled"] else 0)
    if "name" in body:
        sets.append("name=?")
        vals.append(str(body["name"])[:80])
    if sets:
        vals.append(cid)
        c.execute(f"UPDATE default_channels SET {', '.join(sets)} WHERE id=?", vals)
        c.commit()
    c.close()
    return {"ok": True}

# ═══════════════════════════════════════════════════════════
# API — ADMIN USERS
# ═══════════════════════════════════════════════════════════
@app.get("/api/admin/users")
async def admin_users(request: Request):
    require_owner(request)
    c = db()
    rows = c.execute("SELECT id, username, display, avatar, role, active, banned, lim_kick, lim_yt, lim_tg, can_discord, created, last_login FROM users ORDER BY id").fetchall()
    c.close()
    return {"rows": [dict(r) for r in rows]}

@app.post("/api/admin/users")
async def admin_add_user(request: Request):
    require_owner(request)
    body = await request.json()
    un = (body.get("username") or "").strip()
    pw = str(body.get("password") or "")
    if not re.match(r"^[A-Za-z0-9_.-]{3,30}$", un):
        return JSONResponse({"error": "اسم غير صالح"}, 400)
    if len(pw) < 6:
        return JSONResponse({"error": "كلمة المرور 6+"}, 400)
    if un.lower() == ADMIN_USERNAME.lower():
        return JSONResponse({"error": "محجوز"}, 400)
    c = db()
    if c.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)", (un,)).fetchone():
        c.close()
        return JSONResponse({"error": "مستخدم"}, 409)
    salt = secrets.token_hex(16)
    opt = lambda v: (None if v in ("", None) else max(0, min(9999, int(v))))
    c.execute(
        "INSERT INTO users(username,display,pass_hash,salt,role,active,banned,lim_kick,lim_yt,lim_tg,can_discord,created) VALUES(?,?,?,?,'user',1,0,?,?,?,?,?)",
        (un, (body.get("display") or un)[:60], hash_pw(pw, salt), salt,
         opt(body.get("lim_kick")), opt(body.get("lim_yt")), opt(body.get("lim_tg")),
         1 if body.get("can_discord") else 0, now())
    )
    c.commit()
    c.close()
    return {"ok": True}

@app.patch("/api/admin/users/{uid}")
async def admin_patch_user(uid: int, request: Request):
    u = require_owner(request)
    body = await request.json()
    c = db()
    row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        c.close()
        raise HTTPException(404)
    is_self = row["username"] == u["username"]
    is_admin_acc = row["username"].lower() == ADMIN_USERNAME.lower()
    sets, vals = [], []
    opt = lambda v: (None if v in ("", None) else max(0, min(9999, int(v))))
    if "banned" in body and not is_self and not is_admin_acc:
        sets.append("banned=?")
        vals.append(1 if body["banned"] else 0)
    if "active" in body and not is_self and not is_admin_acc:
        sets.append("active=?")
        vals.append(1 if body["active"] else 0)
    if "role" in body and not is_admin_acc:
        sets.append("role=?")
        vals.append("owner" if body["role"] == "owner" else "user")
    if "display" in body:
        sets.append("display=?")
        vals.append(str(body["display"])[:60] or row["username"])
    for k in ("lim_kick", "lim_yt", "lim_tg"):
        if k in body:
            sets.append(f"{k}=?")
            vals.append(opt(body[k]))
    if "can_discord" in body:
        sets.append("can_discord=?")
        vals.append(1 if body["can_discord"] else 0)
    pw_changed = False
    if body.get("password"):
        if len(str(body["password"])) < 6:
            c.close()
            return JSONResponse({"error": "كلمة المرور 6+"}, 400)
        salt = secrets.token_hex(16)
        sets.append("pass_hash=?")
        vals.append(hash_pw(str(body["password"]), salt))
        sets.append("salt=?")
        vals.append(salt)
        pw_changed = True
    if sets:
        vals.append(uid)
        c.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", vals)
        c.commit()
    c.close()
    if pw_changed or "banned" in body or "active" in body:
        kill_sessions(row["username"])
    return {"ok": True}

@app.delete("/api/admin/users/{uid}")
async def admin_del_user(uid: int, request: Request):
    u = require_owner(request)
    c = db()
    row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        c.close()
        raise HTTPException(404)
    if row["username"] == u["username"] or row["username"].lower() == ADMIN_USERNAME.lower():
        c.close()
        return JSONResponse({"error": "لا يمكن حذف هذا الحساب"}, 400)
    uname = row["username"]
    for t in ("kick_channels", "yt_channels", "tg_channels", "discord_feeds", "recent_videos"):
        c.execute(f"DELETE FROM {t} WHERE added_by=?", (uname,))
    for t in ("notifs", "sessions", "suggestions", "push_subs"):
        c.execute(f"DELETE FROM {t} WHERE username=?", (uname,))
    c.execute("DELETE FROM users WHERE id=?", (uid,))
    c.commit()
    c.close()
    return {"ok": True}

# ═══════════════════════════════════════════════════════════
# API — ADMIN STATS + SECURITY
# ═══════════════════════════════════════════════════════════
@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    require_owner(request)
    c = db()
    stats = {
        "users_total": c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],
        "users_active": c.execute("SELECT COUNT(*) n FROM users WHERE active=1 AND banned=0").fetchone()["n"],
        "users_banned": c.execute("SELECT COUNT(*) n FROM users WHERE banned=1").fetchone()["n"],
        "kick_total": c.execute("SELECT COUNT(*) n FROM kick_channels").fetchone()["n"],
        "kick_live": c.execute("SELECT COUNT(*) n FROM kick_channels WHERE live=1").fetchone()["n"],
        "yt_total": c.execute("SELECT COUNT(*) n FROM yt_channels").fetchone()["n"],
        "tg_total": c.execute("SELECT COUNT(*) n FROM tg_channels").fetchone()["n"],
        "feeds_total": c.execute("SELECT COUNT(*) n FROM discord_feeds").fetchone()["n"],
        "notifs_total": c.execute("SELECT COUNT(*) n FROM notifs").fetchone()["n"],
        "suggestions_unread": c.execute("SELECT COUNT(*) n FROM suggestions WHERE is_read=0").fetchone()["n"],
        "push_subs": c.execute("SELECT COUNT(*) n FROM push_subs").fetchone()["n"],
        "defaults_total": c.execute("SELECT COUNT(*) n FROM default_channels").fetchone()["n"],
    }
    c.close()
    stats["discord_ready"] = discord_client.is_ready() if discord_client else False
    stats["discord_guilds"] = len(discord_client.guilds) if discord_client and discord_client.is_ready() else 0
    stats["discord_channels"] = len(_DISCORD_CHANNELS_CACHE)
    stats["watching"] = len(_DISCORD_CHANNELS_CACHE) if not WATCH_CHANNELS else len(WATCH_CHANNELS)
    stats["auto_discovery"] = not bool(WATCH_CHANNELS)
    stats["has_telegram"] = bool(TELEGRAM_TOKEN)
    stats["has_discord"] = bool(DISCORD_TOKEN)
    stats["has_push"] = push_available()
    stats["has_groq"] = groq_available()
    stats["groq_source"] = "env" if GROQ_API_KEY_ENV else ("db" if cfg("groq_api_key", "") else "none")
    stats["maintenance"] = cfg("maintenance", "0") == "1"
    stats["self_bot_mode"] = _SELF_BOT
    stats["discord_mode"] = _DISCORD_MODE  # 🆕
    stats["discord_enabled"] = DISCORD_ENABLE  # 🆕
    stats["bot_info"] = _DISCORD_BOT_INFO
    return stats

@app.get("/api/admin/security")
async def admin_security(request: Request):
    require_owner(request)
    c = db()
    rows = c.execute("SELECT ts, username, action, detail, ip FROM security_log ORDER BY id DESC LIMIT 200").fetchall()
    c.close()
    return {"rows": [dict(r) for r in rows]}

# ═══════════════════════════════════════════════════════════
# ROOT + MANIFEST + SW + HEALTH
# ═══════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def index():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>index.html غير موجود</h1>", status_code=500)

@app.get("/manifest.json")
async def manifest():
    theme = get_site_theme()
    logo = cfg("site_logo", "")
    icons = [{"src": logo or "/favicon.ico", "sizes": "192x192 512x512", "type": "image/png", "purpose": "any"}]
    return JSONResponse({
        "name": cfg("site_name", SITE_NAME),
        "short_name": cfg("site_name", SITE_NAME)[:12],
        "start_url": "/",
        "display": "standalone",
        "background_color": theme["c1"],
        "theme_color": theme["c1"],
        "dir": "rtl",
        "lang": "ar",
        "icons": icons
    })

@app.get("/sw.js")
async def sw():
    js = "self.addEventListener('install',e=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));self.addEventListener('push',e=>{let d={};try{d=e.data.json();}catch(x){d={title:'إشعار جديد',body:e.data?e.data.text():''};}const o={body:d.body||'',icon:d.icon||'/favicon.ico',badge:d.icon||'/favicon.ico',image:d.image||undefined,tag:d.tag||undefined,renotify:!!d.tag,dir:'rtl',lang:'ar',data:{url:d.url||'/'}};e.waitUntil(Promise.all([self.registration.showNotification(d.title||'إشعار جديد',o),self.clients.matchAll({type:'window'}).then(cs=>cs.forEach(c=>c.postMessage({t:'push'})))]));});self.addEventListener('notificationclick',e=>{e.notification.close();const url=(e.notification.data&&e.notification.data.url)||'/';e.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(cs=>{const same=cs.find(c=>new URL(c.url).origin===location.origin);if(url.startsWith('/')&&same)return same.focus();return self.clients.openWindow(url);}));});"
    return FastResponse(content=js, media_type="application/javascript", headers={"cache-control": "no-cache"})

@app.get("/favicon.ico")
async def favicon():
    logo = cfg("site_logo", "")
    if logo and logo.startswith("/api/image/"):
        img_id = logo.replace("/api/image/", "")
        c = db()
        row = c.execute("SELECT mime, data FROM images WHERE id=?", (img_id,)).fetchone()
        c.close()
        if row:
            return FastResponse(content=row["data"], media_type=row["mime"])
    return FastResponse(content=b"", status_code=204)

@app.get("/health")
async def health():
    return {
        "ok": True,
        "discord_ready": discord_client.is_ready() if discord_client else False,
        "discord_channels": len(_DISCORD_CHANNELS_CACHE),
        "discord_guilds": len(_DISCORD_GUILDS_CACHE),
        "auto_discovery": not bool(WATCH_CHANNELS),
        "watching": len(WATCH_CHANNELS),
        "push_enabled": push_available(),
        "telegram_enabled": bool(TELEGRAM_TOKEN),
        "groq_enabled": groq_available(),
        "maintenance": cfg("maintenance", "0") == "1",
        "self_bot_mode": _SELF_BOT,
        "discord_mode": _DISCORD_MODE,  # 🆕
        "discord_enabled": DISCORD_ENABLE,  # 🆕
    }

# ═══════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
