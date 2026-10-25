"""Respect Live — v11 (Stable + Full Page Account + Fixed Login)"""
import os, re, json, time, hashlib, secrets, sqlite3, asyncio
from contextlib import asynccontextmanager
import httpx
import discord
from fastapi import FastAPI, Request, Response, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response as FastResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
load_dotenv()

# ═══ CONFIG ═══
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_hex(32))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
WATCH_CHANNELS = [c.strip() for c in os.getenv("DISCORD_WATCH_CHANNELS", "").split(",") if c.strip()]
ALLOWED_GUILDS = [g.strip() for g in os.getenv("DISCORD_ALLOWED_GUILDS", "").split(",") if g.strip()]
VAPID_PUBLIC = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_EMAIL = os.getenv("VAPID_EMAIL", "mailto:admin@example.com")
SITE_NAME = os.getenv("SITE_NAME", "Respect Live")
SITE_COLOR = os.getenv("SITE_COLOR", "#0b55ea")
DB_PATH = os.getenv("DB_PATH", "respect.db")
GROQ_ENV_KEY = os.getenv("GROQ_API_KEY", "")
TWITTER_ENV_BEARER = os.getenv("TWITTER_BEARER_TOKEN", "")
SESSION_TTL = 7 * 24 * 3600
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
MAX_PER_MIN_TG = 30
MAX_PER_MIN_CH = 15
BATCH_KICK = 30
BATCH_YT = 30
BATCH_TW = 10
MAX_IMAGE_SIZE = 2 * 1024 * 1024
VERIFY_TTL = 600
LINK_CODE_TTL = 600
MEMBER_CHECK_TTL = 600

PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
if not PUBLIC_URL and os.getenv("RAILWAY_PUBLIC_DOMAIN"):
    PUBLIC_URL = "https://" + os.getenv("RAILWAY_PUBLIC_DOMAIN").strip().rstrip("/")

THEMES = [
    {"id":"default","n":"الافتراضي","c1":"#030508","c2":"#0a0f18","ac":"#0b55ea"},
    {"id":"saudi","n":"اليوم الوطني","c1":"#033a20","c2":"#0b7a3e","ac":"#ffffff"},
    {"id":"founding","n":"يوم التأسيس","c1":"#3a290b","c2":"#0b5c3a","ac":"#e6b85c"},
    {"id":"ramadan","n":"رمضان","c1":"#0a1733","c2":"#1d3a6e","ac":"#f5c04a"},
    {"id":"fitr","n":"عيد الفطر","c1":"#0d3434","c2":"#1d6b57","ac":"#ffd166"},
    {"id":"adha","n":"عيد الأضحى","c1":"#2a1a0a","c2":"#6a4720","ac":"#f0b84d"},
]

