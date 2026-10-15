"""
Respect Live — مراقبة قنوات البث + بوت ديسكورد
FastAPI + Discord.py + SQLite
"""
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
ADMIN_USERNAME  = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD  = os.getenv("ADMIN_PASSWORD", "changeme")
SESSION_SECRET  = os.getenv("SESSION_SECRET", secrets.token_hex(32))
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN", "")
DISCORD_TOKEN   = os.getenv("DISCORD_BOT_TOKEN", "")
WATCH_CHANNELS  = [c.strip() for c in os.getenv("DISCORD_WATCH_CHANNELS", "").split(",") if c.strip()]
ALLOWED_GUILDS  = [g.strip() for g in os.getenv("DISCORD_ALLOWED_GUILDS", "").split(",") if g.strip()]
VAPID_PUBLIC    = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE   = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_EMAIL     = os.getenv("VAPID_EMAIL", "mailto:admin@example.com")
SITE_NAME       = os.getenv("SITE_NAME", "Respect Live")
DB_PATH         = os.getenv("DB_PATH", "respect.db")
SESSION_TTL     = 7 * 24 * 3600
UA              = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

MAX_PER_MIN_TG  = 30
MAX_PER_MIN_CH  = 10
BATCH_KICK      = 30
BATCH_YT        = 30
MAX_IMAGE_SIZE  = 2 * 1024 * 1024


# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════
def db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    display TEXT DEFAULT '',
    pass_hash TEXT DEFAULT '',
    salt TEXT DEFAULT '',
    role TEXT DEFAULT 'user',
    active INTEGER DEFAULT 1,
    banned INTEGER DEFAULT 0,
    lim_kick INTEGER, lim_yt INTEGER, lim_tg INTEGER,
    created INTEGER, last_login INTEGER
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    created INTEGER,
    expires INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sessions_exp ON sessions(expires);
CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS default_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL, identifier TEXT NOT NULL,
    name TEXT DEFAULT '', avatar TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1, created INTEGER,
    UNIQUE(kind, identifier)
);
CREATE INDEX IF NOT EXISTS idx_def_kind ON default_channels(kind, enabled);
CREATE TABLE IF NOT EXISTS kick_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL,
    name TEXT DEFAULT '', avatar TEXT DEFAULT '', banner TEXT DEFAULT '',
    msg TEXT DEFAULT '', enabled INTEGER DEFAULT 1, live INTEGER DEFAULT 0,
    title TEXT DEFAULT '', viewers INTEGER DEFAULT 0, thumb TEXT DEFAULT '',
    last_check INTEGER DEFAULT 0, added_by TEXT NOT NULL, created INTEGER,
    UNIQUE(slug, added_by)
);
CREATE INDEX IF NOT EXISTS idx_kick_by ON kick_channels(added_by);
CREATE INDEX IF NOT EXISTS idx_kick_check ON kick_channels(enabled, last_check);
CREATE TABLE IF NOT EXISTS yt_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL, handle TEXT DEFAULT '', name TEXT DEFAULT '',
    avatar TEXT DEFAULT '', msg TEXT DEFAULT '', enabled INTEGER DEFAULT 1,
    last_video TEXT DEFAULT '', last_check INTEGER DEFAULT 0,
    added_by TEXT NOT NULL, created INTEGER, UNIQUE(channel_id, added_by)
);
CREATE INDEX IF NOT EXISTS idx_yt_by ON yt_channels(added_by);
CREATE INDEX IF NOT EXISTS idx_yt_check ON yt_channels(enabled, last_check);
CREATE TABLE IF NOT EXISTS tg_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL, username TEXT DEFAULT '', name TEXT DEFAULT '',
    avatar TEXT DEFAULT '', enabled INTEGER DEFAULT 1,
    added_by TEXT NOT NULL, created INTEGER, UNIQUE(chat_id, added_by)
);
CREATE INDEX IF NOT EXISTS idx_tg_by ON tg_channels(added_by);
CREATE TABLE IF NOT EXISTS discord_feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL, channel_name TEXT DEFAULT '',
    template TEXT DEFAULT '', source_type TEXT DEFAULT 'generic',
    enabled INTEGER DEFAULT 1, added_by TEXT NOT NULL, created INTEGER,
    UNIQUE(channel_id, added_by)
);
CREATE INDEX IF NOT EXISTS idx_df_by ON discord_feeds(added_by);
CREATE INDEX IF NOT EXISTS idx_df_ch ON discord_feeds(channel_id, enabled);
CREATE TABLE IF NOT EXISTS discord_seen (message_id TEXT PRIMARY KEY, ts INTEGER);
CREATE INDEX IF NOT EXISTS idx_ds_ts ON discord_seen(ts);
CREATE TABLE IF NOT EXISTS notifs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL, title TEXT DEFAULT '', body TEXT DEFAULT '',
    image TEXT DEFAULT '', btn_text TEXT DEFAULT '', btn_url TEXT DEFAULT '',
    kind TEXT DEFAULT 'admin', ts INTEGER, is_read INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_notifs ON notifs(username, ts);
CREATE TABLE IF NOT EXISTS recent_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL, ch_name TEXT DEFAULT '', title TEXT DEFAULT '',
    thumb TEXT DEFAULT '', url TEXT DEFAULT '', ts INTEGER,
    added_by TEXT NOT NULL, UNIQUE(video_id, added_by)
);
CREATE INDEX IF NOT EXISTS idx_rv_by ON recent_videos(added_by, ts);
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL, text TEXT NOT NULL,
    is_read INTEGER DEFAULT 0, ts INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sug_ts ON suggestions(ts DESC);