# ═══ DATABASE ═══
def db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, display TEXT DEFAULT '', avatar TEXT DEFAULT '', pass_hash TEXT DEFAULT '', salt TEXT DEFAULT '', role TEXT DEFAULT 'user', active INTEGER DEFAULT 1, banned INTEGER DEFAULT 0, lim_kick INTEGER, lim_yt INTEGER, lim_tg INTEGER, lim_tw INTEGER, can_discord INTEGER DEFAULT 0, created INTEGER, last_login INTEGER, linked_tg_id TEXT DEFAULT '', linked_tg_username TEXT DEFAULT '', linked_tg_name TEXT DEFAULT '', is_member INTEGER DEFAULT 0, member_checked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT NOT NULL, created INTEGER, expires INTEGER);
CREATE INDEX IF NOT EXISTS idx_sess_exp ON sessions(expires);
CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS default_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, identifier TEXT NOT NULL, name TEXT DEFAULT '', avatar TEXT DEFAULT '', enabled INTEGER DEFAULT 1, created INTEGER, UNIQUE(kind, identifier));
CREATE TABLE IF NOT EXISTS kick_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL, name TEXT DEFAULT '', avatar TEXT DEFAULT '', banner TEXT DEFAULT '', msg TEXT DEFAULT '', btn_text TEXT DEFAULT '', enabled INTEGER DEFAULT 1, auto_send INTEGER DEFAULT 1, live INTEGER DEFAULT 0, title TEXT DEFAULT '', viewers INTEGER DEFAULT 0, thumb TEXT DEFAULT '', last_check INTEGER DEFAULT 0, added_by TEXT NOT NULL, created INTEGER, UNIQUE(slug, added_by));
CREATE INDEX IF NOT EXISTS idx_kick_by ON kick_channels(added_by);
CREATE TABLE IF NOT EXISTS yt_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT NOT NULL, handle TEXT DEFAULT '', name TEXT DEFAULT '', avatar TEXT DEFAULT '', banner TEXT DEFAULT '', msg TEXT DEFAULT '', btn_text TEXT DEFAULT '', enabled INTEGER DEFAULT 1, auto_send INTEGER DEFAULT 1, last_video TEXT DEFAULT '', last_check INTEGER DEFAULT 0, added_by TEXT NOT NULL, created INTEGER, UNIQUE(channel_id, added_by));
CREATE INDEX IF NOT EXISTS idx_yt_by ON yt_channels(added_by);
CREATE TABLE IF NOT EXISTS tw_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, name TEXT DEFAULT '', avatar TEXT DEFAULT '', msg TEXT DEFAULT '', btn_text TEXT DEFAULT '', filter_kw TEXT DEFAULT '', enabled INTEGER DEFAULT 1, auto_send INTEGER DEFAULT 1, last_tweet TEXT DEFAULT '', last_check INTEGER DEFAULT 0, added_by TEXT NOT NULL, created INTEGER, UNIQUE(username, added_by));
CREATE INDEX IF NOT EXISTS idx_tw_by ON tw_channels(added_by);
CREATE TABLE IF NOT EXISTS tg_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, username TEXT DEFAULT '', name TEXT DEFAULT '', avatar TEXT DEFAULT '', banner TEXT DEFAULT '', enabled INTEGER DEFAULT 1, verified INTEGER DEFAULT 0, owner_tg_id TEXT DEFAULT '', owner_tg_username TEXT DEFAULT '', added_by TEXT NOT NULL, created INTEGER, UNIQUE(chat_id, added_by));
CREATE INDEX IF NOT EXISTS idx_tg_by ON tg_channels(added_by);
CREATE TABLE IF NOT EXISTS sent_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, tg_chat_id TEXT NOT NULL, source TEXT NOT NULL, title TEXT DEFAULT '', body TEXT DEFAULT '', ts INTEGER);
CREATE INDEX IF NOT EXISTS idx_sent_tg ON sent_messages(tg_chat_id);
CREATE TABLE IF NOT EXISTS tg_known_channels (chat_id TEXT PRIMARY KEY, username TEXT DEFAULT '', name TEXT DEFAULT '', avatar TEXT DEFAULT '', type TEXT DEFAULT '', last_seen INTEGER);
CREATE INDEX IF NOT EXISTS idx_tkc_un ON tg_known_channels(username);
CREATE TABLE IF NOT EXISTS tg_verifications (id INTEGER PRIMARY KEY AUTOINCREMENT, site_username TEXT NOT NULL, tg_username TEXT NOT NULL DEFAULT '', tg_user_id TEXT DEFAULT '', tg_chat_id TEXT DEFAULT '', tg_chat_name TEXT DEFAULT '', tg_chat_avatar TEXT DEFAULT '', code TEXT DEFAULT '', status TEXT DEFAULT 'pending', tg_msg_id INTEGER DEFAULT 0, created INTEGER, expires INTEGER);
CREATE INDEX IF NOT EXISTS idx_tgv_status ON tg_verifications(status, expires);
CREATE TABLE IF NOT EXISTS tg_link_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, site_username TEXT NOT NULL, tg_user_id TEXT DEFAULT '', tg_username TEXT DEFAULT '', tg_first_name TEXT DEFAULT '', token TEXT UNIQUE NOT NULL, status TEXT DEFAULT 'pending', created INTEGER, expires INTEGER);
CREATE INDEX IF NOT EXISTS idx_tlc_status ON tg_link_codes(status, expires);
CREATE TABLE IF NOT EXISTS feed_subs (id INTEGER PRIMARY KEY AUTOINCREMENT, feed_id INTEGER NOT NULL, tg_channel_id INTEGER NOT NULL, username TEXT NOT NULL, enabled INTEGER DEFAULT 1, created INTEGER, UNIQUE(feed_id, tg_channel_id));
CREATE INDEX IF NOT EXISTS idx_fs_feed ON feed_subs(feed_id, enabled);
CREATE TABLE IF NOT EXISTS discord_feeds (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT NOT NULL, channel_name TEXT DEFAULT '', guild_id TEXT DEFAULT '', template TEXT DEFAULT '', btn_text TEXT DEFAULT 'عرض الروم', source_type TEXT DEFAULT 'generic', target_tg_ids TEXT DEFAULT '', enabled INTEGER DEFAULT 1, use_original INTEGER DEFAULT 1, ignore_bots TEXT DEFAULT '', keyword_rules TEXT DEFAULT '', fixed_image TEXT DEFAULT '', room_url TEXT DEFAULT '', use_ai INTEGER DEFAULT 0, ai_prompt TEXT DEFAULT '', added_by TEXT NOT NULL, created INTEGER, UNIQUE(channel_id));
CREATE INDEX IF NOT EXISTS idx_df_ch ON discord_feeds(channel_id, enabled);
CREATE TABLE IF NOT EXISTS discord_seen (message_id TEXT PRIMARY KEY, ts INTEGER);
CREATE INDEX IF NOT EXISTS idx_ds_ts ON discord_seen(ts);
CREATE TABLE IF NOT EXISTS discord_bots (id TEXT PRIMARY KEY, name TEXT DEFAULT '', avatar TEXT DEFAULT '', first_seen INTEGER, last_seen INTEGER, seen_count INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS notifs (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, title TEXT DEFAULT '', body TEXT DEFAULT '', image TEXT DEFAULT '', btn_text TEXT DEFAULT '', btn_url TEXT DEFAULT '', kind TEXT DEFAULT 'admin', ts INTEGER, is_read INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_notifs ON notifs(username, ts);
CREATE TABLE IF NOT EXISTS recent_videos (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT NOT NULL, ch_name TEXT DEFAULT '', title TEXT DEFAULT '', thumb TEXT DEFAULT '', url TEXT DEFAULT '', ts INTEGER, added_by TEXT NOT NULL, UNIQUE(video_id, added_by));
CREATE TABLE IF NOT EXISTS suggestions (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, text TEXT NOT NULL, is_read INTEGER DEFAULT 0, ts INTEGER);
CREATE TABLE IF NOT EXISTS push_subs (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, endpoint TEXT UNIQUE NOT NULL, p256dh TEXT NOT NULL, auth TEXT NOT NULL, ts INTEGER);
CREATE TABLE IF NOT EXISTS images (id TEXT PRIMARY KEY, mime TEXT NOT NULL, data BLOB NOT NULL, size INTEGER NOT NULL, uploaded_by TEXT, created INTEGER);
CREATE TABLE IF NOT EXISTS rate_limits (k TEXT PRIMARY KEY, cnt INTEGER, ts INTEGER);
CREATE TABLE IF NOT EXISTS security_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, username TEXT, action TEXT, detail TEXT, ip TEXT);
CREATE TABLE IF NOT EXISTS news (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT DEFAULT '', image TEXT DEFAULT '', kind TEXT DEFAULT 'news', enabled INTEGER DEFAULT 1, created INTEGER);
CREATE TABLE IF NOT EXISTS news_read (username TEXT NOT NULL, news_id INTEGER NOT NULL, ts INTEGER, PRIMARY KEY(username, news_id));
"""

def migrate_tg_channels_per_user():
    c = db()
    try:
        row = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tg_channels'").fetchone()
        if not row: c.close(); return
        sql = (row["sql"] or "").lower()
        if "unique(chat_id, added_by)" in sql: c.close(); return
        print("[DB] Migrating tg_channels to per-user unique...")
        c.execute("PRAGMA foreign_keys=OFF")
        c.execute("ALTER TABLE tg_channels RENAME TO tg_channels_old")
        c.execute("""CREATE TABLE tg_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, username TEXT DEFAULT '', name TEXT DEFAULT '', avatar TEXT DEFAULT '', banner TEXT DEFAULT '', enabled INTEGER DEFAULT 1, verified INTEGER DEFAULT 0, owner_tg_id TEXT DEFAULT '', owner_tg_username TEXT DEFAULT '', added_by TEXT NOT NULL, created INTEGER, UNIQUE(chat_id, added_by))""")
        rows = c.execute("SELECT * FROM tg_channels_old").fetchall()
        seen = set()
        for r in rows:
            key = (r["chat_id"], r["added_by"])
            if key in seen: continue
            seen.add(key)
            c.execute("INSERT INTO tg_channels (id, chat_id, username, name, avatar, banner, enabled, verified, owner_tg_id, owner_tg_username, added_by, created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (r["id"], r["chat_id"], r["username"], r["name"], r["avatar"], r["banner"], r["enabled"], r["verified"], r["owner_tg_id"], r["owner_tg_username"], r["added_by"], r["created"]))
        c.execute("DROP TABLE tg_channels_old")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tg_by ON tg_channels(added_by)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tg_chat ON tg_channels(chat_id)")
        c.commit()
        print("[DB] ✅ tg_channels migration complete")
    except Exception as e:
        print("[DB] Migration error: " + str(e))
    c.close()

def init_db():
    c = db()
    c.executescript(SCHEMA)
    for tbl, col, typ in [
        ("users","can_discord","INTEGER DEFAULT 0"),
        ("users","avatar","TEXT DEFAULT ''"),
        ("users","lim_tw","INTEGER"),
        ("users","linked_tg_id","TEXT DEFAULT ''"),
        ("users","linked_tg_username","TEXT DEFAULT ''"),
        ("users","linked_tg_name","TEXT DEFAULT ''"),
        ("users","is_member","INTEGER DEFAULT 0"),
        ("users","member_checked","INTEGER DEFAULT 0"),
        ("kick_channels","btn_text","TEXT DEFAULT ''"),
        ("kick_channels","auto_send","INTEGER DEFAULT 1"),
        ("yt_channels","btn_text","TEXT DEFAULT ''"),
        ("yt_channels","auto_send","INTEGER DEFAULT 1"),
        ("yt_channels","banner","TEXT DEFAULT ''"),
        ("tg_channels","banner","TEXT DEFAULT ''"),
        ("tg_channels","verified","INTEGER DEFAULT 0"),
        ("tg_channels","owner_tg_id","TEXT DEFAULT ''"),
        ("tg_channels","owner_tg_username","TEXT DEFAULT ''"),
        ("discord_feeds","btn_text","TEXT DEFAULT 'عرض الروم'"),
        ("discord_feeds","target_tg_ids","TEXT DEFAULT ''"),
        ("discord_feeds","guild_id","TEXT DEFAULT ''"),
        ("discord_feeds","use_original","INTEGER DEFAULT 1"),
        ("discord_feeds","ignore_bots","TEXT DEFAULT ''"),
        ("discord_feeds","keyword_rules","TEXT DEFAULT ''"),
        ("discord_feeds","fixed_image","TEXT DEFAULT ''"),
        ("discord_feeds","room_url","TEXT DEFAULT ''"),
        ("discord_feeds","use_ai","INTEGER DEFAULT 0"),
        ("discord_feeds","ai_prompt","TEXT DEFAULT ''"),
    ]:
        try:
            cols = [r["name"] for r in c.execute("PRAGMA table_info(" + tbl + ")").fetchall()]
            if col not in cols:
                c.execute("ALTER TABLE " + tbl + " ADD COLUMN " + col + " " + typ)
                c.commit()
        except: pass
    salt = secrets.token_hex(16)
    h = hash_pw(ADMIN_PASSWORD, salt)
    if not c.execute("SELECT 1 FROM users WHERE username=?", (ADMIN_USERNAME,)).fetchone():
        c.execute("INSERT INTO users(username,display,pass_hash,salt,role,active,banned,can_discord,created) VALUES(?,?,?,?,'owner',1,0,1,?)", (ADMIN_USERNAME, ADMIN_USERNAME, h, salt, now()))
    else:
        c.execute("UPDATE users SET pass_hash=?, salt=?, role='owner', active=1, banned=0, can_discord=1 WHERE username=?", (h, salt, ADMIN_USERNAME))
    
    defaults = {
        "site_name": SITE_NAME, "site_sub": "STREAM MONITOR",
        "hero_title": "مراقبة", "hero_accent": "القنوات.",
        "hero_text": "تابع قنواتك على كيك ويوتيوب وتويتر وتيليجرام في مكان واحد.",
        "tpl_kick": "<b>{name}</b>\nبدأ بثاً مباشراً الآن\n\n<b>{title}</b>\n\n⚪🔴",
        "tpl_yt": "<b>{title}</b>\n\n\n⚪🔴",
        "tpl_discord": "<b>{author_no_at}</b>\n\n<b>{content}</b>",
        "tpl_twitter": "<b>{author_no_at}</b>\n\n<b>{content}</b>",
        "tpl_youtube_dc": "<b>{title}</b>\n\n<b>{author_no_at}</b>",
        "tpl_tg_verify": "🔐 <b>طلب توثيق قناة</b>\n\nالمستخدم <code>{site_user}</code> يحاول ربط قناة <b>{chat_name}</b>.\n\n<b>هل أنت من يحاول ذلك؟</b>",
        "tpl_tg_success": "✅ <b>تم الربط بنجاح</b>\n\nالقناة: <b>{chat_name}</b>\nالمستخدم: <code>{site_user}</code>\n\nيمكنك الآن إدارتها من الموقع.",
        "tpl_tg_link": "🔐 <b>ربط حساب</b>\n\nرمز التحقق الخاص بك:\n\n<code>{code}</code>\n\n<i>صالح لمدة 10 دقائق. لا تشاركه مع أحد.</i>",
        "btn_kick": "شاهد البث", "btn_yt": "شاهد الفيديو",
        "btn_tg": "عرض القناة", "btn_discord": "عرض الروم", "btn_tw": "عرض التغريدة",
        "lim_kick": "10", "lim_yt": "5", "lim_tg": "3", "lim_tw": "3",
        "guest_mode": "1", "guest_blur": "14",
        "site_theme": "default", "site_logo": "",
        "site_c1": "#030508", "site_c2": "#0a0f18", "site_ac": SITE_COLOR,
        "maintenance": "0", "maintenance_text": "الموقع في صيانة مؤقتة — نرجع قريباً",
        "maintenance_title": "🔧 صيانة مؤقتة",
        "bot_invite_url": "", "bot_name_custom": "Respect Live",
        "groq_api_key": "", "groq_model": "llama-3.3-70b-versatile",
        "twitter_bearer_token": "",
        "registration_enabled": "1",
        "default_lim_kick": "10", "default_lim_yt": "5", "default_lim_tg": "1", "default_lim_tw": "1",
        "bonus_lim_kick": "50", "bonus_lim_yt": "25", "bonus_lim_tg": "5", "bonus_lim_tw": "5",
        "required_channel_id": "", "required_channel_url": "", "required_channel_name": "",
        "required_channel_msg": "🚀 للحصول على صلاحيات مضاعفة، انضم إلى قناتنا الرسمية عبر الرابط أدناه ثم اضغط تحقق.",
        "signup_welcome_title": "مرحباً بك!",
        "signup_welcome_text": "حسابك بصلاحيات محدودة وبدون وصول لصفحة الديسكورد. للترقية، اربط حسابك في تيليجرام وانضم للقناة الرسمية.",
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings(k,v) VALUES(?,?)", (k, v))
    
    if cfg("v11_migration", "") != "done":
        c.execute("INSERT OR REPLACE INTO settings(k,v) VALUES('v11_migration', 'done')")
        c.commit()
        
    c.close()
    print("[DB] Ready")

# ═══ HELPERS ═══
def now(): return int(time.time())

def cfg(k, d=""):
    c = db(); r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone(); c.close()
    return r["v"] if r else d

def set_cfg(k, v):
    c = db(); c.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v))); c.commit(); c.close()

def hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 100000).hex()

def log_sec(username, action, detail="", ip=""):
    try:
        c = db()
        c.execute("INSERT INTO security_log(ts,username,action,detail,ip) VALUES(?,?,?,?,?)", (now(), username or "anon", action[:60], detail[:300], ip[:60]))
        c.execute("DELETE FROM security_log WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY id DESC) rn FROM security_log) WHERE rn > 5000)")
        c.commit(); c.close()
    except: pass

def get_site_theme():
    tid = cfg("site_theme", "default")
    if tid == "custom":
        return {"id":"custom","n":"مخصص","c1":cfg("site_c1","#030508"),"c2":cfg("site_c2","#0a0f18"),"ac":cfg("site_ac",SITE_COLOR)}
    for t in THEMES:
        if t["id"] == tid: return t
    return THEMES[0]

_rate_map = {}
def rate_ok(key, max_per_min=MAX_PER_MIN_TG):
    t = time.time()
    lst = _rate_map.setdefault(key, [])
    lst[:] = [x for x in lst if t - x < 60]
    if len(lst) >= max_per_min: return False
    lst.append(t); return True

# ═══ AUTH ═══
def auth(request):
    tok = request.cookies.get("rl_sid")
    if not tok or len(tok) > 200: return None
    c = db()
    row = c.execute("SELECT s.username, u.* FROM sessions s JOIN users u ON u.username=s.username WHERE s.token=? AND s.expires>? AND u.active=1 AND u.banned=0", (tok, now())).fetchone()
    c.close()
    return dict(row) if row else None

def new_session(username):
    tok = secrets.token_urlsafe(32)
    c = db()
    c.execute("INSERT INTO sessions(token,username,created,expires) VALUES(?,?,?,?)", (tok, username, now(), now()+SESSION_TTL))
    c.commit(); c.close()
    return tok

def kill_sessions(username):
    c = db(); c.execute("DELETE FROM sessions WHERE username=?", (username,)); c.commit(); c.close()

def require_auth(request):
    u = auth(request)
    if not u: raise HTTPException(401, "غير مسجل")
    return u

def require_owner(request):
    u = require_auth(request)
    if u["role"] != "owner": raise HTTPException(403, "غير مصرح")
    return u

def require_discord(request):
    u = require_auth(request)
    if u["role"] == "owner" or u.get("can_discord") == 1: return u
    raise HTTPException(403, "غير مصرح — تحتاج وصول الديسكورد")

def is_maintenance_blocking_write(u):
    if cfg("maintenance", "0") != "1": return False
    return u["role"] != "owner"

def get_user_limits(username, role):
    if role == "owner": return {"kick":9999,"yt":9999,"tg":9999,"tw":9999}
    c = db()
    u = c.execute("SELECT lim_kick,lim_yt,lim_tg,lim_tw,is_member,linked_tg_id FROM users WHERE username=?", (username,)).fetchone()
    c.close()
    if not u: u = {"lim_kick":None,"lim_yt":None,"lim_tg":None,"lim_tw":None,"is_member":0,"linked_tg_id":""}
    member = bool(u["is_member"]) and bool(u["linked_tg_id"] or "")
    d_kick = int(cfg("bonus_lim_kick","50") if member else cfg("default_lim_kick","10"))
    d_yt   = int(cfg("bonus_lim_yt","25")   if member else cfg("default_lim_yt","5"))
    d_tg   = int(cfg("bonus_lim_tg","5")    if member else cfg("default_lim_tg","1"))
    d_tw   = int(cfg("bonus_lim_tw","5")    if member else cfg("default_lim_tw","1"))
    return {
        "kick": u["lim_kick"] if u["lim_kick"] is not None else d_kick,
        "yt":   u["lim_yt"]   if u["lim_yt"]   is not None else d_yt,
        "tg":   u["lim_tg"]   if u["lim_tg"]   is not None else d_tg,
        "tw":   u["lim_tw"]   if u["lim_tw"]   is not None else d_tw,
        "is_member": member,
        "has_linked_tg": bool(u["linked_tg_id"]),
    }

def check_limit(username, kind, role, adding=1):
    if role == "owner": return True
    limit = get_user_limits(username, role).get(kind, 10)
    table = {"kick":"kick_channels","yt":"yt_channels","tg":"tg_channels","tw":"tw_channels"}[kind]
    c = db()
    n = c.execute("SELECT COUNT(*) n FROM " + table + " WHERE added_by=?", (username,)).fetchone()["n"]
    c.close()
    return (n + adding) <= limit

def limit_info(username, kind, role):
    table = {"kick":"kick_channels","yt":"yt_channels","tg":"tg_channels","tw":"tw_channels"}[kind]
    lim = get_user_limits(username, role)
    limit = lim.get(kind, 10)
    c = db()
    used = c.execute("SELECT COUNT(*) n FROM " + table + " WHERE added_by=?", (username,)).fetchone()["n"]
    c.close()
    return {"used": used, "limit": limit, "remaining": max(0, limit - used),
            "is_member": lim.get("is_member", False), "has_linked_tg": lim.get("has_linked_tg", False)}

# ═══ TELEGRAM ═══
async def tg_send(chat_id, text, image="", btn="", url="", source="system", title=""):
    if not TELEGRAM_TOKEN: return False
    if image and image.startswith('/'):
        image = (PUBLIC_URL + image) if PUBLIC_URL else ""
    markup = {"inline_keyboard": [[{"text": btn[:60], "url": url}]]} if (btn and url) else None
    base = {"chat_id": str(chat_id), "parse_mode": "HTML"}
    success = False
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            if image:
                if len(text) > 1024:
                    await c.post("https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto", json={**base,"photo":image})
                    r = await c.post("https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage", json={**base,"text":(text or ".")[:4096],"reply_markup":markup})
                    success = (r.status_code == 200)
                else:
                    r = await c.post("https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto", json={**base,"photo":image,"caption":(text or "."),"reply_markup":markup})
                    success = (r.status_code == 200)
            if not success:
                r = await c.post("https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage", json={**base,"text":(text or ".")[:4096],"reply_markup":markup})
                success = (r.status_code == 200)
                
        if success:
            c = db()
            c.execute("INSERT INTO sent_messages(tg_chat_id, source, title, body, ts) VALUES(?,?,?,?,?)", (str(chat_id), source, title[:100], re.sub(r'<[^>]+>', '', text)[:500], now()))
            c.commit(); c.close()
        return success
    except Exception as e:
        print("[TG] " + str(e)); return False

async def tg_api(method, body):
    if not TELEGRAM_TOKEN: return {"ok": False}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post("https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/" + method, json=body or {})
            return r.json()
    except Exception as e:
        print("[TG API] " + str(e)); return {"ok": False}

async def tg_save_photo(file_id):
    if not TELEGRAM_TOKEN: return ""
    j = await tg_api("getFile", {"file_id": file_id})
    if not j.get("ok"): return ""
    fp = j["result"]["file_path"]
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get("https://api.telegram.org/file/bot" + TELEGRAM_TOKEN + "/" + fp)
            if r.status_code != 200: return ""
            content = r.content
    except: return ""
    if len(content) > MAX_IMAGE_SIZE: return ""
    img_id = secrets.token_urlsafe(16)
    c = db()
    c.execute("INSERT INTO images(id,mime,data,size,uploaded_by,created) VALUES(?,?,?,?,?,?)", (img_id,"image/jpeg",content,len(content),"system",now()))
    c.commit(); c.close()
    return "/api/image/" + img_id

async def _cache_and_return_chat(chat):
    name = chat.get("title") or chat.get("username") or str(chat.get("id", ""))
    username = ("@" + chat["username"]) if chat.get("username") else ""
    photo = chat.get("photo") or {}
    photo_id = photo.get("big_file_id") or photo.get("small_file_id") or ""
    avatar = await tg_save_photo(photo_id) if photo_id else ""
    cid = str(chat.get("id", ""))
    ctype = chat.get("type", "")
    if cid:
        try:
            c = db()
            c.execute("""INSERT INTO tg_known_channels(chat_id, username, name, avatar, type, last_seen)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(chat_id) DO UPDATE SET
                username=excluded.username, name=excluded.name,
                avatar=excluded.avatar, type=excluded.type, last_seen=excluded.last_seen""",
                (cid, username, name, avatar, ctype, now()))
            c.commit(); c.close()
        except Exception as e:
            print("[TG cache save] " + str(e))
    return {"name": name, "username": username, "avatar": avatar, "chat_id": cid, "type": ctype}

async def tg_get_chat_info(chat_input):
    if not TELEGRAM_TOKEN: return None
    s = str(chat_input or "").strip()
    if not s: return None
    uname = None; numeric = None
    m = re.search(r"t\.me/([A-Za-z0-9_]{5,})", s)
    if m: uname = m.group(1)
    elif s.startswith("@"): uname = s[1:]
    elif re.match(r"^-?\d+$", s): numeric = s
    elif re.match(r"^[A-Za-z0-9_]{5,}$", s): uname = s
    if uname or numeric:
        c = db()
        try:
            row = None
            if uname:
                row = c.execute("SELECT * FROM tg_known_channels WHERE lower(username)=lower(?) OR lower(username)=lower(?)", ("@" + uname, uname)).fetchone()
            elif numeric:
                row = c.execute("SELECT * FROM tg_known_channels WHERE chat_id=?", (numeric,)).fetchone()
                if not row and numeric.startswith("-100"):
                    row = c.execute("SELECT * FROM tg_known_channels WHERE chat_id=?", (numeric[4:],)).fetchone()
            if row:
                c.close()
                return {"name": row["name"], "username": row["username"], "avatar": row["avatar"], "chat_id": row["chat_id"], "type": row["type"]}
        except Exception as e:
            print("[TG cache] " + str(e))
        finally:
            try: c.close()
            except: pass
    attempts = []
    if uname:
        attempts.append("@" + uname); attempts.append(uname)
    if numeric:
        attempts.append(numeric)
        if numeric.startswith("-100"):
            attempts.append(numeric[4:]); attempts.append("-" + numeric[4:])
        elif numeric.startswith("-"):
            attempts.append("-100" + numeric[1:]); attempts.append(numeric[1:])
        else:
            attempts.append("-100" + numeric); attempts.append("-" + numeric)
    seen = set(); last_err = ""
    for a in attempts:
        if a in seen: continue
        seen.add(a)
        try:
            j = await tg_api("getChat", {"chat_id": a})
            if j.get("ok") and j.get("result"):
                return await _cache_and_return_chat(j["result"])
            else:
                last_err = j.get("description", "")
        except Exception as e:
            last_err = str(e)
    try:
        j = await tg_api("getUpdates", {"limit": 100, "allowed_updates": ["channel_post", "my_chat_member", "message"]})
        if j.get("ok"):
            for u in j.get("result", []):
                mcm = u.get("my_chat_member") or {}
                chat = mcm.get("chat") or {}
                if chat.get("type") == "channel":
                    ch_un = (chat.get("username") or "").lower()
                    if (uname and ch_un == uname.lower()) or (numeric and str(chat.get("id")) == numeric):
                        return await _cache_and_return_chat(chat)
                cp = u.get("channel_post") or {}
                chat = cp.get("chat") or {}
                if chat.get("type") == "channel":
                    ch_un = (chat.get("username") or "").lower()
                    if (uname and ch_un == uname.lower()) or (numeric and str(chat.get("id")) == numeric):
                        return await _cache_and_return_chat(chat)
    except Exception as e:
        print("[TG getUpdates fallback] " + str(e))
    print("[TG getChat] '" + s + "' failed: " + last_err)
    return None

async def tg_get_full_admins(chat_id):
    j = await tg_api("getChatAdministrators", {"chat_id": chat_id})
    if not j.get("ok"):
        return None, j.get("description", "تعذّر جلب المشرفين")
    admins = []
    for m in j.get("result", []):
        status = m.get("status", "")
        user = m.get("user", {})
        if not user or user.get("is_bot"): continue
        is_owner = (status == "creator")
        has_all = is_owner
        if status == "administrator":
            required = ["can_manage_chat","can_post_messages","can_edit_messages","can_delete_messages","can_invite_users","can_restrict_members","can_pin_messages","can_change_info"]
            has_all = all(m.get(p, False) for p in required)
        if has_all:
            admins.append({"id": str(user["id"]),"name": " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or user.get("username", "") or str(user["id"]),"username": ("@" + user["username"]) if user.get("username") else "","is_owner": is_owner})
    admins.sort(key=lambda a: (not a["is_owner"], a["name"]))
    return admins, None

async def tg_check_membership(tg_user_id, chat_id):
    if not tg_user_id or not chat_id: return False
    j = await tg_api("getChatMember", {"chat_id": chat_id, "user_id": tg_user_id})
    if not j.get("ok"): return False
    status = j["result"].get("status", "")
    return status in ("member", "administrator", "creator")

def norm_chat(s):
    s = (s or "").strip()
    m = re.match(r"(?:https?://)?t\.me/([A-Za-z][\w]{3,})", s)
    if m: return "@" + m.group(1)
    if re.match(r"^-?\d+$", s): return s
    if re.match(r"^@[A-Za-z][\w]{3,}$", s): return s
    if re.match(r"^[A-Za-z][\w]{3,}$", s): return "@" + s
    return None

# ═══ TG VERIFY (channel ownership) ═══
async def send_verify_dm(vid, tg_user_id, site_username, chat_name):
    tpl = cfg("tpl_tg_verify", "🔐 <b>طلب توثيق قناة</b>\n\nالمستخدم <code>{site_user}</code> يحاول ربط قناة <b>{chat_name}</b>.\n\n<b>هل أنت من يحاول ذلك؟</b>")
    text = tpl.replace("{site_user}", site_username).replace("{chat_name}", chat_name)
    kb = {"inline_keyboard": [[{"text": "✅ نعم، أنا من يحاول", "callback_data": "verify_y:" + str(vid)}],[{"text": "❌ لا، ليس أنا", "callback_data": "verify_n:" + str(vid)}]]}
    j = await tg_api("sendMessage", {"chat_id": tg_user_id, "text": text, "parse_mode": "HTML", "reply_markup": kb})
    return j["result"]["message_id"] if j.get("ok") else 0

async def handle_tg_update(update):
    mcm = update.get("my_chat_member")
    if mcm:
        try:
            chat = mcm.get("chat", {})
            if chat.get("type") == "channel":
                await _cache_and_return_chat(chat)
        except Exception as e: print("[TG my_chat_member] " + str(e))
        return
    cp = update.get("channel_post")
    if cp:
        try:
            chat = cp.get("chat", {})
            if chat.get("type") == "channel":
                await _cache_and_return_chat(chat)
        except Exception as e: print("[TG channel_post] " + str(e))
        return
    cq = update.get("callback_query")
    if cq:
        data = cq.get("data", "")
        from_id = str(cq["from"]["id"])
        msg_id = cq["message"]["message_id"]
        chat_id = cq["message"]["chat"]["id"]
        try:
            if data.startswith("verify_y:"):
                vid = int(data.split(":")[1])
                c = db()
                row = c.execute("SELECT * FROM tg_verifications WHERE id=?", (vid,)).fetchone()
                if not row:
                    c.close(); await tg_api("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "انتهت الجلسة"}); return
                row = dict(row)
                if row["tg_user_id"] and row["tg_user_id"] != from_id:
                    c.close(); await tg_api("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "هذا ليس طلبك", "show_alert": True}); return
                if row["status"] != "pending":
                    c.close(); await tg_api("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "تم بالفعل"}); return
                if row["expires"] < now():
                    c.execute("UPDATE tg_verifications SET status='expired' WHERE id=?", (vid,)); c.commit(); c.close()
                    await tg_api("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "انتهت المهلة"}); return
                code = "{:06d}".format(secrets.randbelow(1000000))
                c.execute("UPDATE tg_verifications SET code=?, status='confirmed', expires=? WHERE id=?", (code, now()+300, vid)); c.commit(); c.close()
                await tg_api("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": "✅ <b>تم التأكيد</b>\n\nأدخل هذا الرمز في الموقع:\n\n<code>" + code + "</code>\n\n<i>صالح لمدة 5 دقائق</i>", "parse_mode": "HTML"})
                await tg_api("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "✅ تم"})
                return
            if data.startswith("verify_n:"):
                vid = int(data.split(":")[1])
                c = db(); c.execute("UPDATE tg_verifications SET status='cancelled' WHERE id=?", (vid,)); c.commit(); c.close()
                await tg_api("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": "❌ <b>تم الإلغاء</b>", "parse_mode": "HTML"})
                await tg_api("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "تم الإلغاء"})
                return
        except Exception as e: print("[TG callback] " + str(e))
        await tg_api("answerCallbackQuery", {"callback_query_id": cq["id"]})
        return
    msg = update.get("message")
    if msg:
        text = (msg.get("text") or "").strip()
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        is_private = chat.get("type") == "private"
        if is_private:
            if text.startswith("/start link_"):
                token = text.replace("/start link_", "").strip()
                tg_user_id = str(msg["from"]["id"])
                tg_username = "@" + msg["from"].get("username", "") if msg["from"].get("username") else ""
                tg_first_name = msg["from"].get("first_name", "")
                
                c = db()
                row = c.execute("SELECT * FROM tg_link_codes WHERE token=? AND status='pending' AND expires>?", (token, now())).fetchone()
                if row:
                    site_username = row["site_username"]
                    c.execute("UPDATE users SET linked_tg_id=?, linked_tg_username=?, linked_tg_name=?, member_checked=0 WHERE username=?", (tg_user_id, tg_username, tg_first_name, site_username))
                    c.execute("UPDATE tg_link_codes SET status='used', tg_user_id=?, tg_username=? WHERE id=?", (tg_user_id, tg_username, row["id"]))
                    c.commit()
                    c.close()
                    
                    req_ch = cfg("required_channel_id", "").strip()
                    is_mem = False
                    if req_ch:
                        is_mem = await tg_check_membership(tg_user_id, req_ch)
                    c = db()
                    c.execute("UPDATE users SET is_member=?, member_checked=? WHERE username=?", (1 if is_mem else 0, now(), site_username))
                    c.commit(); c.close()
                    
                    bot_name = cfg("bot_name_custom", "Respect Live")
                    success_msg = f"✅ <b>تم ربط حسابك بنجاح في {bot_name}!</b>\n\nيمكنك العودة إلى الموقع الآن."
                    if is_mem:
                        success_msg += "\n🎁 أنت عضو في القناة الرسمية — صلاحياتك مضاعفة!"
                    await tg_api("sendMessage", {"chat_id": chat_id, "text": success_msg, "parse_mode": "HTML"})
                else:
                    await tg_api("sendMessage", {"chat_id": chat_id, "text": "⚠️ الرابط منتهي الصلاحية أو مستخدم مسبقاً. يرجى المحاولة من الموقع مرة أخرى.", "parse_mode": "HTML"})
                return
            elif text.startswith("/start"):
                bot_name = cfg("bot_name_custom", "Respect Live")
                welcome = "👋 أهلاً بك في <b>" + bot_name + "</b>!\n\n• لربط حسابك: استخدم زر ربط الحساب في الموقع.\n• لتوثيق قناتك: استخدم زر توثيق القناة في الموقع."
                await tg_api("sendMessage", {"chat_id": chat_id, "text": welcome, "parse_mode": "HTML"})
                return

async def setup_tg_webhook():
    if not TELEGRAM_TOKEN: return
    if not PUBLIC_URL:
        print("[TG] ⚠️ PUBLIC_URL غير موجود — سيستخدم polling")
        asyncio.create_task(tg_poll_loop()); return
    url = PUBLIC_URL + "/api/telegram/webhook"
    j = await tg_api("setWebhook", {"url": url, "allowed_updates": ["message", "callback_query", "my_chat_member", "channel_post"]})
    if j.get("ok"): print("[TG] ✅ Webhook set: " + url)
    else:
        print("[TG] ❌ Webhook failed: " + str(j))
        asyncio.create_task(tg_poll_loop())

async def tg_poll_loop():
    offset = 0
    print("[TG] Polling started")
    while True:
        try:
            async with httpx.AsyncClient(timeout=35) as c:
                r = await c.post("https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/getUpdates", json={"offset": offset, "timeout": 30, "allowed_updates": ["message", "callback_query", "my_chat_member", "channel_post"]})
                j = r.json()
            if j.get("ok"):
                for u in j["result"]:
                    offset = u["update_id"] + 1
                    asyncio.create_task(handle_tg_update(u))
        except Exception as e: print("[TG poll] " + str(e))
        await asyncio.sleep(2)

# ═══ KICK + YOUTUBE + TWITTER ═══
async def kick_fetch(slug):
    h = {"User-Agent":UA,"Accept":"application/json","Referer":"https://kick.com/"}
    async with httpx.AsyncClient(timeout=15, headers=h) as c:
        for v in ("v2","v1"):
            try:
                r = await c.get("https://kick.com/api/" + v + "/channels/" + slug)
                if r.status_code == 404: continue
                if r.status_code != 200: continue
                j = r.json()
                ls = j.get("livestream") or {}
                u = j.get("user") or {}
                bn = j.get("banner_image")
                if isinstance(bn, dict): bn = bn.get("url") or ""
                return {"name":u.get("username") or slug,"avatar":u.get("profile_pic") or "","banner":bn or "","live":bool(ls.get("is_live")),"title":ls.get("session_title") or "","viewers":ls.get("viewer_count") or 0,"thumb":((ls.get("thumbnail") or {}).get("url")) or ""}
            except: pass
    return None

async def yt_feed(channel_id):
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent":UA}) as c:
            r = await c.get("https://www.youtube.com/feeds/videos.xml?channel_id=" + channel_id)
            if r.status_code != 200: return None
            items = []
            for m in re.finditer(r"<entry>(.*?)</entry>", r.text, re.S):
                e = m.group(1)
                vid = (re.search(r"<yt:videoId>([^<]+)", e) or [None,""])[1]
                title = (re.search(r"<title>([^<]*)", e) or [None,""])[1]
                pub = (re.search(r"<published>([^<]+)", e) or [None,""])[1]
                if vid: items.append({"id":vid,"title":title,"pub":pub})
            return items
    except: return None

async def yt_resolve(input_str):
    input_str = (input_str or "").strip()[:300]
    if not input_str: return None
    m = re.search(r"UC[\w-]{22}", input_str)
    if m:
        cid = m.group(0)
        try:
            async with httpx.AsyncClient(timeout=15, headers={"User-Agent":UA}) as c:
                r = await c.get("https://www.youtube.com/channel/" + cid)
                html = r.text
            title = (re.search(r'<meta property="og:title" content="([^"]*)"', html) or [None,cid])[1]
            avatar = (re.search(r'<meta property="og:image" content="([^"]*)"', html) or [None,""])[1]
            banner = (re.search(r'"banner":{"imageBannerViewModel":{"image":{"sources":\[\{"url":"([^"]*)"', html) or [None,""])[1]
            return {"channel_id":cid,"name":title,"avatar":avatar,"banner":banner}
        except: return {"channel_id":cid,"name":cid,"avatar":"","banner":""}
    h = re.search(r"@([\w.\-]+)", input_str)
    if h:
        try:
            async with httpx.AsyncClient(timeout=15, headers={"User-Agent":UA}) as c:
                r = await c.get("https://www.youtube.com/@" + h.group(1))
                html = r.text
            cid_m = re.search(r'"externalId":"(UC[\w-]{22})"', html) or re.search(r'"channelId":"(UC[\w-]{22})"', html)
            if not cid_m: return None
            cid = cid_m.group(1)
            title = (re.search(r'<meta property="og:title" content="([^"]*)"', html) or [None,cid])[1]
            avatar = (re.search(r'<meta property="og:image" content="([^"]*)"', html) or [None,""])[1]
            banner = (re.search(r'"banner":{"imageBannerViewModel":{"image":{"sources":\[\{"url":"([^"]*)"', html) or [None,""])[1]
            return {"channel_id":cid,"name":title,"avatar":avatar,"banner":banner}
        except: return None
    return None

async def get_twitter_bearer():
    return TWITTER_ENV_BEARER or cfg("twitter_bearer_token", "")

async def twitter_resolve(username, bearer):
    if not bearer: return None
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"https://api.twitter.com/2/users/by/username/{username}", headers={"Authorization": f"Bearer {bearer}"})
            if r.status_code != 200: return None
            data = r.json().get("data", {})
            return {"id": data.get("id"), "name": data.get("name"), "username": data.get("username")}
    except: return None

async def twitter_feed(user_id, bearer):
    if not bearer: return None
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            url = f"https://api.twitter.com/2/users/{user_id}/tweets?max_results=5&tweet.fields=created_at,text"
            r = await c.get(url, headers={"Authorization": f"Bearer {bearer}"})
            if r.status_code != 200: return None
            return r.json().get("data", [])
    except: return None

# ═══ PUSH ═══
def push_available(): return bool(VAPID_PUBLIC and VAPID_PRIVATE)

async def push_send_to_user(username, title, body, image="", url="/", tag=""):
    if not push_available(): return 0
    try:
        from pywebpush import webpush, WebPushException
    except ImportError: return 0
    c = db(); subs = c.execute("SELECT * FROM push_subs WHERE username=?", (username,)).fetchall(); c.close()
    if not subs: return 0
    payload = json.dumps({"title":title[:80],"body":body[:200],"image":image or "","url":url or "/","tag":tag or "rl"})
    sent = 0
    for sub in subs:
        try:
            webpush(subscription_info={"endpoint":sub["endpoint"],"keys":{"p256dh":sub["p256dh"],"auth":sub["auth"]}}, data=payload, vapid_private_key=VAPID_PRIVATE, vapid_claims={"sub":VAPID_EMAIL}, timeout=10)
            sent += 1
        except WebPushException as e:
            code = getattr(e.response,"status_code",None) if hasattr(e,"response") else None
            if code in (404,410):
                c = db(); c.execute("DELETE FROM push_subs WHERE id=?", (sub["id"],)); c.commit(); c.close()
        except: pass
    return sent

# ═══ TEXT PROCESSING ═══
_MENTION_RE = re.compile(r"<@[!&]?\d+>")
_ROLE_RE = re.compile(r"<@&\d+>")
_CHAN_RE = re.compile(r"<#\d+>")
_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")

def clean_mentions(text):
    if not text: return ""
    t = str(text)
    t = _MENTION_RE.sub("", t); t = _ROLE_RE.sub("", t); t = _CHAN_RE.sub("", t)
    t = re.sub(r"@everyone\b", "", t); t = re.sub(r"@here\b", "", t); t = _EMOJI_RE.sub("", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n", "\n\n", t)
    return t.strip()

def extract_msg(msg):
    author = msg.author.display_name or msg.author.name or ""
    author_no_at = re.sub(r"^@", "", author).strip()
    username = getattr(msg.author, "name", "")
    user_id = str(msg.author.id)
    is_bot = bool(getattr(msg.author, "bot", False))
    raw_content = (msg.content or "").strip()
    content = clean_mentions(raw_content)
    title = ""; desc = ""; img = ""; url = ""; footer = ""
    if msg.embeds:
        for e in msg.embeds:
            if e.author and e.author.name and not author:
                author = e.author.name; author_no_at = re.sub(r"^@","",author).strip()
            if e.title and not title: title = e.title.strip()
            if e.description and not desc: desc = clean_mentions(e.description.strip())
            if e.url and not url: url = e.url
            if e.footer and e.footer.text and not footer: footer = e.footer.text
            if e.image and e.image.url and not img: img = e.image.url
            elif e.thumbnail and e.thumbnail.url and not img: img = e.thumbnail.url
            try:
                if e.fields:
                    parts = []
                    for f in e.fields:
                        fname = (f.name or "").strip()
                        fval = clean_mentions((f.value or "").strip())
                        if fval: parts.append((fname + ": " + fval) if fname else fval)
                    field_text = "\n".join(parts).strip()
                    if field_text and field_text not in desc:
                        desc = (desc + "\n\n" + field_text).strip() if desc else field_text
            except: pass
    if not img and msg.attachments:
        for a in msg.attachments:
            ct = getattr(a, "content_type", "") or ""
            if ct.startswith("image/"): img = a.url; break
    if not content: content = desc or title
    final = content or desc or title
    if title and desc and title not in desc: final = title + "\n\n" + desc
    elif title and not desc: final = title
    return {"author":author[:200],"author_no_at":author_no_at[:200],"username":username[:100],"user_id":user_id,"is_bot":is_bot,"content":content[:4000],"content_raw":raw_content[:4000],"title":title[:300],"description":desc[:4000],"footer":footer[:300],"image":img,"url":url,"final_text":final[:4000],"guild_id":str(msg.guild.id) if msg.guild else "","guild_name":msg.guild.name if msg.guild else "","channel_id":str(msg.channel.id),"channel_name":getattr(msg.channel,"name","") or "","message_id":str(msg.id),"message_url":"https://discord.com/channels/" + str(msg.guild.id) + "/" + str(msg.channel.id) + "/" + str(msg.id) if msg.guild else ""}

def match_kw_full(kw_json, text, default_img="", default_text=""):
    if not kw_json: return default_img, default_text
    try: rules = json.loads(kw_json)
    except: return default_img, default_text
    if not isinstance(rules, list): return default_img, default_text
    tl = (text or "").lower()
    for rule in rules:
        if not isinstance(rule, dict): continue
        for kw in (rule.get("keywords") or []):
            if str(kw).lower() in tl:
                return (rule.get("image") or default_img, rule.get("caption") or rule.get("text") or default_text)
    return default_img, default_text

def build_text(tpl, data, site=""):
    if not tpl: tpl = "<b>{author_no_at}</b>\n\n<b>{content}</b>"
    v = {"name":data.get("author_no_at") or data.get("author") or "","author":data.get("author") or "","author_no_at":data.get("author_no_at") or "","username":data.get("username") or "","user_id":data.get("user_id") or "","content":data.get("content") or "","content_raw":data.get("content_raw") or "","description":data.get("description") or "","title":data.get("title") or "","footer":data.get("footer") or "","channel":data.get("channel_name") or "","channel_id":data.get("channel_id") or "","guild":data.get("guild_name") or "","guild_id":data.get("guild_id") or "","url":data.get("url") or data.get("message_url") or "","message_url":data.get("message_url") or "","site":site}
    return re.sub(r"\{(\w+)\}", lambda m: str(v.get(m.group(1), m.group(0))), str(tpl))

# ═══ GROQ ═══
def get_groq_key(): return GROQ_ENV_KEY or cfg("groq_api_key", "")
def groq_available(): return bool(get_groq_key())

async def groq_rewrite(text, prompt="", model=None):
    key = get_groq_key()
    if not key: return None
    model = model or cfg("groq_model", "llama-3.3-70b-versatile")
    sys = prompt.strip() if prompt else "أعد صياغة الرسالة بأسلوب واضح ومختصر بالعربية. لا تكتب أي مقدمة أو خاتمة، أعد النص فقط."
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.groq.com/openai/v1/chat/completions", headers={"authorization":"Bearer " + key,"content-type":"application/json"}, json={"model":model,"messages":[{"role":"system","content":sys},{"role":"user","content":text[:4000]}],"temperature":0.4,"max_tokens":1024})
            if r.status_code != 200: return None
            j = r.json()
            return (j.get("choices",[{}])[0].get("message",{}).get("content") or "").strip()
    except Exception as e:
        print("[Groq] " + str(e)); return None

# ═══ DISCORD ═══
_HAS_INTENTS = hasattr(discord, 'Intents')
discord_client = None
_SELF_BOT = False
if _HAS_INTENTS:
    try:
        try:
            discord_client = discord.Client(self_bot=True, intents=discord.Intents(guilds=True, guild_messages=True, message_content=True))
            _SELF_BOT = True
        except TypeError:
            intents = discord.Intents(guilds=True, guild_messages=True, message_content=True)
            discord_client = discord.Client(intents=intents)
            _SELF_BOT = False
    except Exception as e:
        print("[Discord] Init error: " + str(e)); discord_client = None
else:
    try:
        discord_client = discord.Client(self_bot=True); _SELF_BOT = True
    except Exception as e:
        print("[Discord] Init error: " + str(e)); discord_client = None

_CH_CACHE = {}; _G_CACHE = {}; _BOT_INFO = {"id":"","name":"","avatar":""}

def _refresh_cache():
    global _CH_CACHE, _G_CACHE, _BOT_INFO
    _CH_CACHE = {}; _G_CACHE = {}
    if not discord_client or not discord_client.is_ready(): return
    u = discord_client.user
    if u: _BOT_INFO = {"id":str(u.id),"name":u.name,"avatar":str(u.display_avatar.url) if u.display_avatar else ""}
    for g in discord_client.guilds:
        _G_CACHE[str(g.id)] = {"name":g.name,"id":str(g.id)}
        if ALLOWED_GUILDS and str(g.id) not in ALLOWED_GUILDS: continue
        for ch in g.text_channels:
            _CH_CACHE[str(ch.id)] = {"name":ch.name,"guild":g.name,"guild_id":str(g.id)}
    print("[Discord] Cache: " + str(len(_CH_CACHE)) + " channels")

if discord_client:
    @discord_client.event
    async def on_ready():
        print("[Discord] ✅ Logged in: " + str(discord_client.user))
        _refresh_cache()
    @discord_client.event
    async def on_guild_channel_create(channel): _refresh_cache()
    @discord_client.event
    async def on_guild_channel_delete(channel): _refresh_cache()
    @discord_client.event
    async def on_guild_join(guild): _refresh_cache()
    @discord_client.event
    async def on_guild_remove(guild): _refresh_cache()

def _feed_ignores_bot(feed, bot_id):
    try:
        ig = feed["ignore_bots"] or ""
        if not ig: return False
        bots = json.loads(ig)
        return isinstance(bots, list) and str(bot_id) in [str(x) for x in bots]
    except: return False

def _track_bot(msg):
    try:
        if not getattr(msg.author, "bot", False): return
        aid = str(msg.author.id); name = msg.author.name or ""
        avatar = str(msg.author.display_avatar.url) if getattr(msg.author, "display_avatar", None) else ""
        c = db()
        ex = c.execute("SELECT seen_count FROM discord_bots WHERE id=?", (aid,)).fetchone()
        if ex: c.execute("UPDATE discord_bots SET last_seen=?, seen_count=seen_count+1, name=?, avatar=? WHERE id=?", (now(), name, avatar, aid))
        else: c.execute("INSERT INTO discord_bots(id,name,avatar,first_seen,last_seen,seen_count) VALUES(?,?,?,?,?,1)", (aid, name, avatar, now(), now()))
        c.commit(); c.close()
    except: pass

if discord_client:
    @discord_client.event
    async def on_message(msg):
        try:
            if discord_client.user and msg.author.id == discord_client.user.id: return
            if not msg.guild: return
            if ALLOWED_GUILDS and str(msg.guild.id) not in ALLOWED_GUILDS: return
            ch_id = str(msg.channel.id)
            if getattr(msg.author, "bot", False): _track_bot(msg)
            c = db()
            feeds = c.execute("SELECT * FROM discord_feeds WHERE channel_id=? AND enabled=1", (ch_id,)).fetchall()
            if not feeds: c.close(); return
            if c.execute("SELECT 1 FROM discord_seen WHERE message_id=?", (str(msg.id),)).fetchone(): c.close(); return
            c.execute("INSERT INTO discord_seen(message_id,ts) VALUES(?,?)", (str(msg.id), now())); c.commit(); c.close()
            data = extract_msg(msg)
            if not data["final_text"] and not data["image"]: return
            site = cfg("site_name", SITE_NAME)
            for feed in feeds:
                if data["is_bot"] and _feed_ignores_bot(feed, data["user_id"]): continue
                if not rate_ok("discord:" + str(feed["id"]), max_per_min=MAX_PER_MIN_TG): continue
                use_orig = feed["use_original"] if "use_original" in feed.keys() else 1
                if use_orig:
                    text = data["final_text"] or ""
                    text = ("<b>" + data["author_no_at"] + "</b>\n\n<b>" + text + "</b>") if data["author_no_at"] else ("<b>" + text + "</b>")
                else:
                    tpl = feed["template"] or cfg("tpl_discord")
                    text = build_text(tpl, data, site)
                if (feed["use_ai"] if "use_ai" in feed.keys() else 0) and groq_available():
                    try:
                        out = await groq_rewrite(text, feed["ai_prompt"] or "")
                        if out: text = "<b>" + out + "</b>"
                    except: pass
                final_img = ""; final_text = text
                kw = feed["keyword_rules"] if "keyword_rules" in feed.keys() else ""
                if kw:
                    kw_img, kw_caption = match_kw_full(kw, text, "", "")
                    if kw_img: final_img = kw_img
                    if kw_caption: final_text = "<b>" + kw_caption + "</b>"
                if not final_img:
                    fixed = feed["fixed_image"] if "fixed_image" in feed.keys() else ""
                    final_img = fixed or data["image"]
                btn = feed["btn_text"] or cfg("btn_discord", "عرض الروم")
                room_url = (feed["room_url"] if "room_url" in feed.keys() else "") or data["message_url"]
                tg_ids_set = set()
                try:
                    for x in json.loads(feed["target_tg_ids"] or "[]"):
                        try: tg_ids_set.add(int(x))
                        except: pass
                except: pass
                c2 = db()
                subs = c2.execute("SELECT tg_channel_id FROM feed_subs WHERE feed_id=? AND enabled=1", (feed["id"],)).fetchall()
                for s in subs:
                    try: tg_ids_set.add(int(s["tg_channel_id"]))
                    except: pass
                tgs = []
                if tg_ids_set:
                    ph = ",".join("?"*len(tg_ids_set))
                    tgs = c2.execute("SELECT * FROM tg_channels WHERE enabled=1 AND id IN (" + ph + ")", tuple(tg_ids_set)).fetchall()
                c2.execute("INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) VALUES(?,?,?,?,?,?,'discord',?,0)", (feed["added_by"], data["author_no_at"] or "رسالة", re.sub(r"<[^>]+>","",final_text)[:500], final_img, btn, room_url, now()))
                c2.commit(); c2.close()
                asyncio.create_task(push_send_to_user(feed["added_by"], data["author_no_at"] or "رسالة", re.sub(r"<[^>]+>","",final_text)[:200], final_img, room_url, "discord"))
                sent_chat_ids = set()
                for tg in tgs:
                    if tg["chat_id"] in sent_chat_ids: continue
                    sent_chat_ids.add(tg["chat_id"])
                    await tg_send(tg["chat_id"], final_text, final_img, btn, room_url, "discord", data["author_no_at"] or "رسالة")
                    if tg["added_by"] != feed["added_by"]:
                        c3 = db()
                        c3.execute("INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) VALUES(?,?,?,?,?,?,'discord',?,0)", (tg["added_by"], data["author_no_at"] or "رسالة", re.sub(r"<[^>]+>","",final_text)[:500], final_img, btn, room_url, now()))
                        c3.commit(); c3.close()
                        asyncio.create_task(push_send_to_user(tg["added_by"], data["author_no_at"] or "رسالة", re.sub(r"<[^>]+>","",final_text)[:200], final_img, room_url, "discord"))
        except Exception as e: print("[Discord on_message] " + str(e))

# ═══ JOBS ═══
async def job_kick():
    c = db()
    rows = c.execute("SELECT * FROM kick_channels WHERE enabled=1 AND last_check<? ORDER BY last_check LIMIT ?", (now()-90, BATCH_KICK)).fetchall()
    c.close()
    if not rows: return
    infos = {}
    sem = asyncio.Semaphore(8)
    async def f(r):
        async with sem: infos[r["slug"]] = await kick_fetch(r["slug"])
    await asyncio.gather(*(f(r) for r in rows), return_exceptions=True)
    updates, events = [], []
    t = now()
    for r in rows:
        info = infos.get(r["slug"])
        if not info: updates.append((t, r["id"])); continue
        updates.append((info["name"],info["avatar"],info["banner"],1 if info["live"] else 0,info["title"],info["viewers"],info["thumb"],t,r["id"]))
        if info["live"] and not r["live"] and r["auto_send"]: events.append((r, info))
    c = db()
    for u in updates:
        if len(u) == 2: c.execute("UPDATE kick_channels SET last_check=? WHERE id=?", u)
        else: c.execute("UPDATE kick_channels SET name=?,avatar=?,banner=?,live=?,title=?,viewers=?,thumb=?,last_check=? WHERE id=?", u)
    c.commit(); c.close()
    async def notify(r, info):
        tpl = r["msg"] or cfg("tpl_kick")
        text = tpl.replace("{name}",info["name"]).replace("{title}",info["title"]).replace("{url}","https://kick.com/" + r["slug"])
        btn = r["btn_text"] or cfg("btn_kick","شاهد البث")
        c2 = db()
        tgs = c2.execute("SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (r["added_by"],)).fetchall()
        c2.execute("INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) VALUES(?,?,?,?,?,?,'kick',?,0)", (r["added_by"], info["name"]+" يبث الآن", info["title"], info["banner"] or info["thumb"], btn, "https://kick.com/" + r["slug"], t))
        c2.commit(); c2.close()
        asyncio.create_task(push_send_to_user(r["added_by"], info["name"]+" يبث الآن", info["title"] or "بث مباشر", info["banner"] or info["thumb"], "https://kick.com/" + r["slug"], "kick:" + str(r["id"])))
        sent = set()
        for tg in tgs:
            if tg["chat_id"] in sent: continue
            sent.add(tg["chat_id"])
            await tg_send(tg["chat_id"], text, info["banner"] or info["thumb"], btn, "https://kick.com/" + r["slug"], "kick", info["name"])
    await asyncio.gather(*(notify(r, info) for r, info in events), return_exceptions=True)

async def job_yt():
    c = db()
    rows = c.execute("SELECT * FROM yt_channels WHERE enabled=1 AND last_check<? ORDER BY last_check LIMIT ?", (now()-300, BATCH_YT)).fetchall()
    c.close()
    if not rows: return
    feeds = {}
    sem = asyncio.Semaphore(8)
    async def f(r):
        async with sem: feeds[r["channel_id"]] = await yt_feed(r["channel_id"])
    await asyncio.gather(*(f(r) for r in rows), return_exceptions=True)
    updates, new_vids = [], []
    t = now()
    for r in rows:
        items = feeds.get(r["channel_id"])
        if not items: updates.append((t, r["id"])); continue
        latest = items[0]["id"]
        if r["last_video"] and latest != r["last_video"] and r["auto_send"]:
            fresh = []
            for it in items:
                if it["id"] == r["last_video"]: break
                fresh.append(it)
            for v in reversed(fresh[:3]): new_vids.append((r, v))
        updates.append((latest, t, r["id"]))
    c = db()
    for u in updates:
        if len(u) == 2: c.execute("UPDATE yt_channels SET last_check=? WHERE id=?", u)
        else: c.execute("UPDATE yt_channels SET last_video=?,last_check=? WHERE id=?", u)
    c.commit(); c.close()
    async def notify(r, v):
        thumb = "https://i.ytimg.com/vi/" + v["id"] + "/maxresdefault.jpg"
        url = "https://youtube.com/watch?v=" + v["id"]
        tpl = r["msg"] or cfg("tpl_yt")
        text = tpl.replace("{name}",r["name"]).replace("{title}",v["title"]).replace("{url}",url)
        btn = r["btn_text"] or cfg("btn_yt","شاهد الفيديو")
        c2 = db()
        c2.execute("INSERT OR IGNORE INTO recent_videos(video_id,ch_name,title,thumb,url,ts,added_by) VALUES(?,?,?,?,?,?,?)", (v["id"],r["name"],v["title"],thumb,url,t,r["added_by"]))
        c2.execute("INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) VALUES(?,?,?,?,?,?,'yt',?,0)", (r["added_by"], "فيديو جديد من " + r["name"], v["title"], thumb, btn, url, t))
        tgs = c2.execute("SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (r["added_by"],)).fetchall()
        c2.commit(); c2.close()
        asyncio.create_task(push_send_to_user(r["added_by"], "فيديو جديد من " + r["name"], v["title"], thumb, url, "yt:" + v["id"]))
        sent = set()
        for tg in tgs:
            if tg["chat_id"] in sent: continue
            sent.add(tg["chat_id"])
            await tg_send(tg["chat_id"], text, thumb, btn, url, "youtube", r["name"])
    await asyncio.gather(*(notify(r, v) for r, v in new_vids), return_exceptions=True)

async def job_twitter():
    bearer = await get_twitter_bearer()
    if not bearer: return
    c = db()
    rows = c.execute("SELECT * FROM tw_channels WHERE enabled=1 AND last_check<? ORDER BY last_check LIMIT ?", (now()-300, BATCH_TW)).fetchall()
    c.close()
    if not rows: return
    
    updates, new_tweets = [], []
    t = now()
    for r in rows:
        user = await twitter_resolve(r["username"], bearer)
        if not user: updates.append((t, r["id"])); continue
        tweets = await twitter_feed(user["id"], bearer)
        if not tweets: updates.append((t, r["id"])); continue
        
        latest = tweets[0]["id"]
        if r["last_tweet"] and latest != r["last_tweet"] and r["auto_send"]:
            fresh = []
            for tw in tweets:
                if tw["id"] == r["last_tweet"]: break
                fresh.append(tw)
            
            filter_kws = [k.strip().lower() for k in (r["filter_kw"] or "").split(",") if k.strip()]
            for tw in reversed(fresh[:3]):
                text_lower = tw["text"].lower()
                if any(kw in text_lower for kw in filter_kws):
                    continue
                new_tweets.append((r, tw))
                
        updates.append((latest, t, r["id"]))
        
    c = db()
    for u in updates:
        if len(u) == 2: c.execute("UPDATE tw_channels SET last_check=? WHERE id=?", u)
        else: c.execute("UPDATE tw_channels SET last_tweet=?,last_check=? WHERE id=?", u)
    c.commit(); c.close()
    
    async def notify(r, tw):
        url = f"https://twitter.com/{r['username']}/status/{tw['id']}"
        tpl = r["msg"] or cfg("tpl_twitter")
        text = tpl.replace("{name}", r["name"]).replace("{content}", tw["text"]).replace("{url}", url)
        btn = r["btn_text"] or cfg("btn_tw", "عرض التغريدة")
        c2 = db()
        c2.execute("INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) VALUES(?,?,?,?,?,?,'twitter',?,0)", (r["added_by"], "تغريدة جديدة من " + r["name"], tw["text"], "", btn, url, t))
        tgs = c2.execute("SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (r["added_by"],)).fetchall()
        c2.commit(); c2.close()
        asyncio.create_task(push_send_to_user(r["added_by"], "تغريدة جديدة", tw["text"], "", url, "tw:" + tw["id"]))
        sent = set()
        for tg in tgs:
            if tg["chat_id"] in sent: continue
            sent.add(tg["chat_id"])
            await tg_send(tg["chat_id"], text, "", btn, url, "twitter", r["name"])
    await asyncio.gather(*(notify(r, tw) for r, tw in new_tweets), return_exceptions=True)

async def job_membership_check():
    req_ch = cfg("required_channel_id", "").strip()
    if not req_ch or not TELEGRAM_TOKEN: return
    c = db()
    rows = c.execute("SELECT username, linked_tg_id, is_member FROM users WHERE linked_tg_id != '' AND member_checked < ?", (now()-MEMBER_CHECK_TTL,)).fetchall()
    c.close()
    if not rows: return
    sem = asyncio.Semaphore(5)
    results = {}
    async def chk(r):
        async with sem:
            try:
                ok = await tg_check_membership(r["linked_tg_id"], req_ch)
                results[r["username"]] = ok
            except: pass
    await asyncio.gather(*(chk(r) for r in rows), return_exceptions=True)
    if not results: return
    c = db()
    for un, is_mem in results.items():
        c.execute("UPDATE users SET is_member=?, member_checked=? WHERE username=?", (1 if is_mem else 0, now(), un))
    c.commit(); c.close()
    print("[Membership] Checked " + str(len(results)) + " users")

async def job_cleanup():
    c = db()
    c.execute("DELETE FROM discord_seen WHERE ts<?", (now()-7*86400,))
    c.execute("DELETE FROM sessions WHERE expires<?", (now(),))
    c.execute("DELETE FROM rate_limits WHERE ts<?", (now()-3600,))
    c.execute("DELETE FROM security_log WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY id DESC) rn FROM security_log) WHERE rn>5000)")
    c.execute("DELETE FROM recent_videos WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY added_by ORDER BY ts DESC) rn FROM recent_videos) WHERE rn>12)")
    c.execute("DELETE FROM notifs WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY username ORDER BY ts DESC) rn FROM notifs) WHERE rn>60)")
    c.execute("DELETE FROM suggestions WHERE ts<?", (now()-90*86400,))
    c.execute("DELETE FROM tg_verifications WHERE created<?", (now()-3600,))
    c.execute("DELETE FROM tg_link_codes WHERE created<?", (now()-3600,))
    c.execute("DELETE FROM tg_known_channels WHERE last_seen<?", (now()-30*86400,))
    c.execute("DELETE FROM sent_messages WHERE ts<?", (now()-14*86400,))
    c.commit(); c.close()

# ═══ APP + SCHEDULER ═══
scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app):
    init_db()
    migrate_tg_channels_per_user()
    scheduler.add_job(job_kick, "interval", seconds=90)
    scheduler.add_job(job_yt, "interval", seconds=300)
    scheduler.add_job(job_twitter, "interval", seconds=300)
    scheduler.add_job(job_membership_check, "interval", seconds=120)
    scheduler.add_job(job_cleanup, "interval", hours=6)
    scheduler.start()
    if DISCORD_TOKEN and discord_client:
        try: asyncio.create_task(discord_client.start(DISCORD_TOKEN))
        except Exception as e: print("[Discord] Start error: " + str(e))
    else: print("[Discord] No token — HTTP-only mode")
    if TELEGRAM_TOKEN:
        try: await setup_tg_webhook()
        except Exception as e: print("[TG] webhook setup error: " + str(e))
    if push_available(): print("[Push] Enabled")
    if groq_available(): print("[Groq] Enabled")
    if await get_twitter_bearer(): print("[Twitter] Enabled")
    yield
    scheduler.shutdown(wait=False)

app = FastAPI(lifespan=lifespan)

# ═══ REGISTRATION ═══
@app.get("/api/register-status")
async def api_register_status():
    return {"enabled": cfg("registration_enabled", "1") == "1", "site_name": cfg("site_name", SITE_NAME),
            "required_channel_url": cfg("required_channel_url", ""),
            "welcome_title": cfg("signup_welcome_title", "مرحباً بك!"),
            "welcome_text": cfg("signup_welcome_text", "")}

@app.post("/api/register")
async def api_register(request: Request, response: Response, username: str = Form(...), password: str = Form(...), display: str = Form("")):
    if cfg("registration_enabled", "1") != "1":
        return JSONResponse({"error":"التسجيل مغلق حالياً"}, 403)
    un = (username or "").strip()
    pw = str(password or "")
    ip = request.client.host if request.client else ""
    if not re.match(r"^[A-Za-z0-9_.-]{3,30}$", un):
        return JSONResponse({"error":"اسم المستخدم 3-30 حرف (a-z 0-9 _ . -)"}, 400)
    if len(pw) < 6:
        return JSONResponse({"error":"كلمة المرور 6 أحرف على الأقل"}, 400)
    if not rate_ok("reg:" + ip, 3):
        return JSONResponse({"error":"عدد كبير من المحاولات، انتظر دقيقة"}, 429)
    if un.lower() == ADMIN_USERNAME.lower():
        return JSONResponse({"error":"هذا الاسم محجوز"}, 400)
    c = db()
    if c.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)", (un,)).fetchone():
        c.close(); return JSONResponse({"error":"الاسم مستخدم مسبقاً"}, 409)
    salt = secrets.token_hex(16)
    dk = max(1, int(cfg("default_lim_kick","10")))
    dy = max(1, int(cfg("default_lim_yt","5")))
    dt = max(0, int(cfg("default_lim_tg","1")))
    dw = max(0, int(cfg("default_lim_tw","1")))
    c.execute("INSERT INTO users(username,display,pass_hash,salt,role,active,banned,lim_kick,lim_yt,lim_tg,lim_tw,can_discord,created) VALUES(?,?,?,?,'user',1,0,?,?,?,?,0,?)",
        (un, (display or un)[:60].strip() or un, hash_pw(pw, salt), salt, dk, dy, dt, dw, now()))
    c.commit(); c.close()
    tok = new_session(un)
    response.set_cookie("rl_sid", tok, max_age=SESSION_TTL, httponly=True, samesite="lax", secure=False, path="/")
    log_sec(un, "register_ok", "", ip)
    return {"ok":True, "username":un, "message":"تم إنشاء الحساب! صلاحياتك محدودة. اربط حسابك في تيليجرام وانضم للقناة الرسمية للحصول على صلاحيات مضاعفة."}

# ═══ LOGIN / LOGOUT ═══
@app.post("/api/login")
async def api_login(request: Request, response: Response, u: str = Form(...), p: str = Form(...)):
    u = u.strip()[:60]
    ip = request.client.host if request.client else ""
    c = db()
    row = c.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
    c.close()
    if not row: log_sec(u, "login_fail", "no user", ip); return JSONResponse({"error":"بيانات خاطئة"}, 401)
    row = dict(row)
    if row["banned"]: log_sec(u, "login_banned", "", ip); return JSONResponse({"error":"حساب محظور"}, 403)
    if not row["active"]: return JSONResponse({"error":"حساب معطل"}, 403)
    if not secrets.compare_digest(hash_pw(p, row["salt"]), row["pass_hash"]):
        log_sec(u, "login_fail", "bad pass", ip); return JSONResponse({"error":"بيانات خاطئة"}, 401)
    tok = new_session(row["username"])
    c = db(); c.execute("UPDATE users SET last_login=? WHERE id=?", (now(), row["id"])); c.commit(); c.close()
    log_sec(u, "login_ok", "", ip)
    response.set_cookie("rl_sid", tok, max_age=SESSION_TTL, httponly=True, samesite="lax", secure=False, path="/")
    return {"ok":True,"user":{"username":row["username"],"role":row["role"]}}

@app.post("/api/logout")
async def api_logout(request: Request, response: Response):
    tok = request.cookies.get("rl_sid")
    if tok:
        c = db(); c.execute("DELETE FROM sessions WHERE token=?", (tok,)); c.commit(); c.close()
    response.delete_cookie("rl_sid", path="/")
    return {"ok":True}

# ═══ ME ═══
@app.get("/api/me")
async def api_me(request: Request):
    u = auth(request)
    if not u: return JSONResponse({"error":"غير مسجل","auth":False}, 401)
    lim = get_user_limits(u["username"], u["role"])
    return {
        "user":{"username":u["username"],"display":u["display"],"role":u["role"],"avatar":u.get("avatar",""),"can_discord":u.get("can_discord",0)==1,
                "linked_tg_id":u.get("linked_tg_id",""),"linked_tg_username":u.get("linked_tg_username",""),
                "linked_tg_name":u.get("linked_tg_name",""),"is_member":bool(u.get("is_member",0))},
        "limits":lim,
        "usage":{"kick":limit_info(u["username"],"kick",u["role"])["used"],"yt":limit_info(u["username"],"yt",u["role"])["used"],"tg":limit_info(u["username"],"tg",u["role"])["used"],"tw":limit_info(u["username"],"twitter",u["role"])["used"]},
        "tpl_kick":cfg("tpl_kick"),"tpl_yt":cfg("tpl_yt"),
        "tpl_discord":cfg("tpl_discord"),"tpl_twitter":cfg("tpl_twitter"),"tpl_youtube_dc":cfg("tpl_youtube_dc"),
        "btn_kick":cfg("btn_kick","شاهد البث"),"btn_yt":cfg("btn_yt","شاهد الفيديو"),
        "btn_tg":cfg("btn_tg","عرض القناة"),"btn_discord":cfg("btn_discord","عرض الروم"),"btn_tw":cfg("btn_tw","عرض التغريدة"),
        "site_name":cfg("site_name", SITE_NAME),"site_logo":cfg("site_logo",""),
        "site_theme":cfg("site_theme","default"),
        "has_telegram":bool(TELEGRAM_TOKEN),"has_discord":bool(DISCORD_TOKEN),
        "has_push":push_available(),"has_groq":groq_available(),"has_twitter":bool(await get_twitter_bearer()),
        "bot_ready":bool(discord_client and discord_client.is_ready()),
        "bot_name_custom":cfg("bot_name_custom","Respect Live"),
        "bot_invite_url":cfg("bot_invite_url",""),
        "self_bot_mode":_SELF_BOT,
        "required_channel_url":cfg("required_channel_url",""),
        "required_channel_name":cfg("required_channel_name",""),
        "required_channel_msg":cfg("required_channel_msg",""),
        "maintenance":cfg("maintenance","0")=="1",
        "maintenance_title":cfg("maintenance_title","🔧 صيانة مؤقتة"),
        "maintenance_text":cfg("maintenance_text",""),
    }

@app.patch("/api/me/profile")
async def api_profile(request: Request):
    u = require_auth(request)
    body = await request.json()
    sets, vals = [], []
    if "display" in body:
        d = str(body["display"]).strip()[:60]
        if d: sets.append("display=?"); vals.append(d)
    if "avatar" in body:
        sets.append("avatar=?"); vals.append(str(body["avatar"]).strip()[:500])
    if not sets: return {"ok":True}
    vals.append(u["username"])
    c = db(); c.execute("UPDATE users SET " + ", ".join(sets) + " WHERE username=?", vals); c.commit(); c.close()
    return {"ok":True}

# ═══ TG ACCOUNT LINKING (Deep Link) ═══
@app.post("/api/link-tg/deeplink")
async def api_link_tg_deeplink(request: Request):
    u = require_auth(request)
    if not TELEGRAM_TOKEN:
        return JSONResponse({"error":"توكن تيليجرام غير مضبوط"}, 400)
    if not rate_ok("linktg:" + u["username"], 5):
        return JSONResponse({"error":"عدد كبير من المحاولات"}, 429)
    
    token = secrets.token_urlsafe(16)
    c = db()
    c.execute("DELETE FROM tg_link_codes WHERE site_username=? AND status='pending'", (u["username"],))
    c.execute("INSERT INTO tg_link_codes(site_username, token, status, created, expires) VALUES(?,?,'pending',?,?)",
        (u["username"], token, now(), now() + 600))
    c.commit()
    c.close()
    
    bot_username = cfg("bot_name_custom", "Respect Live").replace(" ", "_")
    try:
        bot_info = await tg_api("getMe", {})
        if bot_info.get("ok"):
            bot_username = bot_info["result"]["username"]
    except: pass
    
    url = f"https://t.me/{bot_username}?start=link_{token}"
    return {"ok": True, "url": url, "token": token}

@app.get("/api/link-tg/check/{token}")
async def api_link_tg_check(token: str, request: Request):
    u = require_auth(request)
    c = db()
    row = c.execute("SELECT * FROM tg_link_codes WHERE token=? AND site_username=?", (token, u["username"])).fetchone()
    c.close()
    if not row: raise HTTPException(404, "Token not found")
    if row["status"] == "used":
        c = db()
        user = c.execute("SELECT linked_tg_username, is_member FROM users WHERE username=?", (u["username"],)).fetchone()
        c.close()
        return {"ok": True, "status": "used", "is_member": bool(user["is_member"]), "tg_username": user["linked_tg_username"]}
    return {"ok": True, "status": row["status"]}

@app.post("/api/link-tg/unlink")
async def api_link_tg_unlink(request: Request):
    u = require_auth(request)
    c = db()
    c.execute("UPDATE users SET linked_tg_id='', linked_tg_username='', linked_tg_name='', is_member=0, member_checked=0 WHERE username=?", (u["username"],))
    c.commit(); c.close()
    return {"ok":True}

# ═══ NEWS ═══
@app.get("/api/news")
async def api_news(request: Request):
    u = auth(request)
    c = db()
    rows = c.execute("SELECT * FROM news WHERE enabled=1 ORDER BY id DESC LIMIT 30").fetchall()
    read_ids = set()
    if u:
        rd = c.execute("SELECT news_id FROM news_read WHERE username=?", (u["username"],)).fetchall()
        read_ids = set(r["news_id"] for r in rd)
    c.close()
    out = []
    for r in rows:
        d = dict(r); d["is_read"] = d["id"] in read_ids
        out.append(d)
    return {"rows":out, "unread_count":sum(1 for r in out if not r["is_read"] and u)}

@app.post("/api/news/{nid}/read")
async def api_news_read(nid: int, request: Request):
    u = require_auth(request)
    c = db()
    c.execute("INSERT OR REPLACE INTO news_read(username, news_id, ts) VALUES(?,?,?)", (u["username"], nid, now()))
    c.commit(); c.close()
    return {"ok":True}

@app.get("/api/admin/news")
async def api_admin_news_list(request: Request):
    require_owner(request)
    c = db()
    rows = c.execute("SELECT * FROM news ORDER BY id DESC LIMIT 200").fetchall()
    c.close()
    return {"rows":[dict(r) for r in rows]}

@app.post("/api/admin/news")
async def api_admin_news_create(request: Request):
    require_owner(request)
    body = await request.json()
    title = (body.get("title") or "").strip()[:200]
    if not title: return JSONResponse({"error":"العنوان مطلوب"}, 400)
    body_ = (body.get("body") or "").strip()[:4000]
    image = (body.get("image") or "").strip()[:500]
    kind = (body.get("kind") or "news")[:30]
    c = db()
    c.execute("INSERT INTO news(title, body, image, kind, enabled, created) VALUES(?,?,?,?,1,?)",
        (title, body_, image, kind, now()))
    c.commit()
    nid = c.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
    c.close()
    return {"ok":True, "id":nid}

@app.patch("/api/admin/news/{nid}")
async def api_admin_news_patch(nid: int, request: Request):
    require_owner(request)
    body = await request.json()
    sets, vals = [], []
    if "title" in body: sets.append("title=?"); vals.append(str(body["title"])[:200])
    if "body" in body: sets.append("body=?"); vals.append(str(body["body"])[:4000])
    if "image" in body: sets.append("image=?"); vals.append(str(body["image"])[:500])
    if "kind" in body: sets.append("kind=?"); vals.append(str(body["kind"])[:30])
    if "enabled" in body: sets.append("enabled=?"); vals.append(1 if body["enabled"] else 0)
    if sets:
        vals.append(nid)
        c = db(); c.execute("UPDATE news SET " + ", ".join(sets) + " WHERE id=?", vals); c.commit(); c.close()
    return {"ok":True}

@app.delete("/api/admin/news/{nid}")
async def api_admin_news_delete(nid: int, request: Request):
    require_owner(request)
    c = db()
    c.execute("DELETE FROM news WHERE id=?", (nid,))
    c.execute("DELETE FROM news_read WHERE news_id=?", (nid,))
    c.commit(); c.close()
    return {"ok":True}

# ═══ BOOT ═══
@app.get("/api/boot")
async def api_boot():
    theme = get_site_theme()
    return {
        "site_name": cfg("site_name", SITE_NAME),"site_sub": cfg("site_sub"),
        "hero_title": cfg("hero_title"),"hero_accent": cfg("hero_accent"),"hero_text": cfg("hero_text"),
        "guest_mode": cfg("guest_mode", "1") == "1","guest_blur": int(cfg("guest_blur", "14")),
        "has_telegram": bool(TELEGRAM_TOKEN),"has_discord": bool(DISCORD_TOKEN),
        "has_push": push_available(),"has_groq": groq_available(),"has_twitter": bool(await get_twitter_bearer()),
        "discord_watching": len(_CH_CACHE),"theme": theme,"site_logo": cfg("site_logo", ""),
        "maintenance": cfg("maintenance", "0") == "1",
        "maintenance_title": cfg("maintenance_title","🔧 صيانة مؤقتة"),
        "maintenance_text": cfg("maintenance_text"),
        "registration_enabled": cfg("registration_enabled", "1") == "1",
        "bot_invite_url": cfg("bot_invite_url", ""),
        "bot_name_custom": cfg("bot_name_custom", "Respect Live"),
        "bot_ready": bool(discord_client and discord_client.is_ready()),
        "self_bot_mode": _SELF_BOT,
    }

@app.get("/api/guest-preview")
async def api_guest_preview():
    if cfg("guest_mode", "1") != "1": raise HTTPException(403, "وضع الزائر معطل")
    c = db()
    kc = c.execute("SELECT COUNT(*) n FROM kick_channels WHERE enabled=1").fetchone()["n"]
    yc = c.execute("SELECT COUNT(*) n FROM yt_channels WHERE enabled=1").fetchone()["n"]
    tc = c.execute("SELECT COUNT(*) n FROM tg_channels WHERE enabled=1").fetchone()["n"]
    twc = c.execute("SELECT COUNT(*) n FROM tw_channels WHERE enabled=1").fetchone()["n"]
    live = c.execute("SELECT slug,name,avatar,title,viewers,thumb FROM kick_channels WHERE live=1 AND enabled=1 LIMIT 6").fetchall()
    c.close()
    return {"counts":{"kick":kc,"yt":yc,"tg":tc,"tw":twc},"live":[dict(r) for r in live]}

@app.get("/api/home-stats")
async def api_home_stats(request: Request):
    u = require_auth(request)
    c = db()
    my = {"kick":c.execute("SELECT COUNT(*) n FROM kick_channels WHERE added_by=?", (u["username"],)).fetchone()["n"],
          "yt":c.execute("SELECT COUNT(*) n FROM yt_channels WHERE added_by=?", (u["username"],)).fetchone()["n"],
          "tg":c.execute("SELECT COUNT(*) n FROM tg_channels WHERE added_by=?", (u["username"],)).fetchone()["n"],
          "tw":c.execute("SELECT COUNT(*) n FROM tw_channels WHERE added_by=?", (u["username"],)).fetchone()["n"],
          "feeds":c.execute("SELECT COUNT(*) n FROM feed_subs WHERE username=? AND enabled=1", (u["username"],)).fetchone()["n"],
          "live":c.execute("SELECT COUNT(*) n FROM kick_channels WHERE added_by=? AND live=1 AND enabled=1", (u["username"],)).fetchone()["n"],
          "videos":c.execute("SELECT COUNT(*) n FROM recent_videos WHERE added_by=?", (u["username"],)).fetchone()["n"]}
    g = {"users":c.execute("SELECT COUNT(*) n FROM users WHERE active=1 AND banned=0").fetchone()["n"],
         "total_live":c.execute("SELECT COUNT(*) n FROM kick_channels WHERE live=1 AND enabled=1").fetchone()["n"],
         "discord_channels":len(_CH_CACHE),"bot_ready":bool(discord_client and discord_client.is_ready())}
    live = c.execute("SELECT slug,name,avatar,banner,thumb,title,viewers FROM kick_channels WHERE live=1 AND enabled=1 ORDER BY viewers DESC LIMIT 4").fetchall()
    vids = c.execute("SELECT video_id,ch_name,title,thumb,url FROM recent_videos WHERE added_by=? ORDER BY ts DESC LIMIT 4", (u["username"],)).fetchall()
    c.close()
    return {"my":my,"global":g,"live_now":[dict(r) for r in live],"videos":[dict(r) for r in vids]}

# ═══ CHANNELS ═══
@app.get("/api/channels/{kind}")
async def api_channels(kind: str, request: Request):
    u = require_auth(request)
    table = {"kick":"kick_channels","yt":"yt_channels","tg":"tg_channels","twitter":"tw_channels"}.get(kind)
    if not table: raise HTTPException(404)
    c = db()
    if u["role"]=="owner":
        rows = c.execute("SELECT * FROM " + table + " ORDER BY id DESC").fetchall()
    else:
        rows = c.execute("SELECT * FROM " + table + " WHERE added_by=? ORDER BY id DESC", (u["username"],)).fetchall()
    c.close()
    return {"rows":[dict(r) for r in rows],"limits":limit_info(u["username"], kind, u["role"])}

@app.get("/api/channels/{kind}/suggestions")
async def api_suggestions(kind: str, request: Request):
    u = require_auth(request)
    if kind not in ("kick","yt","tg","twitter"): raise HTTPException(404)
    table = {"kick":"kick_channels","yt":"yt_channels","tg":"tg_channels","twitter":"tw_channels"}[kind]
    ic = {"kick":"slug","yt":"channel_id","tg":"chat_id","twitter":"username"}[kind]
    c = db()
    defaults = c.execute("SELECT * FROM default_channels WHERE kind=? AND enabled=1 ORDER BY id DESC", (kind,)).fetchall()
    mine = set(r[ic] for r in c.execute("SELECT " + ic + " FROM " + table + " WHERE added_by=?", (u["username"],)).fetchall())
    c.close()
    return {"rows":[dict(r) for r in defaults if r["identifier"] not in mine]}

@app.post("/api/channels/{kind}")
async def api_add_channel(kind: str, request: Request):
    u = require_auth(request)
    if is_maintenance_blocking_write(u):
        return JSONResponse({"error":"الموقع في صيانة — لا يمكن الإضافة حالياً"}, 503)
    if not rate_ok("add:" + u["username"], MAX_PER_MIN_CH): raise HTTPException(429, "عدد كبير")
    body = await request.json()
    if kind == "tg":
        return JSONResponse({"error":"استخدم flow التوثيق"}, 400)
    c = db(); t = now(); warn = ""
    
    ident = ""
    if kind == "kick":
        ident = re.sub(r"[^a-z0-9_-]", "", (body.get("slug") or "").lower().replace("@",""))
    elif kind == "yt":
        info = await yt_resolve(body.get("channel_id") or body.get("input") or "")
        if not info: c.close(); return JSONResponse({"error":"تعذّر التعرف"},400)
        ident = info["channel_id"]
    elif kind == "twitter":
        bearer = await get_twitter_bearer()
        if not bearer: c.close(); return JSONResponse({"error":"يرجى تفعيل Twitter API من الإدارة أولاً"}, 400)
        ident = (body.get("username") or "").strip().replace("@","")
        if not ident: c.close(); return JSONResponse({"error":"اسم المستخدم مطلوب"},400)
    
    if c.execute("SELECT 1 FROM default_channels WHERE kind=? AND identifier=?", (kind, ident)).fetchone():
        c.close()
        return JSONResponse({"error":"هذه القناة موجودة في المقترحات، يرجى إضافتها من قسم المقترحات لتوفير المساحة."}, 400)

    if kind == "kick":
        if c.execute("SELECT 1 FROM kick_channels WHERE slug=? AND added_by=?", (ident, u["username"])).fetchone():
            c.close(); return JSONResponse({"error":"مضافة مسبقاً"},409)
        if not check_limit(u["username"], "kick", u["role"]):
            c.close(); i = limit_info(u["username"],"kick",u["role"]); return JSONResponse({"error":"وصلت الحد (" + str(i["limit"]) + ")"},400)
        info = await kick_fetch(ident)
        c.execute("INSERT INTO kick_channels(slug,name,avatar,banner,msg,btn_text,enabled,auto_send,live,title,viewers,thumb,last_check,added_by,created) VALUES(?,?,?,?,?,?,1,1,?,?,?,?,?,?,?)",
            (ident, (info or {}).get("name") or ident, (info or {}).get("avatar") or "", (info or {}).get("banner") or "",
             body.get("msg","")[:1500], body.get("btn_text","")[:60],
             1 if (info or {}).get("live") else 0, (info or {}).get("title") or "",
             (info or {}).get("viewers") or 0, (info or {}).get("thumb") or "", t, u["username"], t))
        if not TELEGRAM_TOKEN: warn = "⚠️ توكن تيليجرام غير مضبوط"
    elif kind == "yt":
        if c.execute("SELECT 1 FROM yt_channels WHERE channel_id=? AND added_by=?", (ident, u["username"])).fetchone():
            c.close(); return JSONResponse({"error":"مضافة مسبقاً"},409)
        if not check_limit(u["username"], "yt", u["role"]):
            c.close(); i = limit_info(u["username"],"yt",u["role"]); return JSONResponse({"error":"وصلت الحد (" + str(i["limit"]) + ")"},400)
        feed = await yt_feed(ident); last = feed[0]["id"] if feed else ""
        c.execute("INSERT INTO yt_channels(channel_id,handle,name,avatar,banner,msg,btn_text,enabled,auto_send,last_video,last_check,added_by,created) VALUES(?,?,?,?,?,?,?,1,1,?,?,?,?)",
            (ident,"",info["name"] or ident,info.get("avatar") or "",info.get("banner") or "",
             body.get("msg","")[:1500], body.get("btn_text","")[:60], last, t, u["username"], t))
        if not TELEGRAM_TOKEN: warn = "⚠️ توكن تيليجرام غير مضبوط"
    elif kind == "twitter":
        if c.execute("SELECT 1 FROM tw_channels WHERE username=? AND added_by=?", (ident, u["username"])).fetchone():
            c.close(); return JSONResponse({"error":"مضافة مسبقاً"},409)
        if not check_limit(u["username"], "twitter", u["role"]):
            c.close(); i = limit_info(u["username"],"twitter",u["role"]); return JSONResponse({"error":"وصلت الحد (" + str(i["limit"]) + ")"},400)
        
        tw_info = await twitter_resolve(ident, bearer)
        if not tw_info: c.close(); return JSONResponse({"error":"لم يتم العثور على الحساب في تويتر"}, 400)
        
        tweets = await twitter_feed(tw_info["id"], bearer)
        last_tw = tweets[0]["id"] if tweets else ""
        
        c.execute("INSERT INTO tw_channels(username,name,avatar,msg,btn_text,filter_kw,enabled,auto_send,last_tweet,last_check,added_by,created) VALUES(?,?,?,?,?,?,1,1,?,?,?,?)",
            (ident, tw_info["name"] or ident, "", body.get("msg","")[:1500], body.get("btn_text","")[:60], body.get("filter_kw","")[:500], last_tw, t, u["username"], t))
        if not TELEGRAM_TOKEN: warn = "⚠️ توكن تيليجرام غير مضبوط"
        
    c.commit(); c.close()
    return {"ok":True,"warn":warn}

@app.post("/api/channels/{kind}/bulk-add")
async def api_bulk_add(kind: str, request: Request):
    u = require_auth(request)
    if is_maintenance_blocking_write(u):
        return JSONResponse({"error":"الموقع في صيانة — لا يمكن الإضافة حالياً"}, 503)
    if kind not in ("kick","yt","twitter"): raise HTTPException(404)
    body = await request.json()
    ids = [int(x) for x in (body.get("ids") or []) if str(x).isdigit()][:50]
    if not ids: return JSONResponse({"error":"لا توجد قنوات"},400)
    info_lim = limit_info(u["username"], kind, u["role"])
    if u["role"] != "owner" and info_lim["remaining"] < len(ids):
        return JSONResponse({"error":"المتبقي " + str(info_lim["remaining"])},400)
    c = db()
    rows = c.execute("SELECT * FROM default_channels WHERE id IN (" + ",".join("?"*len(ids)) + ") AND kind=? AND enabled=1", (*ids, kind)).fetchall()
    c.close()
    if not rows: return JSONResponse({"error":"لا توجد قنوات"},404)
    added, failed, errors = 0, 0, []
    remaining = info_lim["remaining"] if u["role"] != "owner" else 9999
    
    bearer = await get_twitter_bearer() if kind == "twitter" else ""
    
    for row in rows:
        if u["role"] != "owner" and remaining <= 0:
            errors.append(row["name"] + ": وصلت الحد"); failed += 1; continue
        try:
            c = db(); t = now()
            if kind == "kick":
                if c.execute("SELECT 1 FROM kick_channels WHERE slug=? AND added_by=?", (row["identifier"], u["username"])).fetchone():
                    c.close(); failed += 1; errors.append(row["name"] + ": مضافة"); continue
                inf = await kick_fetch(row["identifier"])
                c.execute("INSERT INTO kick_channels(slug,name,avatar,banner,msg,btn_text,enabled,auto_send,live,title,viewers,thumb,last_check,added_by,created) VALUES(?,?,?,?,?,?,1,1,?,?,?,?,?,?,?)",
                    (row["identifier"], (inf or {}).get("name") or row["name"] or row["identifier"],
                     (inf or {}).get("avatar") or row["avatar"] or "", (inf or {}).get("banner") or "",
                     "","", 1 if (inf or {}).get("live") else 0, (inf or {}).get("title") or "",
                     (inf or {}).get("viewers") or 0, (inf or {}).get("thumb") or "", t, u["username"], t))
            elif kind == "yt":
                if c.execute("SELECT 1 FROM yt_channels WHERE channel_id=? AND added_by=?", (row["identifier"], u["username"])).fetchone():
                    c.close(); failed += 1; errors.append(row["name"] + ": مضافة"); continue
                feed = await yt_feed(row["identifier"]); last = feed[0]["id"] if feed else ""
                yinfo = await yt_resolve(row["identifier"])
                c.execute("INSERT INTO yt_channels(channel_id,handle,name,avatar,banner,msg,btn_text,enabled,auto_send,last_video,last_check,added_by,created) VALUES(?,?,?,?,?,?,?,1,1,?,?,?,?)",
                    (row["identifier"],"",row["name"] or row["identifier"],row["avatar"] or "",(yinfo or {}).get("banner") or "","","",last,t,u["username"],t))
            elif kind == "twitter":
                if not bearer: c.close(); failed += 1; errors.append("Twitter API not set"); continue
                if c.execute("SELECT 1 FROM tw_channels WHERE username=? AND added_by=?", (row["identifier"], u["username"])).fetchone():
                    c.close(); failed += 1; errors.append(row["name"] + ": مضافة"); continue
                tw_info = await twitter_resolve(row["identifier"], bearer)
                tweets = await twitter_feed(tw_info["id"], bearer) if tw_info else []
                last_tw = tweets[0]["id"] if tweets else ""
                c.execute("INSERT INTO tw_channels(username,name,avatar,msg,btn_text,filter_kw,enabled,auto_send,last_tweet,last_check,added_by,created) VALUES(?,?,?,?,?,?,1,1,?,?,?,?)",
                    (row["identifier"], (tw_info or {}).get("name", row["name"]), "", "", "", "", last_tw, t, u["username"], t))
            
            c.commit(); c.close()
            added += 1
            if u["role"] != "owner": remaining -= 1
        except Exception as e:
            failed += 1; errors.append(row["name"] + ": " + str(e)[:60])
    return {"ok":True,"added":added,"failed":failed,"errors":errors}

@app.delete("/api/channels/{kind}/{cid}")
async def api_del_channel(kind: str, cid: int, request: Request):
    u = require_auth(request)
    table = {"kick":"kick_channels","yt":"yt_channels","tg":"tg_channels","twitter":"tw_channels"}.get(kind)
    if not table: raise HTTPException(404)
    c = db()
    row = c.execute("SELECT * FROM " + table + " WHERE id=?", (cid,)).fetchone()
    if not row: c.close(); raise HTTPException(404)
    if u["role"] != "owner" and row["added_by"] != u["username"]: c.close(); raise HTTPException(403)
    if kind == "tg":
        c.execute("DELETE FROM feed_subs WHERE tg_channel_id=?", (cid,))
        c.execute("DELETE FROM sent_messages WHERE tg_chat_id=?", (row["chat_id"],))
    c.execute("DELETE FROM " + table + " WHERE id=?", (cid,))
    c.commit(); c.close()
    return {"ok":True}

@app.patch("/api/channels/{kind}/{cid}")
async def api_patch_channel(kind: str, cid: int, request: Request):
    u = require_auth(request)
    table = {"kick":"kick_channels","yt":"yt_channels","tg":"tg_channels","twitter":"tw_channels"}.get(kind)
    if not table: raise HTTPException(404)
    body = await request.json()
    c = db()
    row = c.execute("SELECT * FROM " + table + " WHERE id=?", (cid,)).fetchone()
    if not row: c.close(); raise HTTPException(404)
    if u["role"] != "owner" and row["added_by"] != u["username"]: c.close(); raise HTTPException(403)
    sets, vals = [], []
    if "enabled" in body: sets.append("enabled=?"); vals.append(1 if body["enabled"] else 0)
    if "auto_send" in body and kind != "tg": sets.append("auto_send=?"); vals.append(1 if body["auto_send"] else 0)
    if "msg" in body and kind != "tg": sets.append("msg=?"); vals.append(str(body["msg"])[:1500])
    if "btn_text" in body and kind != "tg": sets.append("btn_text=?"); vals.append(str(body["btn_text"])[:60])
    if "name" in body: sets.append("name=?"); vals.append(str(body["name"])[:80])
    if "filter_kw" in body and kind == "twitter": sets.append("filter_kw=?"); vals.append(str(body["filter_kw"])[:500])
    if "avatar" in body and kind == "tg": sets.append("avatar=?"); vals.append(str(body["avatar"])[:500])
    if "banner" in body and kind in ("yt","tg"): sets.append("banner=?"); vals.append(str(body["banner"])[:500])
    if sets:
        vals.append(cid)
        c.execute("UPDATE " + table + " SET " + ", ".join(sets) + " WHERE id=?", vals)
        c.commit()
    c.close()
    return {"ok":True}

@app.post("/api/channels/{kind}/{cid}/refresh")
async def api_refresh_channel(kind: str, cid: int, request: Request):
    u = require_auth(request)
    if kind not in ("tg","yt","twitter"): raise HTTPException(404)
    table = {"tg":"tg_channels","yt":"yt_channels","twitter":"tw_channels"}[kind]
    c = db()
    row = c.execute("SELECT * FROM " + table + " WHERE id=?", (cid,)).fetchone()
    if not row: c.close(); raise HTTPException(404)
    if u["role"] != "owner" and row["added_by"] != u["username"]: c.close(); raise HTTPException(403)
    if kind == "tg":
        info = await tg_get_chat_info(row["chat_id"])
        if not info: c.close(); return JSONResponse({"error":"تعذّر الجلب — تأكد أن البوت مضاف كمشرف"},400)
        c.execute("UPDATE tg_channels SET name=?,username=?,avatar=? WHERE id=?", (info["name"],info["username"] or row["username"],info["avatar"] or row["avatar"],cid))
    elif kind == "yt":
        info = await yt_resolve(row["channel_id"])
        if not info: c.close(); return JSONResponse({"error":"تعذّر الجلب"},400)
        c.execute("UPDATE yt_channels SET name=?,avatar=?,banner=? WHERE id=?", (info["name"] or row["name"],info.get("avatar") or row["avatar"],info.get("banner") or row["banner"],cid))
    else:
        bearer = await get_twitter_bearer()
        info = await twitter_resolve(row["username"], bearer)
        if not info: c.close(); return JSONResponse({"error":"تعذّر الجلب"},400)
        c.execute("UPDATE tw_channels SET name=? WHERE id=?", (info["name"] or row["name"], cid))
    
    c.commit(); c.close()
    return {"ok":True}

@app.get("/api/tg/{cid}/messages")
async def api_tg_messages(cid: int, request: Request):
    u = require_auth(request)
    c = db()
    row = c.execute("SELECT * FROM tg_channels WHERE id=? AND added_by=?", (cid, u["username"])).fetchone()
    if not row and u["role"] != "owner":
        c.close(); raise HTTPException(403)
    
    chat_id = row["chat_id"]
    msgs = c.execute("SELECT * FROM sent_messages WHERE tg_chat_id=? ORDER BY ts DESC LIMIT 30", (chat_id,)).fetchall()
    c.close()
    return {"rows": [dict(m) for m in msgs]}

# ═══ TG VERIFY FLOW ═══
@app.post("/api/tg/verify/start")
async def tg_verify_start(request: Request):
    u = require_auth(request)
    if is_maintenance_blocking_write(u):
        return JSONResponse({"error":"الموقع في صيانة — لا يمكن التوثيق حالياً"}, 503)
    if not TELEGRAM_TOKEN:
        return JSONResponse({"error":"توكن تيليجرام غير مضبوط"}, 400)
    if not rate_ok("tgv:" + u["username"], 5):
        return JSONResponse({"error":"عدد كبير من المحاولات، انتظر دقيقة"}, 429)
    body = await request.json()
    chat_input = (body.get("chat_id") or "").strip()
    chat_id = norm_chat(chat_input)
    if not chat_id:
        return JSONResponse({"error":"معرّف القناة غير صالح"}, 400)
    chat_info = await tg_get_chat_info(chat_id)
    if not chat_info:
        return JSONResponse({"error":"تعذّر الوصول للقناة.\n\nتأكد من:\n• إضافة البوت كمشرف\n• كتابة المعرّف بشكل صحيح\n• انشر أي رسالة في القناة أولاً"}, 400)
    c = db()
    
    if c.execute("SELECT 1 FROM default_channels WHERE kind='tg' AND identifier=?", (chat_info["chat_id"],)).fetchone():
        c.close()
        return JSONResponse({"error":"هذه القناة موجودة في المقترحات، يرجى إضافتها من قسم المقترحات لتوفير المساحة."}, 400)

    ex = c.execute("SELECT 1 FROM tg_channels WHERE chat_id=? AND added_by=?", (chat_info["chat_id"], u["username"])).fetchone()
    if ex: c.close(); return JSONResponse({"error":"أنت أضفت هذه القناة مسبقاً"}, 409)
    if not check_limit(u["username"], "tg", u["role"]):
        c.close(); i = limit_info(u["username"],"tg",u["role"])
        return JSONResponse({"error":"وصلت الحد (" + str(i["limit"]) + ")"}, 400)
    old = c.execute("SELECT id FROM tg_verifications WHERE tg_chat_id=? AND site_username=? AND status IN ('pending','awaiting_admin') AND expires>?", (chat_info["chat_id"], u["username"], now())).fetchone()
    if old: c.close(); return JSONResponse({"error":"يوجد طلب معلق"}, 409)
    c.close()
    admins, adm_err = await tg_get_full_admins(chat_info["chat_id"])
    if admins is None:
        return JSONResponse({"error":"تعذّر جلب مشرفي القناة.\n" + adm_err}, 400)
    if not admins:
        return JSONResponse({"error":"لا يوجد مشرف في القناة يملك كل الصلاحيات"}, 400)
    t = now()
    c = db()
    c.execute("INSERT INTO tg_verifications(site_username,tg_username,tg_user_id,tg_chat_id,tg_chat_name,tg_chat_avatar,status,created,expires) VALUES(?,?,?,?,?,?,'awaiting_admin',?,?)",
        (u["username"], "", "", chat_info["chat_id"], chat_info["name"], chat_info["avatar"], t, t + VERIFY_TTL))
    c.commit()
    vid = c.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
    c.close()
    return {"ok": True, "verify_id": vid, "chat_name": chat_info["name"], "chat_avatar": chat_info["avatar"], "admins": admins, "auto_admin_id": admins[0]["id"], "expires": VERIFY_TTL}

@app.post("/api/tg/verify/{vid}/send")
async def tg_verify_send(vid: int, request: Request):
    u = require_auth(request)
    body = await request.json()
    admin_id = (body.get("admin_id") or "").strip()
    if not admin_id: return JSONResponse({"error":"لم يتم اختيار مشرف"}, 400)
    c = db()
    row = c.execute("SELECT * FROM tg_verifications WHERE id=? AND site_username=?", (vid, u["username"])).fetchone()
    if not row: c.close(); return JSONResponse({"error":"طلب غير موجود"}, 404)
    row = dict(row)
    if row["status"] != "awaiting_admin": c.close(); return JSONResponse({"error":"حالة غير صحيحة"}, 400)
    if row["expires"] < now(): c.close(); return JSONResponse({"error":"انتهت المهلة"}, 400)
    c.close()
    admins, _ = await tg_get_full_admins(row["tg_chat_id"])
    if not admins: return JSONResponse({"error":"تعذّر التحقق من المشرفين"}, 400)
    valid_admin = next((a for a in admins if a["id"] == admin_id), None)
    if not valid_admin: return JSONResponse({"error":"هذا المشرف لا يملك صلاحيات كاملة"}, 400)
    c = db()
    c.execute("UPDATE tg_verifications SET tg_user_id=?, tg_username=?, status='pending', expires=? WHERE id=?", (admin_id, valid_admin["username"], now() + VERIFY_TTL, vid))
    c.commit(); c.close()
    msg_id = await send_verify_dm(vid, admin_id, u["username"], row["tg_chat_name"])
    if not msg_id:
        c = db(); c.execute("UPDATE tg_verifications SET status='awaiting_admin' WHERE id=?", (vid,)); c.commit(); c.close()
        return JSONResponse({"error":"تعذّر الإرسال — المشرف يحتاج فتح البوت /start أولاً"}, 400)
    c = db(); c.execute("UPDATE tg_verifications SET tg_msg_id=? WHERE id=?", (msg_id, vid)); c.commit(); c.close()
    return {"ok": True, "admin_name": valid_admin["name"]}

@app.get("/api/tg/verify/{vid}")
async def tg_verify_status(vid: int, request: Request):
    u = require_auth(request)
    c = db()
    row = c.execute("SELECT * FROM tg_verifications WHERE id=? AND site_username=?", (vid, u["username"])).fetchone()
    c.close()
    if not row: raise HTTPException(404)
    row = dict(row)
    if row["status"] in ("pending","awaiting_admin") and row["expires"] < now():
        c = db(); c.execute("UPDATE tg_verifications SET status='expired' WHERE id=?", (vid,)); c.commit(); c.close()
        row["status"] = "expired"
    return {"status": row["status"], "chat_name": row["tg_chat_name"], "chat_avatar": row["tg_chat_avatar"], "expires_in": max(0, row["expires"] - now())}

@app.post("/api/tg/verify/{vid}/code")
async def tg_verify_code(vid: int, request: Request):
    u = require_auth(request)
    body = await request.json()
    code = (body.get("code") or "").strip()
    if not re.match(r"^\d{6}$", code): return JSONResponse({"error":"الرمز 6 أرقام"}, 400)
    c = db()
    row = c.execute("SELECT * FROM tg_verifications WHERE id=? AND site_username=?", (vid, u["username"])).fetchone()
    if not row: c.close(); return JSONResponse({"error":"طلب غير موجود"}, 404)
    row = dict(row)
    if row["status"] == "used": c.close(); return JSONResponse({"error":"مستخدم"}, 400)
    if row["status"] != "confirmed": c.close(); return JSONResponse({"error":"لم يتم التأكيد من تيليجرام"}, 400)
    if row["expires"] < now(): c.close(); return JSONResponse({"error":"انتهت الصلاحية"}, 400)
    if row["code"] != code: c.close(); return JSONResponse({"error":"رمز خاطئ"}, 400)
    ex = c.execute("SELECT 1 FROM tg_channels WHERE chat_id=? AND added_by=?", (row["tg_chat_id"], u["username"])).fetchone()
    if ex: c.close(); return JSONResponse({"error":"مضافة مسبقاً"}, 409)
    t = now()
    c.execute("INSERT INTO tg_channels(chat_id,username,name,avatar,banner,enabled,verified,owner_tg_id,owner_tg_username,added_by,created) VALUES(?,?,?,?,?,1,1,?,?,?,?)",
        (row["tg_chat_id"], row["tg_username"], row["tg_chat_name"], row["tg_chat_avatar"], "", row["tg_user_id"], row["tg_username"], u["username"], t))
    c.execute("UPDATE tg_verifications SET status='used' WHERE id=?", (vid,))
    c.commit(); c.close()
    log_sec(u["username"], "tg_verify_ok", row["tg_chat_id"], "")
    try:
        success_tpl = cfg("tpl_tg_success", "✅ <b>تم الربط بنجاح</b>\n\nالقناة: <b>{chat_name}</b>\nالمستخدم: <code>{site_user}</code>")
        success_text = success_tpl.replace("{chat_name}", row["tg_chat_name"]).replace("{site_user}", u["username"])
        if row["tg_user_id"]: await tg_api("sendMessage", {"chat_id": row["tg_user_id"], "text": success_text, "parse_mode": "HTML"})
        c2 = db()
        c2.execute("INSERT INTO notifs(username,title,body,kind,ts,is_read) VALUES(?,?,?,'tg_verify',?,0)", (u["username"], "✅ تم ربط القناة", "تم ربط قناة " + row["tg_chat_name"] + " بنجاح بحسابك", now()))
        c2.commit(); c2.close()
    except Exception as e: print("[TG success] " + str(e))
    return {"ok":True}

@app.post("/api/tg/verify/{vid}/cancel")
async def tg_verify_cancel(vid: int, request: Request):
    u = require_auth(request)
    c = db()
    c.execute("UPDATE tg_verifications SET status='cancelled' WHERE id=? AND site_username=? AND status IN ('pending','awaiting_admin')", (vid, u["username"]))
    c.commit(); c.close()
    return {"ok":True}

# ═══ SEND ═══
@app.get("/api/send/prefill")
async def api_send_prefill(request: Request):
    u = require_auth(request)
    c = db()
    if u["role"] == "owner":
        tgs = c.execute("SELECT id,name,username,avatar,enabled FROM tg_channels ORDER BY id DESC").fetchall()
        users = c.execute("SELECT id,username,display FROM users WHERE active=1 AND banned=0 ORDER BY username").fetchall()
    else:
        tgs = c.execute("SELECT id,name,username,avatar,enabled FROM tg_channels WHERE added_by=? ORDER BY id DESC", (u["username"],)).fetchall()
        users = []
    c.close()
    return {"tgs":[dict(r) for r in tgs],"users":[dict(r) for r in users],"is_owner":u["role"]=="owner"}

@app.post("/api/send")
async def api_send(request: Request):
    u = require_auth(request)
    if is_maintenance_blocking_write(u):
        return JSONResponse({"error":"الموقع في صيانة — لا يمكن الإرسال حالياً"}, 503)
    if not rate_ok("send:" + u["username"], 10): return JSONResponse({"error":"عدد كبير"},429)
    body = await request.json()
    text = (body.get("text") or "").strip()
    image = (body.get("image") or "").strip()[:500]
    btn_text = (body.get("btn_text") or "").strip()[:60]
    btn_url = (body.get("btn_url") or "").strip()[:2000]
    if not text and not image: return JSONResponse({"error":"لا يوجد محتوى"},400)
    out = {"tg_sent":0,"tg_failed":0,"users":0}
    tg_mode = (body.get("tg") or {}).get("mode","none")
    tg_ids = (body.get("tg") or {}).get("ids",[])
    rows = []
    if tg_mode == "all" and TELEGRAM_TOKEN:
        c = db()
        if u["role"] == "owner": rows = c.execute("SELECT * FROM tg_channels WHERE enabled=1").fetchall()
        else: rows = c.execute("SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (u["username"],)).fetchall()
        c.close()
    elif tg_mode == "pick" and TELEGRAM_TOKEN and tg_ids:
        ids_c = [int(x) for x in tg_ids if str(x).isdigit()][:50]
        if ids_c:
            c = db()
            if u["role"] == "owner": rows = c.execute("SELECT * FROM tg_channels WHERE id IN (" + ",".join("?"*len(ids_c)) + ")", tuple(ids_c)).fetchall()
            else: rows = c.execute("SELECT * FROM tg_channels WHERE added_by=? AND id IN (" + ",".join("?"*len(ids_c)) + ")", (u["username"],*ids_c)).fetchall()
            c.close()
    sent_chat_ids = set()
    for tg in rows:
        if tg["chat_id"] in sent_chat_ids: continue
        sent_chat_ids.add(tg["chat_id"])
        try:
            r = await tg_send(tg["chat_id"], text, image, btn_text, btn_url, "system", "رسالة إدارية")
            if r: out["tg_sent"] += 1
            else: out["tg_failed"] += 1
        except: out["tg_failed"] += 1
    us_mode = (body.get("users") or {}).get("mode","none")
    if us_mode != "none" and u["role"] == "owner":
        c = db()
        if us_mode == "all":
            us = c.execute("SELECT username,display FROM users WHERE active=1 AND banned=0").fetchall()
        else:
            ids_c = [int(x) for x in (body.get("users") or {}).get("ids",[]) if str(x).isdigit()][:500]
            us = c.execute("SELECT username,display FROM users WHERE active=1 AND banned=0 AND id IN (" + ",".join("?"*len(ids_c)) + ")", tuple(ids_c)).fetchall() if ids_c else []
        c.close()
        for tgt in us:
            c = db()
            c.execute("INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) VALUES(?,?,?,?,?,?,'admin',?,0)", (tgt["username"],"رسالة من الإدارة",text[:500],image,btn_text,btn_url,now()))
            c.commit(); c.close()
            asyncio.create_task(push_send_to_user(tgt["username"],"رسالة من الإدارة",text[:200],image,btn_url or "/","admin"))
            out["users"] += 1
    return {"ok":True,"result":out}

# ═══ DISCORD ═══
@app.get("/api/discord/channels")
async def api_dc_channels(request: Request):
    require_discord(request)
    return {"channels":_CH_CACHE,"guilds":_G_CACHE,"watching":list(_CH_CACHE.keys()) if not WATCH_CHANNELS else WATCH_CHANNELS,
            "auto_discovery":not bool(WATCH_CHANNELS),"bot_ready":bool(discord_client and discord_client.is_ready()),
            "bot_info":_BOT_INFO,"bot_name_custom":cfg("bot_name_custom","Respect Live"),
            "bot_invite_url":cfg("bot_invite_url",""),"self_bot_mode":_SELF_BOT}

@app.post("/api/discord/refresh")
async def api_dc_refresh(request: Request):
    require_discord(request)
    _refresh_cache()
    return {"ok":True,"channels":len(_CH_CACHE),"guilds":len(_G_CACHE),"bot_ready":bool(discord_client and discord_client.is_ready())}

@app.get("/api/discord/bots")
async def api_dc_bots(request: Request):
    require_discord(request)
    c = db()
    rows = c.execute("SELECT id,name,avatar,last_seen,seen_count FROM discord_bots ORDER BY last_seen DESC LIMIT 200").fetchall()
    c.close()
    return {"rows":[dict(r) for r in rows]}

@app.get("/api/discord/feeds")
async def api_dc_feeds(request: Request):
    u = require_discord(request)
    is_owner_user = u["role"] == "owner"
    c = db()
    if is_owner_user: rows = c.execute("SELECT * FROM discord_feeds ORDER BY id DESC").fetchall()
    else: rows = c.execute("SELECT * FROM discord_feeds WHERE enabled=1 ORDER BY id DESC").fetchall()
    my_subs = {}
    if is_owner_user: subs_rows = c.execute("SELECT feed_id, tg_channel_id FROM feed_subs").fetchall()
    else: subs_rows = c.execute("SELECT feed_id, tg_channel_id FROM feed_subs WHERE username=?", (u["username"],)).fetchall()
    for s in subs_rows: my_subs.setdefault(s["feed_id"], []).append(s["tg_channel_id"])
    if is_owner_user: tgs = c.execute("SELECT id,name,username,avatar,enabled FROM tg_channels WHERE enabled=1 ORDER BY id DESC").fetchall()
    else: tgs = c.execute("SELECT id,name,username,avatar,enabled FROM tg_channels WHERE added_by=? AND enabled=1 ORDER BY id DESC", (u["username"],)).fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r); d["my_subs"] = my_subs.get(d["id"], []); out.append(d)
    return {"rows":out,"known_channels":_CH_CACHE,"guilds":_G_CACHE,
            "watching":list(_CH_CACHE.keys()) if not WATCH_CHANNELS else WATCH_CHANNELS,
            "auto_discovery":not bool(WATCH_CHANNELS),"bot_ready":bool(discord_client and discord_client.is_ready()),
            "bot_info":_BOT_INFO if is_owner_user else {"name":"","avatar":""},
            "bot_name_custom":cfg("bot_name_custom","Respect Live"),
            "bot_invite_url":cfg("bot_invite_url","") if is_owner_user else "",
            "self_bot_mode":_SELF_BOT,
            "is_owner":is_owner_user,"my_tgs":[dict(r) for r in tgs]}

@app.post("/api/discord/feeds")
async def api_dc_add_feed(request: Request):
    u = require_owner(request)
    body = await request.json()
    ch = str(body.get("channel_id") or "").strip()
    if not ch or not ch.isdigit(): return JSONResponse({"error":"channel_id يجب أن يكون رقماً"},400)
    if ch not in _CH_CACHE and (not WATCH_CHANNELS or ch not in WATCH_CHANNELS):
        return JSONResponse({"error":"الروم غير موجود"},400)
    name = str(body.get("channel_name") or "")[:100] or (_CH_CACHE.get(ch,{}).get("name") or ch)
    tpl = str(body.get("template") or "")[:2000]
    btn = str(body.get("btn_text") or "عرض الروم")[:60]
    src = str(body.get("source_type") or "generic")[:20]
    gid = str(body.get("guild_id") or "")[:30]
    use_orig = 1 if body.get("use_original", True) else 0
    ig_bots = [str(x) for x in (body.get("ignore_bots") or [])][:50]
    kw = body.get("keyword_rules") or []
    if not isinstance(kw, list): kw = []
    fixed = str(body.get("fixed_image") or "")[:500]
    room_url = str(body.get("room_url") or "")[:500]
    use_ai = 1 if body.get("use_ai") else 0
    ai_p = str(body.get("ai_prompt") or "")[:2000]
    c = db()
    if c.execute("SELECT 1 FROM discord_feeds WHERE channel_id=?", (ch,)).fetchone():
        c.close(); return JSONResponse({"error":"الروم مضاف مسبقاً"},409)
    c.execute("INSERT INTO discord_feeds(channel_id,channel_name,guild_id,template,btn_text,source_type,target_tg_ids,enabled,use_original,ignore_bots,keyword_rules,fixed_image,room_url,use_ai,ai_prompt,added_by,created) VALUES(?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?)",
        (ch,name,gid,tpl,btn,src,"[]",use_orig,json.dumps(ig_bots),json.dumps(kw),fixed,room_url,use_ai,ai_p,u["username"],now()))
    c.commit(); c.close()
    return {"ok":True}

@app.patch("/api/discord/feeds/{fid}")
async def api_dc_patch_feed(fid: int, request: Request):
    u = require_owner(request)
    body = await request.json()
    c = db()
    if not c.execute("SELECT 1 FROM discord_feeds WHERE id=?", (fid,)).fetchone():
        c.close(); raise HTTPException(404)
    sets, vals = [], []
    for f in ("template","btn_text","fixed_image","room_url","ai_prompt"):
        if f in body: sets.append(f + "=?"); vals.append(str(body[f])[:2000])
    for f in ("enabled","use_original","use_ai"):
        if f in body: sets.append(f + "=?"); vals.append(1 if body[f] else 0)
    if "ignore_bots" in body: sets.append("ignore_bots=?"); vals.append(json.dumps([str(x) for x in (body["ignore_bots"] or [])][:50]))
    if "keyword_rules" in body:
        kw = body["keyword_rules"] or []
        if not isinstance(kw, list): kw = []
        sets.append("keyword_rules=?"); vals.append(json.dumps(kw))
    if sets:
        vals.append(fid)
        c.execute("UPDATE discord_feeds SET " + ", ".join(sets) + " WHERE id=?", vals)
        c.commit()
    c.close()
    return {"ok":True}

@app.delete("/api/discord/feeds/{fid}")
async def api_dc_del_feed(fid: int, request: Request):
    u = require_owner(request)
    c = db()
    c.execute("DELETE FROM feed_subs WHERE feed_id=?", (fid,))
    c.execute("DELETE FROM discord_feeds WHERE id=?", (fid,))
    c.commit(); c.close()
    return {"ok":True}

@app.post("/api/discord/feeds/{fid}/subscribe")
async def api_dc_feed_sub(fid: int, request: Request):
    u = require_discord(request)
    body = await request.json()
    tg_ids = [int(x) for x in (body.get("tg_channel_ids") or []) if str(x).isdigit()][:50]
    c = db()
    if not c.execute("SELECT 1 FROM discord_feeds WHERE id=?", (fid,)).fetchone():
        c.close(); raise HTTPException(404)
    my_channels = set()
    for x in c.execute("SELECT id FROM tg_channels WHERE added_by=?", (u["username"],)).fetchall(): my_channels.add(x["id"])
    c.execute("DELETE FROM feed_subs WHERE feed_id=? AND username=?", (fid, u["username"]))
    for tid in tg_ids:
        if tid in my_channels:
            c.execute("INSERT OR IGNORE INTO feed_subs(feed_id, tg_channel_id, username, enabled, created) VALUES(?,?,?,1,?)", (fid, tid, u["username"], now()))
    c.commit(); c.close()
    return {"ok":True}

# ═══ NOTIFS ═══
@app.get("/api/notifs")
async def api_notifs(request: Request):
    u = require_auth(request)
    c = db()
    unread = c.execute("SELECT COUNT(*) n FROM notifs WHERE username=? AND is_read=0", (u["username"],)).fetchone()["n"]
    if request.query_params.get("count"): c.close(); return {"unread":unread}
    rows = c.execute("SELECT * FROM notifs WHERE username=? ORDER BY ts DESC LIMIT 50", (u["username"],)).fetchall()
    c.close()
    return {"rows":[dict(r) for r in rows],"unread":unread}

@app.post("/api/notifs/read-all")
async def api_notifs_readall(request: Request):
    u = require_auth(request)
    c = db(); c.execute("UPDATE notifs SET is_read=1 WHERE username=?", (u["username"],)); c.commit(); c.close()
    return {"ok":True}

@app.post("/api/notifs/clear")
async def api_notifs_clear(request: Request):
    u = require_auth(request)
    c = db(); c.execute("DELETE FROM notifs WHERE username=?", (u["username"],)); c.commit(); c.close()
    return {"ok":True}

# ═══ SUGGESTIONS ═══
@app.post("/api/suggestions")
async def api_suggest(request: Request):
    u = require_auth(request)
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text: return JSONResponse({"error":"النص فارغ"},400)
    if len(text) > 1000: return JSONResponse({"error":"الحد 1000 حرف"},400)
    if not rate_ok("sug:" + u["username"],3): return JSONResponse({"error":"عدد كبير"},429)
    c = db(); c.execute("INSERT INTO suggestions(username,text,is_read,ts) VALUES(?,?,0,?)", (u["username"],text[:1000],now())); c.commit(); c.close()
    return {"ok":True}

@app.get("/api/admin/suggestions")
async def api_admin_sug(request: Request):
    require_owner(request)
    c = db()
    unread = c.execute("SELECT COUNT(*) n FROM suggestions WHERE is_read=0").fetchone()["n"]
    rows = c.execute("SELECT * FROM suggestions ORDER BY ts DESC LIMIT 200").fetchall()
    c.close()
    return {"rows":[dict(r) for r in rows],"unread":unread}

@app.patch("/api/admin/suggestions/{sid}")
async def api_admin_patch_sug(sid: int, request: Request):
    require_owner(request)
    body = await request.json()
    c = db()
    if "is_read" in body:
        c.execute("UPDATE suggestions SET is_read=? WHERE id=?", (1 if body["is_read"] else 0, sid)); c.commit()
    c.close()
    return {"ok":True}

@app.delete("/api/admin/suggestions/{sid}")
async def api_admin_del_sug(sid: int, request: Request):
    require_owner(request)
    c = db(); c.execute("DELETE FROM suggestions WHERE id=?", (sid,)); c.commit(); c.close()
    return {"ok":True}

# ═══ PUSH ═══
@app.get("/api/push/key")
async def api_push_key():
    if not push_available(): return JSONResponse({"error":"Push غير مفعّل"},404)
    return {"key":VAPID_PUBLIC}

@app.post("/api/push/subscribe")
async def api_push_sub(request: Request):
    u = require_auth(request)
    if not push_available(): return JSONResponse({"error":"Push غير مفعّل"},400)
    body = await request.json()
    ep = body.get("endpoint") or ""
    keys = body.get("keys") or {}
    p = keys.get("p256dh") or ""; a = keys.get("auth") or ""
    if not ep or not p or not a: return JSONResponse({"error":"بيانات ناقصة"},400)
    c = db()
    c.execute("INSERT INTO push_subs(username,endpoint,p256dh,auth,ts) VALUES(?,?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET username=excluded.username,p256dh=excluded.p256dh,auth=excluded.auth,ts=excluded.ts", (u["username"],ep[:600],p[:200],a[:200],now()))
    c.commit(); c.close()
    return {"ok":True}

@app.post("/api/push/unsubscribe")
async def api_push_unsub(request: Request):
    u = require_auth(request)
    body = await request.json()
    c = db(); c.execute("DELETE FROM push_subs WHERE endpoint=? AND username=?", (body.get("endpoint") or "", u["username"])); c.commit(); c.close()
    return {"ok":True}

@app.post("/api/push/test")
async def api_push_test(request: Request):
    u = require_auth(request)
    if not push_available(): return JSONResponse({"error":"Push غير مفعّل"},400)
    sent = await push_send_to_user(u["username"],"تجربة","الإشعارات تعمل ✅","","/","test")
    if sent == 0: return JSONResponse({"error":"لا اشتراك فعّال"},404)
    return {"ok":True,"sent":sent}

# ═══ UPLOAD ═══
@app.post("/api/upload")
async def api_upload(request: Request):
    u = require_auth(request)
    if is_maintenance_blocking_write(u):
        return JSONResponse({"error":"الموقع في صيانة"}, 503)
    if not rate_ok("upload:" + u["username"],5): return JSONResponse({"error":"عدد كبير"},429)
    form = await request.form()
    file = form.get("file")
    if not file: return JSONResponse({"error":"لا ملف"},400)
    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE: return JSONResponse({"error":"أكبر من 2MB"},413)
    mime = file.content_type or "image/png"
    if not mime.startswith("image/"): return JSONResponse({"error":"ليس صورة"},400)
    img_id = secrets.token_urlsafe(16)
    c = db()
    c.execute("INSERT INTO images(id,mime,data,size,uploaded_by,created) VALUES(?,?,?,?,?,?)", (img_id,mime,content,len(content),u["username"],now()))
    c.commit(); c.close()
    return {"ok":True,"id":img_id,"url":"/api/image/" + img_id}

@app.get("/api/image/{img_id}")
async def api_get_image(img_id: str):
    if not re.match(r"^[A-Za-z0-9_-]{10,40}$", img_id): raise HTTPException(400)
    c = db()
    row = c.execute("SELECT mime,data FROM images WHERE id=?", (img_id,)).fetchone()
    c.close()
    if not row: raise HTTPException(404)
    return FastResponse(content=row["data"], media_type=row["mime"], headers={"cache-control":"public, max-age=31536000, immutable"})

# ═══ SETTINGS ═══
@app.get("/api/settings")
async def api_settings(request: Request):
    require_auth(request)
    keys = ["site_name","site_sub","hero_title","hero_accent","hero_text",
            "tpl_kick","tpl_yt","tpl_discord","tpl_twitter","tpl_youtube_dc","tpl_tg_verify","tpl_tg_success","tpl_tg_link",
            "btn_kick","btn_yt","btn_tg","btn_discord","btn_tw",
            "lim_kick","lim_yt","lim_tg","lim_tw","guest_mode","guest_blur",
            "site_theme","site_logo","site_c1","site_c2","site_ac",
            "maintenance","maintenance_text","maintenance_title","bot_invite_url","bot_name_custom","groq_model","twitter_bearer_token",
            "registration_enabled","default_lim_kick","default_lim_yt","default_lim_tg","default_lim_tw",
            "bonus_lim_kick","bonus_lim_yt","bonus_lim_tg","bonus_lim_tw",
            "required_channel_id","required_channel_url","required_channel_name","required_channel_msg",
            "signup_welcome_title","signup_welcome_text"]
    out = {k:cfg(k) for k in keys}
    out["groq_configured"] = groq_available()
    out["groq_source"] = "env" if GROQ_ENV_KEY else ("db" if cfg("groq_api_key","") else "none")
    out["twitter_configured"] = bool(await get_twitter_bearer())
    out["twitter_source"] = "env" if TWITTER_ENV_BEARER else ("db" if cfg("twitter_bearer_token","") else "none")
    return out

@app.post("/api/settings")
async def api_save_settings(request: Request):
    require_owner(request)
    body = await request.json()
    allowed = ["site_name","site_sub","hero_title","hero_accent","hero_text",
               "tpl_kick","tpl_yt","tpl_discord","tpl_twitter","tpl_youtube_dc","tpl_tg_verify","tpl_tg_success","tpl_tg_link",
               "btn_kick","btn_yt","btn_tg","btn_discord","btn_tw",
               "lim_kick","lim_yt","lim_tg","lim_tw","guest_mode","guest_blur",
               "site_theme","site_logo","site_c1","site_c2","site_ac",
               "maintenance","maintenance_text","maintenance_title","bot_invite_url","bot_name_custom","groq_model","twitter_bearer_token",
               "registration_enabled","default_lim_kick","default_lim_yt","default_lim_tg","default_lim_tw",
               "bonus_lim_kick","bonus_lim_yt","bonus_lim_tg","bonus_lim_tw",
               "required_channel_id","required_channel_url","required_channel_name","required_channel_msg",
               "signup_welcome_title","signup_welcome_text"]
    for k in allowed:
        if k in body: set_cfg(k, str(body[k])[:2000])
    return {"ok":True}

@app.post("/api/admin/site-logo")
async def api_site_logo(request: Request):
    require_owner(request)
    form = await request.form()
    file = form.get("file")
    if not file: return JSONResponse({"error":"لا ملف"},400)
    content = await file.read()
    if len(content) > 512000: return JSONResponse({"error":"أكبر من 500KB"},413)
    mime = file.content_type or "image/png"
    if not mime.startswith("image/"): return JSONResponse({"error":"ليس صورة"},400)
    img_id = secrets.token_urlsafe(16)
    c = db()
    c.execute("INSERT INTO images(id,mime,data,size,uploaded_by,created) VALUES(?,?,?,?,?,?)", (img_id,mime,content,len(content),"site_logo",now()))
    c.commit(); c.close()
    url = "/api/image/" + img_id
    set_cfg("site_logo", url)
    return {"ok":True,"url":url}

@app.delete("/api/admin/site-logo")
async def api_site_logo_del(request: Request):
    require_owner(request)
    set_cfg("site_logo","")
    return {"ok":True}

@app.post("/api/admin/maintenance")
async def api_maint(request: Request):
    require_owner(request)
    body = await request.json()
    enabled = 1 if body.get("enabled") else 0
    title = str(body.get("title") or "")[:200]
    text = str(body.get("text") or "")[:500]
    set_cfg("maintenance", str(enabled))
    if title: set_cfg("maintenance_title", title)
    if text: set_cfg("maintenance_text", text)
    return {"ok":True,"maintenance":enabled==1}

# ═══ GROQ ═══
@app.get("/api/ai/status")
async def api_ai_status(request: Request):
    require_auth(request)
    return {"available":groq_available(),"model":cfg("groq_model","llama-3.3-70b-versatile"),"source":"env" if GROQ_ENV_KEY else ("db" if cfg("groq_api_key","") else "none")}

@app.post("/api/ai/rewrite")
async def api_ai_rewrite(request: Request):
    u = require_auth(request)
    if not rate_ok("ai:" + u["username"],10): return JSONResponse({"error":"عدد كبير"},429)
    if not groq_available(): return JSONResponse({"error":"Groq غير مفعّل"},400)
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text: return JSONResponse({"error":"لا نص"},400)
    prompt = str(body.get("prompt") or "")[:2000]
    out = await groq_rewrite(text[:4000], prompt)
    if not out: return JSONResponse({"error":"فشل الاتصال"},500)
    return {"ok":True,"text":out}

@app.post("/api/admin/groq")
async def api_admin_groq(request: Request):
    require_owner(request)
    body = await request.json()
    if "api_key" in body:
        key = str(body["api_key"]).strip()[:200]
        if key and not key.startswith("gsk_"): return JSONResponse({"error":"يبدأ بـ gsk_"},400)
        set_cfg("groq_api_key", key)
    if "model" in body: set_cfg("groq_model", str(body["model"]).strip()[:100] or "llama-3.3-70b-versatile")
    if body.get("test"):
        out = await groq_rewrite("اختبار الاتصال", "أعد التحية فقط", None)
        return {"ok":True,"test":out or "فشل الاختبار"}
    return {"ok":True,"available":groq_available()}

@app.post("/api/admin/twitter")
async def api_admin_twitter(request: Request):
    require_owner(request)
    body = await request.json()
    if "bearer_token" in body:
        token = str(body["bearer_token"]).strip()[:500]
        set_cfg("twitter_bearer_token", token)
    return {"ok":True, "configured": bool(await get_twitter_bearer())}

# ═══ ADMIN DEFAULTS ═══
@app.get("/api/admin/default-channels")
async def api_admin_defaults(request: Request):
    require_owner(request)
    kind = request.query_params.get("kind")
    c = db()
    if kind in ("kick","yt","tg","twitter"): rows = c.execute("SELECT * FROM default_channels WHERE kind=? ORDER BY id DESC", (kind,)).fetchall()
    else: rows = c.execute("SELECT * FROM default_channels ORDER BY kind, id DESC").fetchall()
    c.close()
    return {"rows":[dict(r) for r in rows]}

@app.post("/api/admin/default-channels")
async def api_admin_add_default(request: Request):
    require_owner(request)
    body = await request.json()
    kind = body.get("kind")
    if kind not in ("kick","yt","tg","twitter"): return JSONResponse({"error":"نوع غير صالح"},400)
    raw = (body.get("identifier") or "").strip()
    if not raw: return JSONResponse({"error":"المعرّف مطلوب"},400)
    if kind == "kick":
        ident = re.sub(r"[^a-z0-9_-]","",raw.lower().replace("@",""))
        name = body.get("name") or ident; avatar = ""
        info = await kick_fetch(ident)
        if info: name = info["name"]; avatar = info["avatar"]
    elif kind == "yt":
        info = await yt_resolve(raw)
        if not info: return JSONResponse({"error":"تعذّر التعرف"},400)
        ident = info["channel_id"]; name = info["name"] or ident; avatar = info.get("avatar") or ""
    elif kind == "twitter":
        bearer = await get_twitter_bearer()
        ident = raw.replace("@","")
        info = await twitter_resolve(ident, bearer)
        if not info: return JSONResponse({"error":"تعذّر التعرف على حساب تويتر"},400)
        name = body.get("name") or info.get("name") or ident
        avatar = ""
    else:
        ident = norm_chat(raw)
        if not ident: return JSONResponse({"error":"معرّف غير صالح"},400)
        info = await tg_get_chat_info(ident)
        name = body.get("name") or (info or {}).get("name") or ident
        avatar = (info or {}).get("avatar") or ""
        if info and info.get("chat_id"): ident = info["chat_id"]
    c = db()
    if c.execute("SELECT 1 FROM default_channels WHERE kind=? AND identifier=?", (kind,ident)).fetchone():
        c.close(); return JSONResponse({"error":"موجودة مسبقاً"},409)
    c.execute("INSERT INTO default_channels(kind,identifier,name,avatar,enabled,created) VALUES(?,?,?,?,1,?)", (kind,ident,name,avatar,now()))
    c.commit(); c.close()
    return {"ok":True}

@app.post("/api/admin/default-channels/bulk")
async def api_admin_bulk_defaults(request: Request):
    require_owner(request)
    body = await request.json()
    kind = body.get("kind")
    if kind not in ("kick","yt","tg","twitter"): return JSONResponse({"error":"نوع غير صالح"},400)
    text = (body.get("text") or "").strip()
    if not text: return JSONResponse({"error":"لا نص"},400)
    lines = [l.strip() for l in text.split("\n") if l.strip()][:100]
    added, failed, errors = 0, 0, []
    
    bearer = await get_twitter_bearer() if kind == "twitter" else ""
    
    for line in lines:
        try:
            parts = [p.strip() for p in line.split("|")]
            raw = parts[0]; cname = parts[1] if len(parts)>1 else ""
            if kind == "kick":
                ident = re.sub(r"[^a-z0-9_-]","",raw.lower().replace("@",""))
                if not ident: failed += 1; errors.append(raw + ": غير صالح"); continue
                name = cname or ident; avatar = ""
                info = await kick_fetch(ident)
                if info: name = cname or info["name"]; avatar = info["avatar"]
            elif kind == "yt":
                info = await yt_resolve(raw)
                if not info: failed += 1; errors.append(raw + ": تعذّر"); continue
                ident = info["channel_id"]; name = cname or info["name"] or ident; avatar = info.get("avatar") or ""
            elif kind == "twitter":
                ident = raw.replace("@","")
                info = await twitter_resolve(ident, bearer)
                if not info: failed += 1; errors.append(raw + ": تعذّر"); continue
                name = cname or info.get("name") or ident; avatar = ""
            else:
                ident = norm_chat(raw)
                if not ident: failed += 1; errors.append(raw + ": غير صالح"); continue
                info = await tg_get_chat_info(ident)
                name = cname or (info or {}).get("name") or ident
                avatar = (info or {}).get("avatar") or ""
                if info and info.get("chat_id"): ident = info["chat_id"]
            c = db()
            if c.execute("SELECT 1 FROM default_channels WHERE kind=? AND identifier=?", (kind,ident)).fetchone():
                c.close(); failed += 1; errors.append(name + ": موجودة"); continue
            c.execute("INSERT INTO default_channels(kind,identifier,name,avatar,enabled,created) VALUES(?,?,?,?,1,?)", (kind,ident,name,avatar,now()))
            c.commit(); c.close()
            added += 1
        except Exception as e:
            failed += 1; errors.append(line[:30] + ": " + str(e)[:40])
    return {"ok":True,"added":added,"failed":failed,"errors":errors}

@app.delete("/api/admin/default-channels/{cid}")
async def api_admin_del_default(cid: int, request: Request):
    require_owner(request)
    c = db(); c.execute("DELETE FROM default_channels WHERE id=?", (cid,)); c.commit(); c.close()
    return {"ok":True}

@app.patch("/api/admin/default-channels/{cid}")
async def api_admin_patch_default(cid: int, request: Request):
    require_owner(request)
    body = await request.json()
    c = db()
    sets, vals = [], []
    if "enabled" in body: sets.append("enabled=?"); vals.append(1 if body["enabled"] else 0)
    if "name" in body: sets.append("name=?"); vals.append(str(body["name"])[:80])
    if sets:
        vals.append(cid); c.execute("UPDATE default_channels SET " + ", ".join(sets) + " WHERE id=?", vals); c.commit()
    c.close()
    return {"ok":True}

# ═══ ADMIN USERS ═══
@app.get("/api/admin/users")
async def api_admin_users(request: Request):
    require_owner(request)
    c = db()
    rows = c.execute("SELECT id,username,display,avatar,role,active,banned,lim_kick,lim_yt,lim_tg,lim_tw,can_discord,created,last_login,linked_tg_id,linked_tg_username,linked_tg_name,is_member,member_checked FROM users ORDER BY id").fetchall()
    c.close()
    return {"rows":[dict(r) for r in rows]}

@app.get("/api/admin/users/{uid}/details")
async def api_admin_user_details(uid: int, request: Request):
    require_owner(request)
    c = db()
    user = c.execute("SELECT id,username,display,avatar,role,active,banned,lim_kick,lim_yt,lim_tg,lim_tw,can_discord,created,last_login,linked_tg_id,linked_tg_username,linked_tg_name,is_member,member_checked FROM users WHERE id=?", (uid,)).fetchone()
    if not user: c.close(); raise HTTPException(404)
    un = user["username"]
    kick = c.execute("SELECT id,slug,name,avatar,live,viewers,title,enabled,created FROM kick_channels WHERE added_by=? ORDER BY id DESC", (un,)).fetchall()
    yt = c.execute("SELECT id,channel_id,name,avatar,enabled,created FROM yt_channels WHERE added_by=? ORDER BY id DESC", (un,)).fetchall()
    tw = c.execute("SELECT id,username,name,enabled,created FROM tw_channels WHERE added_by=? ORDER BY id DESC", (un,)).fetchall()
    tg = c.execute("SELECT id,chat_id,username,name,avatar,verified,enabled,created FROM tg_channels WHERE added_by=? ORDER BY id DESC", (un,)).fetchall()
    feeds = c.execute("SELECT id,channel_id,channel_name,enabled,created FROM discord_feeds WHERE added_by=? ORDER BY id DESC", (un,)).fetchall()
    subs = c.execute("SELECT fs.id, fs.feed_id, fs.tg_channel_id, df.channel_name, t.name as tg_name FROM feed_subs fs LEFT JOIN discord_feeds df ON df.id=fs.feed_id LEFT JOIN tg_channels t ON t.id=fs.tg_channel_id WHERE fs.username=?", (un,)).fetchall()
    notifs_count = c.execute("SELECT COUNT(*) n FROM notifs WHERE username=?", (un,)).fetchone()["n"]
    c.close()
    return {"user":dict(user),"kick":[dict(r) for r in kick],"yt":[dict(r) for r in yt],"tw":[dict(r) for r in tw],"tg":[dict(r) for r in tg],"discord_feeds":[dict(r) for r in feeds],"feed_subs":[dict(r) for r in subs],"notifs_count":notifs_count}

@app.post("/api/admin/users")
async def api_admin_add_user(request: Request):
    require_owner(request)
    body = await request.json()
    un = (body.get("username") or "").strip()
    pw = str(body.get("password") or "")
    if not re.match(r"^[A-Za-z0-9_.-]{3,30}$", un): return JSONResponse({"error":"اسم غير صالح"},400)
    if len(pw) < 6: return JSONResponse({"error":"كلمة المرور 6+"},400)
    if un.lower() == ADMIN_USERNAME.lower(): return JSONResponse({"error":"محجوز"},400)
    c = db()
    if c.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)", (un,)).fetchone():
        c.close(); return JSONResponse({"error":"مستخدم"},409)
    salt = secrets.token_hex(16)
    opt = lambda v: (None if v in ("",None) else max(0, min(9999, int(v))))
    c.execute("INSERT INTO users(username,display,pass_hash,salt,role,active,banned,lim_kick,lim_yt,lim_tg,lim_tw,can_discord,created) VALUES(?,?,?,?,'user',1,0,?,?,?,?,?,?)",
        (un, (body.get("display") or un)[:60], hash_pw(pw,salt), salt, opt(body.get("lim_kick")), opt(body.get("lim_yt")), opt(body.get("lim_tg")), opt(body.get("lim_tw")), 1 if body.get("can_discord") else 0, now()))
    c.commit(); c.close()
    return {"ok":True}

@app.patch("/api/admin/users/{uid}")
async def api_admin_patch_user(uid: int, request: Request):
    u = require_owner(request)
    body = await request.json()
    c = db()
    row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row: c.close(); raise HTTPException(404)
    is_self = row["username"] == u["username"]
    is_admin_acc = row["username"].lower() == ADMIN_USERNAME.lower()
    sets, vals = [], []
    opt = lambda v: (None if v in ("",None) else max(0, min(9999, int(v))))
    if "banned" in body and not is_self and not is_admin_acc: sets.append("banned=?"); vals.append(1 if body["banned"] else 0)
    if "active" in body and not is_self and not is_admin_acc: sets.append("active=?"); vals.append(1 if body["active"] else 0)
    if "role" in body and not is_admin_acc: sets.append("role=?"); vals.append("owner" if body["role"]=="owner" else "user")
    if "display" in body: sets.append("display=?"); vals.append(str(body["display"])[:60] or row["username"])
    for k in ("lim_kick","lim_yt","lim_tg","lim_tw"):
        if k in body: sets.append(k + "=?"); vals.append(opt(body[k]))
    if "can_discord" in body: sets.append("can_discord=?"); vals.append(1 if body["can_discord"] else 0)
    pw_ch = False
    if body.get("password"):
        if len(str(body["password"])) < 6: c.close(); return JSONResponse({"error":"كلمة المرور 6+"},400)
        salt = secrets.token_hex(16)
        sets.append("pass_hash=?"); vals.append(hash_pw(str(body["password"]), salt))
        sets.append("salt=?"); vals.append(salt)
        pw_ch = True
    if sets:
        vals.append(uid)
        c.execute("UPDATE users SET " + ", ".join(sets) + " WHERE id=?", vals)
        c.commit()
    c.close()
    if pw_ch or "banned" in body or "active" in body: kill_sessions(row["username"])
    return {"ok":True}

@app.delete("/api/admin/users/{uid}")
async def api_admin_del_user(uid: int, request: Request):
    u = require_owner(request)
    c = db()
    row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row: c.close(); raise HTTPException(404)
    if row["username"] == u["username"] or row["username"].lower() == ADMIN_USERNAME.lower():
        c.close(); return JSONResponse({"error":"لا يمكن حذف هذا الحساب"},400)
    un = row["username"]
    for t in ("kick_channels","yt_channels","tw_channels","tg_channels","recent_videos"):
        c.execute("DELETE FROM " + t + " WHERE added_by=?", (un,))
    c.execute("DELETE FROM feed_subs WHERE username=?", (un,))
    for t in ("notifs","sessions","suggestions","push_subs","tg_link_codes"):
        c.execute("DELETE FROM " + t + " WHERE site_username=?" if t == "tg_link_codes" else "DELETE FROM " + t + " WHERE username=?", (un,))
    c.execute("DELETE FROM tg_link_codes WHERE site_username=?", (un,))
    c.execute("DELETE FROM users WHERE id=?", (uid,))
    c.commit(); c.close()
    return {"ok":True}

@app.get("/api/admin/stats")
async def api_admin_stats(request: Request):
    require_owner(request)
    c = db()
    s = {"users_total":c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],
         "users_active":c.execute("SELECT COUNT(*) n FROM users WHERE active=1 AND banned=0").fetchone()["n"],
         "users_banned":c.execute("SELECT COUNT(*) n FROM users WHERE banned=1").fetchone()["n"],
         "users_linked_tg":c.execute("SELECT COUNT(*) n FROM users WHERE linked_tg_id != ''").fetchone()["n"],
         "users_members":c.execute("SELECT COUNT(*) n FROM users WHERE is_member=1").fetchone()["n"],
         "kick_total":c.execute("SELECT COUNT(*) n FROM kick_channels").fetchone()["n"],
         "kick_live":c.execute("SELECT COUNT(*) n FROM kick_channels WHERE live=1").fetchone()["n"],
         "yt_total":c.execute("SELECT COUNT(*) n FROM yt_channels").fetchone()["n"],
         "tw_total":c.execute("SELECT COUNT(*) n FROM tw_channels").fetchone()["n"],
         "tg_total":c.execute("SELECT COUNT(*) n FROM tg_channels").fetchone()["n"],
         "tg_verified":c.execute("SELECT COUNT(*) n FROM tg_channels WHERE verified=1").fetchone()["n"],
         "feeds_total":c.execute("SELECT COUNT(*) n FROM discord_feeds").fetchone()["n"],
         "feed_subs_total":c.execute("SELECT COUNT(*) n FROM feed_subs WHERE enabled=1").fetchone()["n"],
         "suggestions_unread":c.execute("SELECT COUNT(*) n FROM suggestions WHERE is_read=0").fetchone()["n"],
         "push_subs":c.execute("SELECT COUNT(*) n FROM push_subs").fetchone()["n"],
         "defaults_total":c.execute("SELECT COUNT(*) n FROM default_channels").fetchone()["n"],
         "tg_known":c.execute("SELECT COUNT(*) n FROM tg_known_channels").fetchone()["n"],
         "news_total":c.execute("SELECT COUNT(*) n FROM news WHERE enabled=1").fetchone()["n"]}
    c.close()
    s["discord_ready"] = bool(discord_client and discord_client.is_ready())
    s["discord_channels"] = len(_CH_CACHE)
    s["auto_discovery"] = not bool(WATCH_CHANNELS)
    s["has_telegram"] = bool(TELEGRAM_TOKEN)
    s["has_discord"] = bool(DISCORD_TOKEN)
    s["has_push"] = push_available()
    s["has_groq"] = groq_available()
    s["has_twitter"] = bool(await get_twitter_bearer())
    s["groq_source"] = "env" if GROQ_ENV_KEY else ("db" if cfg("groq_api_key","") else "none")
    s["maintenance"] = cfg("maintenance","0") == "1"
    s["self_bot_mode"] = _SELF_BOT
    s["bot_info"] = _BOT_INFO
    s["public_url"] = PUBLIC_URL
    s["webhook_set"] = bool(PUBLIC_URL and TELEGRAM_TOKEN)
    return s

@app.get("/api/admin/security")
async def api_admin_sec(request: Request):
    require_owner(request)
    c = db()
    rows = c.execute("SELECT ts,username,action,detail,ip FROM security_log ORDER BY id DESC LIMIT 200").fetchall()
    c.close()
    return {"rows":[dict(r) for r in rows]}

# ═══ WEBHOOK ═══
@app.post("/api/telegram/webhook")
async def tg_webhook(request: Request):
    try:
        upd = await request.json()
        asyncio.create_task(handle_tg_update(upd))
    except Exception as e: print("[TG webhook] " + str(e))
    return {"ok": True}

@app.get("/api/telegram/webhook-info")
async def tg_webhook_info(request: Request):
    require_owner(request)
    j = await tg_api("getWebhookInfo", {})
    return j

@app.post("/api/telegram/setup-webhook")
async def tg_setup_webhook_manual(request: Request):
    require_owner(request)
    if not PUBLIC_URL: return JSONResponse({"error": "PUBLIC_URL غير مضبوط"}, 400)
    url = PUBLIC_URL + "/api/telegram/webhook"
    j = await tg_api("setWebhook", {"url": url, "allowed_updates": ["message", "callback_query", "my_chat_member", "channel_post"]})
    return j

@app.get("/api/telegram/known-channels")
async def tg_known_channels(request: Request):
    require_owner(request)
    c = db()
    rows = c.execute("SELECT * FROM tg_known_channels ORDER BY last_seen DESC LIMIT 100").fetchall()
    c.close()
    return {"rows": [dict(r) for r in rows]}

# ═══ ROOT + MANIFEST + SW ═══
@app.get("/", response_class=HTMLResponse)
async def index():
    try:
        with open("index.html","r",encoding="utf-8") as f: return f.read()
    except FileNotFoundError: return HTMLResponse("<h1>index.html غير موجود</h1>", status_code=500)

@app.get("/manifest.json")
async def manifest():
    theme = get_site_theme()
    logo = cfg("site_logo","")
    icons = [{"src":logo or "/favicon.ico","sizes":"192x192 512x512","type":"image/png","purpose":"any"}]
    return JSONResponse({"name":cfg("site_name",SITE_NAME),"short_name":cfg("site_name",SITE_NAME)[:12],"start_url":"/","display":"standalone","background_color":theme["c1"],"theme_color":theme["c1"],"dir":"rtl","lang":"ar","icons":icons})

@app.get("/sw.js")
async def sw():
    js = "self.addEventListener('install',e=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));self.addEventListener('push',e=>{let d={};try{d=e.data.json();}catch(x){d={title:'إشعار',body:e.data?e.data.text():''};}const o={body:d.body||'',icon:d.icon||'/favicon.ico',image:d.image||undefined,tag:d.tag||undefined,renotify:!!d.tag,dir:'rtl',lang:'ar',data:{url:d.url||'/'}};e.waitUntil(Promise.all([self.registration.showNotification(d.title||'إشعار',o),self.clients.matchAll({type:'window'}).then(cs=>cs.forEach(c=>c.postMessage({t:'push'})))]));});self.addEventListener('notificationclick',e=>{e.notification.close();const url=(e.notification.data&&e.notification.data.url)||'/';e.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(cs=>{const s=cs.find(c=>new URL(c.url).origin===location.origin);if(url.startsWith('/')&&s)return s.focus();return self.clients.openWindow(url);}));});"
    return FastResponse(content=js, media_type="application/javascript", headers={"cache-control":"no-cache"})

@app.get("/favicon.ico")
async def favicon():
    logo = cfg("site_logo","")
    if logo and logo.startswith("/api/image/"):
        img_id = logo.replace("/api/image/","")
        c = db(); row = c.execute("SELECT mime,data FROM images WHERE id=?", (img_id,)).fetchone(); c.close()
        if row: return FastResponse(content=row["data"], media_type=row["mime"])
    return FastResponse(content=b"", status_code=204)

@app.get("/health")
async def health():
    return {"ok":True,"discord_ready":bool(discord_client and discord_client.is_ready()),"discord_channels":len(_CH_CACHE),"auto_discovery":not bool(WATCH_CHANNELS),"push_enabled":push_available(),"telegram_enabled":bool(TELEGRAM_TOKEN),"groq_enabled":groq_available(),"twitter_enabled":bool(await get_twitter_bearer()),"maintenance":cfg("maintenance","0")=="1","self_bot_mode":_SELF_BOT,"public_url":PUBLIC_URL}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