CREATE TABLE IF NOT EXISTS push_subs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL, endpoint TEXT UNIQUE NOT NULL,
    p256dh TEXT NOT NULL, auth TEXT NOT NULL, ts INTEGER
);
CREATE INDEX IF NOT EXISTS idx_push_user ON push_subs(username);
CREATE TABLE IF NOT EXISTS images (
    id TEXT PRIMARY KEY, mime TEXT NOT NULL, data BLOB NOT NULL,
    size INTEGER NOT NULL, uploaded_by TEXT, created INTEGER
);
CREATE TABLE IF NOT EXISTS rate_limits (k TEXT PRIMARY KEY, cnt INTEGER, ts INTEGER);
CREATE TABLE IF NOT EXISTS security_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER, username TEXT, action TEXT, detail TEXT, ip TEXT
);
CREATE INDEX IF NOT EXISTS idx_sec_ts ON security_log(ts);
"""


def init_db():
    c = db()
    c.executescript(SCHEMA)
    if not c.execute("SELECT 1 FROM users WHERE username=?", (ADMIN_USERNAME,)).fetchone():
        salt = secrets.token_hex(16)
        c.execute(
            "INSERT INTO users(username,display,pass_hash,salt,role,active,banned,created) "
            "VALUES(?,?,?,?,'owner',1,0,?)",
            (ADMIN_USERNAME, ADMIN_USERNAME, hash_pw(ADMIN_PASSWORD, salt), salt, now()),
        )
    defaults = {
        "site_name": SITE_NAME, "site_sub": "STREAM MONITOR · OFFICIAL",
        "hero_title": "مراقبة", "hero_accent": "القنوات.",
        "hero_text": "تابع قنواتك على كيك ويوتيوب وتيليجرام في مكان واحد. إشعارات فورية عند أي بث أو فيديو جديد.",
        "tpl_kick": "<b>{name}</b>\nبدأ بثاً مباشراً الآن\n\n<b>{title}</b>",
        "tpl_yt":   "<b>{name}</b>\nنشر فيديو جديداً\n\n<b>{title}</b>",
        "tpl_discord": "<b>{author}</b>\n{content}",
        "tpl_twitter": "<b>{author}</b>\n{content}",
        "tpl_youtube_dc": "<b>{author}</b>\n{content}",
        "btn_kick": "شاهد البث", "btn_yt": "شاهد الفيديو",
        "lim_kick": "10", "lim_yt": "5", "lim_tg": "3",
        "guest_mode": "1", "guest_blur": "14",
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings(k,v) VALUES(?,?)", (k, v))
    c.commit()
    c.close()


def now() -> int:
    return int(time.time())


def cfg(k: str, d: str = "") -> str:
    c = db()
    r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    c.close()
    return r["v"] if r else d


def set_cfg(k: str, v: str):
    c = db()
    c.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
              (k, str(v)))
    c.commit()
    c.close()


def hash_pw(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 100000).hex()


def log_sec(username: str, action: str, detail: str = "", ip: str = ""):
    try:
        c = db()
        c.execute("INSERT INTO security_log(ts,username,action,detail,ip) VALUES(?,?,?,?,?)",
                  (now(), username or "anon", action[:60], detail[:300], ip[:60]))
        c.execute("DELETE FROM security_log WHERE id IN "
                  "(SELECT id FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY id DESC) rn "
                  "FROM security_log) WHERE rn > 5000)")
        c.commit()
        c.close()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# RATE LIMITING
# ═══════════════════════════════════════════════════════════
_rate_map: dict = {}


def rate_ok(key: str, max_per_min: int = MAX_PER_MIN_TG) -> bool:
    t = time.time()
    lst = _rate_map.setdefault(key, [])
    lst[:] = [x for x in lst if t - x < 60]
    if len(lst) >= max_per_min:
        return False
    lst.append(t)
    return True


# ═══════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════
def auth(request: Request) -> Optional[dict]:
    tok = request.cookies.get("rl_sid")
    if not tok or len(tok) > 200:
        return None
    c = db()
    row = c.execute(
        "SELECT s.username, u.* FROM sessions s "
        "JOIN users u ON u.username=s.username "
        "WHERE s.token=? AND s.expires>? AND u.active=1 AND u.banned=0",
        (tok, now()),
    ).fetchone()
    c.close()
    return dict(row) if row else None


def new_session(username: str) -> str:
    tok = secrets.token_urlsafe(32)
    c = db()
    c.execute("INSERT INTO sessions(token,username,created,expires) VALUES(?,?,?,?)",
              (tok, username, now(), now() + SESSION_TTL))
    c.commit()
    c.close()
    return tok


def kill_sessions(username: str):
    c = db()
    c.execute("DELETE FROM sessions WHERE username=?", (username,))
    c.commit()
    c.close()


def require_auth(request: Request):
    u = auth(request)
    if not u:
        raise HTTPException(401, "غير مسجل")
    return u


def require_owner(request: Request):
    u = require_auth(request)
    if u["role"] != "owner":
        raise HTTPException(403, "غير مصرح")
    return u


def check_limit(username: str, kind: str, role: str) -> bool:
    if role == "owner":
        return True
    lim_key = {"kick": "lim_kick", "yt": "lim_yt", "tg": "lim_tg"}[kind]
    table = {"kick": "kick_channels", "yt": "yt_channels", "tg": "tg_channels"}[kind]
    limit = int(cfg(lim_key, {"kick": "10", "yt": "5", "tg": "3"}[kind]))
    c = db()
    n = c.execute(f"SELECT COUNT(*) n FROM {table} WHERE added_by=?", (username,)).fetchone()["n"]
    c.close()
    return n < limit


# ═══════════════════════════════════════════════════════════
# TELEGRAM
# ═══════════════════════════════════════════════════════════
async def tg_send(chat_id: str, text: str, image: str = "",
                  btn: str = "", url: str = "") -> bool:
    if not TELEGRAM_TOKEN:
        return False
    markup = {"inline_keyboard": [[{"text": btn[:60], "url": url}]]} if (btn and url) else None
    base = {"chat_id": str(chat_id), "parse_mode": "HTML"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            if image:
                r = await c.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                    json={**base, "photo": image, "caption": (text or ".")[:1024],
                          "reply_markup": markup},
                )
                if r.status_code == 200:
                    return True
            r = await c.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={**base, "text": (text or ".")[:4096], "reply_markup": markup},
            )
            return r.status_code == 200
    except Exception as e:
        print(f"[TG ERROR] {e}")
        return False


def norm_chat(s: str) -> Optional[str]:
    s = (s or "").strip()
    m = re.match(r"(?:https?://)?t\.me/([A-Za-z][\w]{3,})", s)
    if m: return "@" + m.group(1)
    if re.match(r"^-?\d+$", s): return s
    if re.match(r"^@[A-Za-z][\w]{3,}$", s): return s
    if re.match(r"^[A-Za-z][\w]{3,}$", s): return "@" + s
    return None


# ═══════════════════════════════════════════════════════════
# KICK
# ═══════════════════════════════════════════════════════════
async def kick_fetch(slug: str) -> Optional[dict]:
    h = {"User-Agent": UA, "Accept": "application/json", "Referer": "https://kick.com/"}
    async with httpx.AsyncClient(timeout=15, headers=h) as c:
        for v in ("v2", "v1"):
            try:
                r = await c.get(f"https://kick.com/api/{v}/channels/{slug}")
                if r.status_code == 404: continue
                if r.status_code != 200: continue
                j = r.json()
                ls = j.get("livestream") or {}
                u = j.get("user") or {}
                bn = j.get("banner_image")
                if isinstance(bn, dict): bn = bn.get("url") or ""
                return {
                    "name": u.get("username") or slug,
                    "avatar": u.get("profile_pic") or "",
                    "banner": bn or "",
                    "live": bool(ls.get("is_live")),
                    "title": ls.get("session_title") or "",
                    "viewers": ls.get("viewer_count") or 0,
                    "thumb": ((ls.get("thumbnail") or {}).get("url")) or "",
                }
            except Exception as e:
                print(f"[KICK] {e}")
    return None


# ═══════════════════════════════════════════════════════════
# YOUTUBE
# ═══════════════════════════════════════════════════════════
async def yt_feed(channel_id: str) -> Optional[list]:
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}) as c:
            r = await c.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
            if r.status_code != 200: return None
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


async def yt_resolve(input_str: str) -> Optional[dict]:
    input_str = (input_str or "").strip()[:300]
    if not input_str: return None
    m = re.search(r"UC[\w-]{22}", input_str)
    if m:
        cid = m.group(0)
        try:
            async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}) as c:
                r = await c.get(f"https://www.youtube.com/channel/{cid}")
                html = r.text
            title = (re.search(r'<meta property="og:title" content="([^"]*)"', html) or [None, cid])[1]
            avatar = (re.search(r'<meta property="og:image" content="([^"]*)"', html) or [None, ""])[1]
            return {"channel_id": cid, "name": title, "avatar": avatar}
        except Exception:
            return {"channel_id": cid, "name": cid, "avatar": ""}
    h = re.search(r"@([\w.\-]+)", input_str)
    if h:
        try:
            async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}) as c:
                r = await c.get(f"https://www.youtube.com/@{h.group(1)}")
                html = r.text
            cid_m = re.search(r'"externalId":"(UC[\w-]{22})"', html) or re.search(r'"channelId":"(UC[\w-]{22})"', html)
            if not cid_m: return None
            cid = cid_m.group(1)
            title = (re.search(r'<meta property="og:title" content="([^"]*)"', html) or [None, cid])[1]
            avatar = (re.search(r'<meta property="og:image" content="([^"]*)"', html) or [None, ""])[1]
            return {"channel_id": cid, "name": title, "avatar": avatar}
        except Exception:
            return None
    return None


# ═══════════════════════════════════════════════════════════
# WEB PUSH (VAPID)
# ═══════════════════════════════════════════════════════════
def push_available() -> bool:
    return bool(VAPID_PUBLIC and VAPID_PRIVATE)


async def push_send_to_user(username: str, title: str, body: str,
                            image: str = "", url: str = "/", tag: str = "") -> int:
    if not push_available(): return 0
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        print("[Push] pywebpush غير مثبت")
        return 0
    c = db()
    subs = c.execute("SELECT * FROM push_subs WHERE username=?", (username,)).fetchall()
    c.close()
    if not subs: return 0
    payload = json.dumps({
        "title": title[:80], "body": body[:200],
        "image": image or "", "url": url or "/", "tag": tag or "rl",
    })
    sent = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload, vapid_private_key=VAPID_PRIVATE,
                vapid_claims={"sub": VAPID_EMAIL}, timeout=10,
            )
            sent += 1
        except WebPushException as e:
            code = getattr(e.response, "status_code", None) if hasattr(e, "response") else None
            if code in (404, 410):
                c = db()
                c.execute("DELETE FROM push_subs WHERE id=?", (sub["id"],))
                c.commit()
                c.close()
        except Exception as e:
            print(f"[Push] {e}")
    return sent


# ═══════════════════════════════════════════════════════════
# DISCORD BOT
# ═══════════════════════════════════════════════════════════
discord_client = discord.Client(intents=discord.Intents(
    guilds=True, guild_messages=True, message_content=True,
))


@discord_client.event
async def on_ready():
    print(f"[Discord] ✅ {discord_client.user} في {len(discord_client.guilds)} سيرفر")
    print(f"[Discord] يراقب {len(WATCH_CHANNELS)} روم")


def classify_message_source(msg: discord.Message) -> str:
    if msg.embeds:
        e = msg.embeds[0]
        url = (e.url or "").lower()
        author_name = ((e.author.name if e.author else "") or "").lower()
        provider = ((e.provider.name if e.provider else "") or "").lower()
        if "twitter.com" in url or "x.com" in url or "twitter" in provider or "twitter" in author_name:
            return "twitter"
        if "youtube.com" in url or "youtu.be" in url or "youtube" in provider:
            return "youtube"
    if "twitter.com" in (msg.content or "").lower() or "x.com" in (msg.content or "").lower():
        return "twitter"
    if "youtube.com" in (msg.content or "").lower() or "youtu.be" in (msg.content or "").lower():
        return "youtube"
    return "generic"


def extract_author_and_content(msg: discord.Message) -> tuple:
    author = msg.author.display_name or msg.author.name or ""
    content = (msg.content or "").strip()[:2000]
    if msg.author.bot and msg.embeds:
        e = msg.embeds[0]
        if e.author and e.author.name: author = e.author.name
        elif e.provider and e.provider.name: author = e.provider.name
        parts = []
        if e.title: parts.append(e.title.strip())
        if e.description: parts.append(e.description.strip())
        if parts: content = "\n".join(parts)[:2000]
    return author, content


def extract_image_and_url(msg: discord.Message) -> tuple:
    image, url = "", ""
    if msg.embeds:
        e = msg.embeds[0]
        if e.image and e.image.url: image = e.image.url
        elif e.thumbnail and e.thumbnail.url: image = e.thumbnail.url
        url = e.url or ""
    if not image and msg.attachments:
        for a in msg.attachments:
            if a.content_type and a.content_type.startswith("image/"):
                image = a.url
                break
    return image, url


@discord_client.event
async def on_message(msg: discord.Message):
    if msg.author.bot and not msg.embeds: return
    if msg.guild is None: return
    if ALLOWED_GUILDS and str(msg.guild.id) not in ALLOWED_GUILDS: return
    ch_id = str(msg.channel.id)
    if ch_id not in WATCH_CHANNELS: return
    c = db()
    if c.execute("SELECT 1 FROM discord_seen WHERE message_id=?", (str(msg.id),)).fetchone():
        c.close()
        return
    c.execute("INSERT INTO discord_seen(message_id,ts) VALUES(?,?)", (str(msg.id), now()))
    c.commit()
    source = classify_message_source(msg)
    author, content = extract_author_and_content(msg)
    image, url = extract_image_and_url(msg)
    if not content and not image:
        c.close()
        return
    feeds = c.execute(
        "SELECT * FROM discord_feeds WHERE channel_id=? AND enabled=1", (ch_id,)
    ).fetchall()
    c.close()
    if not feeds: return
    for feed in feeds:
        owner = feed["added_by"]
        if not rate_ok(f"discord:{owner}", max_per_min=MAX_PER_MIN_TG):
            continue
        if feed["template"]: tpl = feed["template"]
        elif source == "twitter": tpl = cfg("tpl_twitter") or cfg("tpl_discord")
        elif source == "youtube": tpl = cfg("tpl_youtube_dc") or cfg("tpl_discord")
        else: tpl = cfg("tpl_discord")
        text = (tpl.replace("{author}", author).replace("{content}", content)
                .replace("{channel}", getattr(msg.channel, "name", "") or "")
                .replace("{source}", source))
        c2 = db()
        tgs = c2.execute(
            "SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (owner,)
        ).fetchall()
        c2.execute(
            "INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) "
            "VALUES(?,?,?,?,?,?,'discord',?,0)",
            (owner, author or "رسالة ديسكورد", content[:500], image,
             "فتح الرابط" if url else "", url or "", now()),
        )
        c2.commit()
        c2.close()
        asyncio.create_task(push_send_to_user(
            owner, author or "رسالة ديسكورد", content[:200], image, url, "discord"
        ))
        for tg in tgs:
            await tg_send(tg["chat_id"], text, image, "عرض", url)
            

# ═══════════════════════════════════════════════════════════
# BACKGROUND JOBS
# ═══════════════════════════════════════════════════════════
async def job_kick():
    c = db()
    rows = c.execute(
        "SELECT * FROM kick_channels WHERE enabled=1 AND last_check<? "
        "ORDER BY last_check LIMIT ?",
        (now() - 90, BATCH_KICK),
    ).fetchall()
    c.close()
    if not rows: return
    infos = {}
    sem = asyncio.Semaphore(8)
    async def fetch_one(r):
        async with sem:
            infos[r["slug"]] = await kick_fetch(r["slug"])
    await asyncio.gather(*(fetch_one(r) for r in rows), return_exceptions=True)
    updates, live_events = [], []
    t = now()
    for r in rows:
        info = infos.get(r["slug"])
        if not info:
            updates.append((t, r["id"]))
            continue
        updates.append((
            info["name"], info["avatar"], info["banner"],
            1 if info["live"] else 0, info["title"], info["viewers"],
            info["thumb"], t, r["id"]
        ))
        if info["live"] and not r["live"]:
            live_events.append((r, info))
    c = db()
    for u in updates:
        if len(u) == 2:
            c.execute("UPDATE kick_channels SET last_check=? WHERE id=?", u)
        else:
            c.execute(
                "UPDATE kick_channels SET name=?,avatar=?,banner=?,live=?,title=?,"
                "viewers=?,thumb=?,last_check=? WHERE id=?", u
            )
    c.commit()
    c.close()
    async def notify_one(r, info):
        tpl = r["msg"] or cfg("tpl_kick")
        text = (tpl.replace("{name}", info["name"])
                .replace("{title}", info["title"])
                .replace("{url}", f"https://kick.com/{r['slug']}"))
        c2 = db()
        tgs = c2.execute(
            "SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (r["added_by"],)
        ).fetchall()
        c2.execute(
            "INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) "
            "VALUES(?,?,?,?,?,?,'kick',?,0)",
            (r["added_by"], info["name"] + " يبث الآن", info["title"],
             info["banner"] or info["thumb"], cfg("btn_kick"),
             f"https://kick.com/{r['slug']}", t),
        )
        c2.commit()
        c2.close()
        asyncio.create_task(push_send_to_user(
            r["added_by"], info["name"] + " يبث الآن",
            info["title"] or "بث مباشر الآن",
            info["banner"] or info["thumb"],
            f"https://kick.com/{r['slug']}", f"kick:{r['id']}"
        ))
        for tg in tgs:
            await tg_send(tg["chat_id"], text, info["banner"] or info["thumb"],
                          cfg("btn_kick"), f"https://kick.com/{r['slug']}")
    await asyncio.gather(*(notify_one(r, info) for r, info in live_events),
                         return_exceptions=True)


async def job_yt():
    c = db()
    rows = c.execute(
        "SELECT * FROM yt_channels WHERE enabled=1 AND last_check<? "
        "ORDER BY last_check LIMIT ?",
        (now() - 300, BATCH_YT),
    ).fetchall()
    c.close()
    if not rows: return
    feeds = {}
    sem = asyncio.Semaphore(8)
    async def fetch_one(r):
        async with sem:
            feeds[r["channel_id"]] = await yt_feed(r["channel_id"])
    await asyncio.gather(*(fetch_one(r) for r in rows), return_exceptions=True)
    updates, new_videos = [], []
    t = now()
    for r in rows:
        items = feeds.get(r["channel_id"])
        if not items:
            updates.append((t, r["id"]))
            continue
        latest = items[0]["id"]
        if r["last_video"] and latest != r["last_video"]:
            fresh = []
            for it in items:
                if it["id"] == r["last_video"]: break
                fresh.append(it)
            for v in reversed(fresh[:3]):
                new_videos.append((r, v))
        updates.append((latest, t, r["id"]))
    c = db()
    for u in updates:
        if len(u) == 2:
            c.execute("UPDATE yt_channels SET last_check=? WHERE id=?", u)
        else:
            c.execute("UPDATE yt_channels SET last_video=?,last_check=? WHERE id=?", u)
    c.commit()
    c.close()
    async def notify_one(r, v):
        thumb = f"https://i.ytimg.com/vi/{v['id']}/maxresdefault.jpg"
        url = f"https://youtube.com/watch?v={v['id']}"
        tpl = r["msg"] or cfg("tpl_yt")
        text = (tpl.replace("{name}", r["name"]).replace("{title}", v["title"]).replace("{url}", url))
        c2 = db()
        c2.execute(
            "INSERT OR IGNORE INTO recent_videos(video_id,ch_name,title,thumb,url,ts,added_by) "
            "VALUES(?,?,?,?,?,?,?)",
            (v["id"], r["name"], v["title"], thumb, url, t, r["added_by"]),
        )
        c2.execute(
            "INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) "
            "VALUES(?,?,?,?,?,?,'yt',?,0)",
            (r["added_by"], f"فيديو جديد من {r['name']}", v["title"],
             thumb, cfg("btn_yt"), url, t),
        )
        tgs = c2.execute(
            "SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (r["added_by"],)
        ).fetchall()
        c2.commit()
        c2.close()
        asyncio.create_task(push_send_to_user(
            r["added_by"], f"فيديو جديد من {r['name']}",
            v["title"], thumb, url, f"yt:{v['id']}"
        ))
        for tg in tgs:
            await tg_send(tg["chat_id"], text, thumb, cfg("btn_yt"), url)
    await asyncio.gather(*(notify_one(r, v) for r, v in new_videos),
                         return_exceptions=True)


async def job_cleanup():
    c = db()
    c.execute("DELETE FROM discord_seen WHERE ts<?", (now() - 7 * 86400,))
    c.execute("DELETE FROM sessions WHERE expires<?", (now(),))
    c.execute("DELETE FROM rate_limits WHERE ts<?", (now() - 3600,))
    c.execute("DELETE FROM security_log WHERE id IN "
              "(SELECT id FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY id DESC) rn "
              "FROM security_log) WHERE rn > 5000)")
    c.execute("DELETE FROM recent_videos WHERE id IN "
              "(SELECT id FROM (SELECT id, ROW_NUMBER() OVER "
              "(PARTITION BY added_by ORDER BY ts DESC) rn FROM recent_videos) WHERE rn > 12)")
    c.execute("DELETE FROM notifs WHERE id IN "
              "(SELECT id FROM (SELECT id, ROW_NUMBER() OVER "
              "(PARTITION BY username ORDER BY ts DESC) rn FROM notifs) WHERE rn > 60)")
    c.execute("DELETE FROM suggestions WHERE ts<?", (now() - 90 * 86400,))
    c.commit()
    c.close()


# ═══════════════════════════════════════════════════════════
# FASTAPI APP
# ═══════════════════════════════════════════════════════════
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.add_job(job_kick, "interval", seconds=90)
    scheduler.add_job(job_yt, "interval", seconds=300)
    scheduler.add_job(job_cleanup, "interval", hours=6)
    scheduler.start()
    if DISCORD_TOKEN:
        asyncio.create_task(discord_client.start(DISCORD_TOKEN))
    else:
        print("[Discord] ⚠️ DISCORD_BOT_TOKEN غير مضبوط")
    if push_available():
        print("[Push] ✅ Web Push مفعّل")
    else:
        print("[Push] ⚠️ VAPID غير مضبوط")
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)


# ═══════════════════════════════════════════════════════════
# API — BOOT / GUEST
# ═══════════════════════════════════════════════════════════
@app.get("/api/boot")
async def boot(request: Request):
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
        "discord_watching": len(WATCH_CHANNELS),
    }


@app.get("/api/guest-preview")
async def guest_preview():
    if cfg("guest_mode", "1") != "1":
        raise HTTPException(403, "وضع الزائر معطل")
    c = db()
    kick_count = c.execute("SELECT COUNT(*) n FROM kick_channels WHERE enabled=1").fetchone()["n"]
    yt_count = c.execute("SELECT COUNT(*) n FROM yt_channels WHERE enabled=1").fetchone()["n"]
    tg_count = c.execute("SELECT COUNT(*) n FROM tg_channels WHERE enabled=1").fetchone()["n"]
    live_list = c.execute(
        "SELECT slug, name, avatar, title, viewers, thumb FROM kick_channels "
        "WHERE live=1 AND enabled=1 LIMIT 6"
    ).fetchall()
    c.close()
    return {
        "counts": {"kick": kick_count, "yt": yt_count, "tg": tg_count},
        "live": [dict(r) for r in live_list],
    }


# ═══════════════════════════════════════════════════════════
# API — AUTH (فقط دخول — بدون تسجيل)
# ═══════════════════════════════════════════════════════════
@app.post("/api/login")
async def login(request: Request, response: Response,
                u: str = Form(...), p: str = Form(...)):
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
    tok = new_session(row["username"])
    c = db()
    c.execute("UPDATE users SET last_login=? WHERE id=?", (now(), row["id"]))
    c.commit()
    c.close()
    log_sec(u, "login_ok", "", ip)
    response.set_cookie("rl_sid", tok, max_age=SESSION_TTL,
                        httponly=True, samesite="lax", secure=False)
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
    c = db()
    limits = {
        "kick": int(cfg("lim_kick", "10")),
        "yt": int(cfg("lim_yt", "5")),
        "tg": int(cfg("lim_tg", "3")),
    }
    usage = {
        "kick": c.execute("SELECT COUNT(*) n FROM kick_channels WHERE added_by=?", (u["username"],)).fetchone()["n"],
        "yt": c.execute("SELECT COUNT(*) n FROM yt_channels WHERE added_by=?", (u["username"],)).fetchone()["n"],
        "tg": c.execute("SELECT COUNT(*) n FROM tg_channels WHERE added_by=?", (u["username"],)).fetchone()["n"],
    }
    c.close()
    return {
        "user": {"username": u["username"], "display": u["display"], "role": u["role"]},
        "limits": limits, "usage": usage,
        "tpl_kick": cfg("tpl_kick"), "tpl_yt": cfg("tpl_yt"),
        "tpl_discord": cfg("tpl_discord"), "tpl_twitter": cfg("tpl_twitter"),
        "tpl_youtube_dc": cfg("tpl_youtube_dc"),
        "site_name": cfg("site_name", SITE_NAME),
        "has_telegram": bool(TELEGRAM_TOKEN),
        "has_discord": bool(DISCORD_TOKEN),
        "has_push": push_available(),
    }


# ═══════════════════════════════════════════════════════════
# API — CHANNELS
# ═══════════════════════════════════════════════════════════
@app.get("/api/channels/{kind}")
async def list_channels(kind: str, request: Request):
    u = require_auth(request)
    table = {"kick": "kick_channels", "yt": "yt_channels", "tg": "tg_channels"}.get(kind)
    if not table: raise HTTPException(404)
    c = db()
    if u["role"] == "owner":
        rows = c.execute(f"SELECT * FROM {table} ORDER BY id DESC").fetchall()
    else:
        rows = c.execute(f"SELECT * FROM {table} WHERE added_by=? ORDER BY id DESC",
                         (u["username"],)).fetchall()
    c.close()
    return {"rows": [dict(r) for r in rows]}


@app.get("/api/channels/{kind}/suggestions")
async def channel_suggestions(kind: str, request: Request):
    u = require_auth(request)
    if kind not in ("kick", "yt", "tg"): raise HTTPException(404)
    table = {"kick": "kick_channels", "yt": "yt_channels", "tg": "tg_channels"}[kind]
    ident_col = {"kick": "slug", "yt": "channel_id", "tg": "chat_id"}[kind]
    c = db()
    defaults = c.execute(
        "SELECT * FROM default_channels WHERE kind=? AND enabled=1 ORDER BY id DESC", (kind,)
    ).fetchall()
    mine = set(r[ident_col] for r in c.execute(
        f"SELECT {ident_col} FROM {table} WHERE added_by=?", (u["username"],)
    ).fetchall())
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
    if kind == "kick":
        slug = re.sub(r"[^a-z0-9_-]", "", (body.get("slug") or "").lower().replace("@", ""))
        if not slug:
            c.close()
            return JSONResponse({"error": "اسم غير صالح"}, 400)
        if c.execute("SELECT 1 FROM kick_channels WHERE slug=? AND added_by=?",
                     (slug, u["username"])).fetchone():
            c.close()
            return JSONResponse({"error": "مضافة مسبقاً"}, 409)
        if not check_limit(u["username"], "kick", u["role"]):
            c.close()
            return JSONResponse({"error": "وصلت الحد الأقصى"}, 400)
        info = await kick_fetch(slug)
        c.execute(
            "INSERT INTO kick_channels(slug,name,avatar,banner,msg,enabled,live,title,"
            "viewers,thumb,last_check,added_by,created) VALUES(?,?,?,?,?,1,?,?,?,?,?,?,?)",
            (slug, (info or {}).get("name") or slug, (info or {}).get("avatar") or "",
             (info or {}).get("banner") or "", body.get("msg", "")[:1500],
             1 if (info or {}).get("live") else 0, (info or {}).get("title") or "",
             (info or {}).get("viewers") or 0, (info or {}).get("thumb") or "",
             t, u["username"], t),
        )
    elif kind == "yt":
        info = await yt_resolve(body.get("channel_id") or body.get("input") or "")
        if not info:
            c.close()
            return JSONResponse({"error": "تعذّر التعرف على القناة"}, 400)
        cid = info["channel_id"]
        if c.execute("SELECT 1 FROM yt_channels WHERE channel_id=? AND added_by=?",
                     (cid, u["username"])).fetchone():
            c.close()
            return JSONResponse({"error": "مضافة مسبقاً"}, 409)
        if not check_limit(u["username"], "yt", u["role"]):
            c.close()
            return JSONResponse({"error": "وصلت الحد الأقصى"}, 400)
        feed = await yt_feed(cid)
        last = feed[0]["id"] if feed else ""
        c.execute(
            "INSERT INTO yt_channels(channel_id,handle,name,avatar,msg,enabled,last_video,"
            "last_check,added_by,created) VALUES(?,?,?,?,?,1,?,?,?,?)",
            (cid, "", info["name"] or cid, info.get("avatar") or "",
             body.get("msg", "")[:1500], last, t, u["username"], t),
        )
    elif kind == "tg":
        raw = (body.get("chat_id") or "").strip()
        cid = norm_chat(raw)
        if not cid:
            c.close()
            return JSONResponse({"error": "معرّف غير صالح"}, 400)
        if c.execute("SELECT 1 FROM tg_channels WHERE chat_id=? AND added_by=?",
                     (cid, u["username"])).fetchone():
            c.close()
            return JSONResponse({"error": "مضافة مسبقاً"}, 409)
        if not check_limit(u["username"], "tg", u["role"]):
            c.close()
            return JSONResponse({"error": "وصلت الحد الأقصى"}, 400)
        c.execute(
            "INSERT INTO tg_channels(chat_id,username,name,avatar,enabled,added_by,created) "
            "VALUES(?,?,?,?,1,?,?)",
            (cid, cid if cid.startswith("@") else "", body.get("name") or cid, "",
             u["username"], t),
        )
    else:
        c.close()
        raise HTTPException(404)
    c.commit()
    c.close()
    return {"ok": True}


@app.post("/api/channels/{kind}/bulk-add")
async def bulk_add_suggestions(kind: str, request: Request):
    u = require_auth(request)
    if kind not in ("kick", "yt", "tg"): raise HTTPException(404)
    body = await request.json()
    ids = body.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return JSONResponse({"error": "لا توجد قنوات"}, 400)
    ids = [int(x) for x in ids if str(x).isdigit()][:50]
    if not ids:
        return JSONResponse({"error": "معرّفات غير صالحة"}, 400)
    c = db()
    rows = c.execute(
        f"SELECT * FROM default_channels WHERE id IN ({','.join('?' * len(ids))}) AND kind=? AND enabled=1",
        (*ids, kind)
    ).fetchall()
    c.close()
    if not rows:
        return JSONResponse({"error": "لا توجد قنوات"}, 404)
    added, failed, errors = 0, 0, []
    for row in rows:
        if not check_limit(u["username"], kind, u["role"]):
            errors.append(f"{row['name']}: وصلت الحد")
            failed += 1
            continue
        try:
            c = db()
            t = now()
            if kind == "kick":
                if c.execute("SELECT 1 FROM kick_channels WHERE slug=? AND added_by=?",
                             (row["identifier"], u["username"])).fetchone():
                    c.close()
                    failed += 1
                    errors.append(f"{row['name']}: مضافة مسبقاً")
                    continue
                info = await kick_fetch(row["identifier"])
                c.execute(
                    "INSERT INTO kick_channels(slug,name,avatar,banner,msg,enabled,live,title,"
                    "viewers,thumb,last_check,added_by,created) VALUES(?,?,?,?,?,1,?,?,?,?,?,?,?)",
                    (row["identifier"], (info or {}).get("name") or row["name"] or row["identifier"],
                     (info or {}).get("avatar") or row["avatar"] or "",
                     (info or {}).get("banner") or "", "",
                     1 if (info or {}).get("live") else 0, (info or {}).get("title") or "",
                     (info or {}).get("viewers") or 0, (info or {}).get("thumb") or "",
                     t, u["username"], t),
                )
            elif kind == "yt":
                if c.execute("SELECT 1 FROM yt_channels WHERE channel_id=? AND added_by=?",
                             (row["identifier"], u["username"])).fetchone():
                    c.close()
                    failed += 1
                    errors.append(f"{row['name']}: مضافة مسبقاً")
                    continue
                feed = await yt_feed(row["identifier"])
                last = feed[0]["id"] if feed else ""
                c.execute(
                    "INSERT INTO yt_channels(channel_id,handle,name,avatar,msg,enabled,"
                    "last_video,last_check,added_by,created) VALUES(?,?,?,?,?,1,?,?,?,?)",
                    (row["identifier"], "", row["name"] or row["identifier"],
                     row["avatar"] or "", "", last, t, u["username"], t),
                )
            elif kind == "tg":
                if c.execute("SELECT 1 FROM tg_channels WHERE chat_id=? AND added_by=?",
                             (row["identifier"], u["username"])).fetchone():
                    c.close()
                    failed += 1
                    errors.append(f"{row['name']}: مضافة مسبقاً")
                    continue
                c.execute(
                    "INSERT INTO tg_channels(chat_id,username,name,avatar,enabled,added_by,created) "
                    "VALUES(?,?,?,?,1,?,?)",
                    (row["identifier"], row["identifier"] if row["identifier"].startswith("@") else "",
                     row["name"] or row["identifier"], row["avatar"] or "", u["username"], t),
                )
            c.commit()
            c.close()
            added += 1
        except Exception as e:
            failed += 1
            errors.append(f"{row['name']}: {str(e)[:60]}")
    return {"ok": True, "added": added, "failed": failed, "errors": errors}


@app.delete("/api/channels/{kind}/{cid}")
async def del_channel(kind: str, cid: int, request: Request):
    u = require_auth(request)
    table = {"kick": "kick_channels", "yt": "yt_channels", "tg": "tg_channels"}.get(kind)
    if not table: raise HTTPException(404)
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
    if not table: raise HTTPException(404)
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
    if "enabled" in body: sets.append("enabled=?"); vals.append(1 if body["enabled"] else 0)
    if "msg" in body: sets.append("msg=?"); vals.append(str(body["msg"])[:1500])
    if "name" in body: sets.append("name=?"); vals.append(str(body["name"])[:80])
    if sets:
        vals.append(cid)
        c.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?", vals)
        c.commit()
    c.close()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════
# API — DISCORD FEEDS
# ═══════════════════════════════════════════════════════════
@app.get("/api/discord/feeds")
async def list_feeds(request: Request):
    u = require_auth(request)
    c = db()
    rows = c.execute("SELECT * FROM discord_feeds WHERE added_by=? ORDER BY id DESC",
                     (u["username"],)).fetchall()
    c.close()
    known = {}
    if discord_client.is_ready():
        for g in discord_client.guilds:
            if ALLOWED_GUILDS and str(g.id) not in ALLOWED_GUILDS: continue
            for ch in g.text_channels:
                known[str(ch.id)] = {"name": ch.name, "guild": g.name}
    return {"rows": [dict(r) for r in rows], "known_channels": known, "watching": WATCH_CHANNELS}


@app.post("/api/discord/feeds")
async def add_feed(request: Request):
    u = require_auth(request)
    body = await request.json()
    ch = str(body.get("channel_id") or "").strip()
    if not ch or not ch.isdigit():
        return JSONResponse({"error": "channel_id يجب أن يكون رقماً"}, 400)
    if ch not in WATCH_CHANNELS:
        return JSONResponse({"error": "هذا الروم غير مُراقب"}, 400)
    tpl = str(body.get("template") or "")[:2000]
    name = str(body.get("channel_name") or "")[:100]
    source = str(body.get("source_type") or "generic")[:20]
    c = db()
    if c.execute("SELECT 1 FROM discord_feeds WHERE channel_id=? AND added_by=?",
                 (ch, u["username"])).fetchone():
        c.close()
        return JSONResponse({"error": "مضاف مسبقاً"}, 409)
    c.execute(
        "INSERT INTO discord_feeds(channel_id,channel_name,template,source_type,enabled,"
        "added_by,created) VALUES(?,?,?,?,1,?,?)",
        (ch, name, tpl, source, u["username"], now()),
    )
    c.commit()
    c.close()
    return {"ok": True}


@app.patch("/api/discord/feeds/{fid}")
async def patch_feed(fid: int, request: Request):
    u = require_auth(request)
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
    if "template" in body: sets.append("template=?"); vals.append(str(body["template"])[:2000])
    if "enabled" in body: sets.append("enabled=?"); vals.append(1 if body["enabled"] else 0)
    if sets:
        vals.append(fid)
        c.execute(f"UPDATE discord_feeds SET {', '.join(sets)} WHERE id=?", vals)
        c.commit()
    c.close()
    return {"ok": True}


@app.delete("/api/discord/feeds/{fid}")
async def del_feed(fid: int, request: Request):
    u = require_auth(request)
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
# API — NOTIFICATIONS
# ═══════════════════════════════════════════════════════════
@app.get("/api/notifs")
async def notifs(request: Request):
    u = require_auth(request)
    c = db()
    unread = c.execute("SELECT COUNT(*) n FROM notifs WHERE username=? AND is_read=0",
                       (u["username"],)).fetchone()["n"]
    if request.query_params.get("count"):
        c.close()
        return {"unread": unread}
    rows = c.execute("SELECT * FROM notifs WHERE username=? ORDER BY ts DESC LIMIT 50",
                     (u["username"],)).fetchall()
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
    if not text: return JSONResponse({"error": "النص فارغ"}, 400)
    if len(text) > 1000: return JSONResponse({"error": "الحد 1000 حرف"}, 400)
    if not rate_ok(f"sug:{u['username']}", max_per_min=3):
        return JSONResponse({"error": "عدد كبير من الاقتراحات"}, 429)
    c = db()
    c.execute("INSERT INTO suggestions(username,text,is_read,ts) VALUES(?,?,0,?)",
              (u["username"], text[:1000], now()))
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
        c.execute("UPDATE suggestions SET is_read=? WHERE id=?",
                  (1 if body["is_read"] else 0, sid))
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
# API — WEB PUSH
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
        "INSERT INTO push_subs(username,endpoint,p256dh,auth,ts) "
        "VALUES(?,?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET "
        "username=excluded.username,p256dh=excluded.p256dh,auth=excluded.auth,ts=excluded.ts",
        (u["username"], endpoint[:600], p256dh[:200], auth_key[:200], now()),
    )
    c.commit()
    c.close()
    return {"ok": True}


@app.post("/api/push/unsubscribe")
async def push_unsubscribe(request: Request):
    u = require_auth(request)
    body = await request.json()
    endpoint = body.get("endpoint") or ""
    c = db()
    c.execute("DELETE FROM push_subs WHERE endpoint=? AND username=?",
              (endpoint[:600], u["username"]))
    c.commit()
    c.close()
    return {"ok": True}


@app.post("/api/push/test")
async def push_test(request: Request):
    u = require_auth(request)
    if not push_available():
        return JSONResponse({"error": "Push غير مفعّل"}, 400)
    sent = await push_send_to_user(
        u["username"], "تجربة الإشعارات",
        "إذا وصلتك هذي، فالإشعارات تعمل ✅", "", "/", "test"
    )
    if sent == 0:
        return JSONResponse({"error": "لا يوجد اشتراك فعّال"}, 404)
    return {"ok": True, "sent": sent}


# ═══════════════════════════════════════════════════════════
# API — IMAGES UPLOAD
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
    c.execute("INSERT INTO images(id,mime,data,size,uploaded_by,created) VALUES(?,?,?,?,?,?)",
              (img_id, mime, content, len(content), u["username"], now()))
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
    if not row: raise HTTPException(404, "غير موجودة")
    return FastResponse(content=row["data"], media_type=row["mime"],
                        headers={"cache-control": "public, max-age=31536000, immutable"})


# ═══════════════════════════════════════════════════════════
# API — SETTINGS
# ═══════════════════════════════════════════════════════════
@app.get("/api/settings")
async def get_settings(request: Request):
    require_auth(request)
    keys = ["site_name", "site_sub", "hero_title", "hero_accent", "hero_text",
            "tpl_kick", "tpl_yt", "tpl_discord", "tpl_twitter", "tpl_youtube_dc",
            "btn_kick", "btn_yt", "lim_kick", "lim_yt", "lim_tg",
            "guest_mode", "guest_blur"]
    return {k: cfg(k) for k in keys}


@app.post("/api/settings")
async def save_settings(request: Request):
    require_owner(request)
    body = await request.json()
    allowed = ["site_name", "site_sub", "hero_title", "hero_accent", "hero_text",
               "tpl_kick", "tpl_yt", "tpl_discord", "tpl_twitter", "tpl_youtube_dc",
               "btn_kick", "btn_yt", "lim_kick", "lim_yt", "lim_tg",
               "guest_mode", "guest_blur"]
    for k in allowed:
        if k in body: set_cfg(k, str(body[k])[:2000])
    return {"ok": True}


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
    if not raw: return JSONResponse({"error": "المعرّف مطلوب"}, 400)
    if kind == "kick":
        ident = re.sub(r"[^a-z0-9_-]", "", raw.lower().replace("@", ""))
        name = body.get("name") or ident
        avatar = ""
        info = await kick_fetch(ident)
        if info:
            name = info["name"]; avatar = info["avatar"]
    elif kind == "yt":
        info = await yt_resolve(raw)
        if not info: return JSONResponse({"error": "تعذّر التعرف على القناة"}, 400)
        ident = info["channel_id"]
        name = info["name"] or ident
        avatar = info.get("avatar") or ""
    else:
        ident = norm_chat(raw)
        if not ident: return JSONResponse({"error": "معرّف غير صالح"}, 400)
        name = body.get("name") or ident
        avatar = ""
    c = db()
    if c.execute("SELECT 1 FROM default_channels WHERE kind=? AND identifier=?",
                 (kind, ident)).fetchone():
        c.close()
        return JSONResponse({"error": "موجودة مسبقاً"}, 409)
    c.execute("INSERT INTO default_channels(kind,identifier,name,avatar,enabled,created) "
              "VALUES(?,?,?,?,1,?)", (kind, ident, name, avatar, now()))
    c.commit()
    c.close()
    return {"ok": True}


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
    if "enabled" in body: sets.append("enabled=?"); vals.append(1 if body["enabled"] else 0)
    if "name" in body: sets.append("name=?"); vals.append(str(body["name"])[:80])
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
    rows = c.execute(
        "SELECT id, username, display, role, active, banned, lim_kick, lim_yt, lim_tg, "
        "created, last_login FROM users ORDER BY id"
    ).fetchall()
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
    if len(pw) < 6: return JSONResponse({"error": "كلمة المرور 6+"}, 400)
    if un.lower() == ADMIN_USERNAME.lower(): return JSONResponse({"error": "محجوز"}, 400)
    c = db()
    if c.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)", (un,)).fetchone():
        c.close()
        return JSONResponse({"error": "مستخدم"}, 409)
    salt = secrets.token_hex(16)
    opt = lambda v: (None if v in ("", None) else max(0, min(1000, int(v))))
    c.execute(
        "INSERT INTO users(username,display,pass_hash,salt,role,active,banned,"
        "lim_kick,lim_yt,lim_tg,created) VALUES(?,?,?,?,'user',1,0,?,?,?,?)",
        (un, (body.get("display") or un)[:60], hash_pw(pw, salt), salt,
         opt(body.get("lim_kick")), opt(body.get("lim_yt")), opt(body.get("lim_tg")), now()),
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
    opt = lambda v: (None if v in ("", None) else max(0, min(1000, int(v))))
    if "banned" in body and not is_self and not is_admin_acc:
        sets.append("banned=?"); vals.append(1 if body["banned"] else 0)
    if "active" in body and not is_self and not is_admin_acc:
        sets.append("active=?"); vals.append(1 if body["active"] else 0)
    if "role" in body and not is_admin_acc:
        sets.append("role=?"); vals.append("owner" if body["role"] == "owner" else "user")
    if "display" in body:
        sets.append("display=?"); vals.append(str(body["display"])[:60] or row["username"])
    for k in ("lim_kick", "lim_yt", "lim_tg"):
        if k in body:
            sets.append(f"{k}=?"); vals.append(opt(body[k]))
    pw_changed = False
    if body.get("password"):
        if len(str(body["password"])) < 6:
            c.close()
            return JSONResponse({"error": "كلمة المرور 6+"}, 400)
        salt = secrets.token_hex(16)
        sets.append("pass_hash=?"); vals.append(hash_pw(str(body["password"]), salt))
        sets.append("salt=?"); vals.append(salt)
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
    stats["watching"] = len(WATCH_CHANNELS)
    stats["has_telegram"] = bool(TELEGRAM_TOKEN)
    stats["has_discord"] = bool(DISCORD_TOKEN)
    stats["has_push"] = push_available()
    return stats


@app.get("/api/admin/security")
async def admin_security(request: Request):
    require_owner(request)
    c = db()
    rows = c.execute(
        "SELECT ts, username, action, detail, ip FROM security_log ORDER BY id DESC LIMIT 200"
    ).fetchall()
    c.close()
    return {"rows": [dict(r) for r in rows]}


# ═══════════════════════════════════════════════════════════
# ROOT + HEALTH
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
    return JSONResponse({
        "name": cfg("site_name", SITE_NAME),
        "short_name": cfg("site_name", SITE_NAME)[:12],
        "start_url": "/", "display": "standalone",
        "background_color": "#030508", "theme_color": "#030508",
        "dir": "rtl", "lang": "ar",
    })


@app.get("/health")
async def health():
    return {
        "ok": True,
        "discord_ready": discord_client.is_ready() if discord_client else False,
        "watching": len(WATCH_CHANNELS),
        "push_enabled": push_available(),
        "telegram_enabled": bool(TELEGRAM_TOKEN),
    }


# ═══════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
