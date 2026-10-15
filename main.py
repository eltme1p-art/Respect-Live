"""
Respect Live — نظام مراقبة قنوات البث + بوت ديسكورد
FastAPI + Discord.py + SQLite + APScheduler
النسخة الكاملة — بدون حذف
"""
import os, re, json, time, hashlib, secrets, sqlite3, asyncio, html
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import discord
from fastapi import FastAPI, Request, Response, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════
#                        CONFIG
# ═══════════════════════════════════════════════════════════
ADMIN_USERNAME  = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD  = os.getenv("ADMIN_PASSWORD", "changeme")
SESSION_SECRET  = os.getenv("SESSION_SECRET", secrets.token_hex(32))
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN", "")
DISCORD_TOKEN   = os.getenv("DISCORD_BOT_TOKEN", "")
WATCH_CHANNELS  = [c.strip() for c in os.getenv("DISCORD_WATCH_CHANNELS", "").split(",") if c.strip()]
ALLOWED_GUILDS  = [g.strip() for g in os.getenv("DISCORD_ALLOWED_GUILDS", "").split(",") if g.strip()]
SITE_NAME       = os.getenv("SITE_NAME", "Respect Live")
DB_PATH         = os.getenv("DB_PATH", "respect.db")
SESSION_TTL     = 7 * 24 * 3600
UA              = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

# حدود الإرسال لكل مستخدم
MAX_PER_MIN_TG  = 30    # رسائل تيليجرام/دقيقة
MAX_PER_MIN_CH  = 10    # إضافات قنوات/دقيقة
BATCH_KICK      = 30    # قنوات كيك لكل دورة
BATCH_YT        = 30    # قنوات يوتيوب لكل دورة


# ═══════════════════════════════════════════════════════════
#                       DATABASE
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

-- ⚙️ القنوات الافتراضية (يضيفها المالك، تظهر كاقتراحات للمستخدمين)
CREATE TABLE IF NOT EXISTS default_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,             -- 'kick' | 'yt' | 'tg'
    identifier TEXT NOT NULL,       -- slug | channel_id | chat_id
    name TEXT DEFAULT '',
    avatar TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    created INTEGER,
    UNIQUE(kind, identifier)
);
CREATE INDEX IF NOT EXISTS idx_def_kind ON default_channels(kind, enabled);

-- قنوات كيك (خاصة بكل مستخدم)
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

-- 📥 روابط ديسكورد (تربط روم ديسكورد بقنوات TG للمستخدم)
CREATE TABLE IF NOT EXISTS discord_feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    channel_name TEXT DEFAULT '',
    template TEXT DEFAULT '',
    source_type TEXT DEFAULT 'generic',  -- 'generic' | 'twitter' | 'youtube'
    enabled INTEGER DEFAULT 1,
    added_by TEXT NOT NULL, created INTEGER,
    UNIQUE(channel_id, added_by)
);
CREATE INDEX IF NOT EXISTS idx_df_by ON discord_feeds(added_by);
CREATE INDEX IF NOT EXISTS idx_df_ch ON discord_feeds(channel_id, enabled);

-- 🔒 منع تكرار رسائل ديسكورد (لكل رسالة ID فريد)
CREATE TABLE IF NOT EXISTS discord_seen (
    message_id TEXT PRIMARY KEY, ts INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ds_ts ON discord_seen(ts);

-- إشعارات داخلية للمستخدمين
CREATE TABLE IF NOT EXISTS notifs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL, title TEXT DEFAULT '', body TEXT DEFAULT '',
    image TEXT DEFAULT '', btn_text TEXT DEFAULT '', btn_url TEXT DEFAULT '',
    kind TEXT DEFAULT 'admin', ts INTEGER, is_read INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_notifs ON notifs(username, ts);

-- فيديوهات يوتيوب الأخيرة
CREATE TABLE IF NOT EXISTS recent_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL, ch_name TEXT DEFAULT '', title TEXT DEFAULT '',
    thumb TEXT DEFAULT '', url TEXT DEFAULT '', ts INTEGER,
    added_by TEXT NOT NULL, UNIQUE(video_id, added_by)
);
CREATE INDEX IF NOT EXISTS idx_rv_by ON recent_videos(added_by, ts);

-- Rate limiting
CREATE TABLE IF NOT EXISTS rate_limits (k TEXT PRIMARY KEY, cnt INTEGER, ts INTEGER);

-- سجل أمني
CREATE TABLE IF NOT EXISTS security_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER, username TEXT, action TEXT, detail TEXT, ip TEXT
);
CREATE INDEX IF NOT EXISTS idx_sec_ts ON security_log(ts);
"""


def init_db():
    c = db()
    c.executescript(SCHEMA)
    # تأكد من وجود حساب المالك
    if not c.execute("SELECT 1 FROM users WHERE username=?", (ADMIN_USERNAME,)).fetchone():
        salt = secrets.token_hex(16)
        c.execute(
            "INSERT INTO users(username,display,pass_hash,salt,role,active,banned,created) "
            "VALUES(?,?,?,?,'owner',1,0,?)",
            (ADMIN_USERNAME, ADMIN_USERNAME, hash_pw(ADMIN_PASSWORD, salt), salt, now()),
        )
    # الإعدادات الافتراضية
    defaults = {
        "site_name": SITE_NAME,
        "site_sub": "STREAM MONITOR · OFFICIAL",
        "hero_title": "مراقبة",
        "hero_accent": "القنوات.",
        "hero_text": "تابع قنواتك على كيك ويوتيوب وتيليجرام في مكان واحد. إشعارات فورية عند أي بث أو فيديو جديد.",
        "tpl_kick": "<b>{name}</b>\nبدأ بثاً مباشراً الآن\n\n<b>{title}</b>",
        "tpl_yt":   "<b>{name}</b>\nنشر فيديو جديداً\n\n<b>{title}</b>",
        "tpl_discord": "<b>{author}</b>\n{content}",
        "tpl_twitter": "<b>{author}</b>\n{content}",
        "tpl_youtube_dc": "<b>{author}</b>\n{content}",
        "btn_kick": "شاهد البث",
        "btn_yt":   "شاهد الفيديو",
        "lim_kick": "10",
        "lim_yt":   "5",
        "lim_tg":   "3",
        "guest_mode": "1",     # 1 = يسمح بالتصفح كزائر مع تغبيش
        "guest_blur": "14",    # درجة التغبيش بالبكسل
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings(k,v) VALUES(?,?)", (k, v))
    # قنوات افتراضية للأمثلة (يمكن للمالك حذفها)
    defaults_channels = [
        ("kick", "xqc", "xQc", ""),
        ("yt", "UCX6OQ3DkcsbYNE6H8uQQuVA", "MrBeast", ""),
    ]
    for kind, ident, name, avatar in defaults_channels:
        c.execute(
            "INSERT OR IGNORE INTO default_channels(kind,identifier,name,avatar,enabled,created) "
            "VALUES(?,?,?,?,1,?)",
            (kind, ident, name, avatar, now()),
        )
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
#                    RATE LIMITING (per user)
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
#                        AUTH
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


# ═══════════════════════════════════════════════════════════
#                     TELEGRAM
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
#                        KICK
# ═══════════════════════════════════════════════════════════
async def kick_fetch(slug: str) -> Optional[dict]:
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
#                      YOUTUBE
# ═══════════════════════════════════════════════════════════
async def yt_feed(channel_id: str) -> Optional[list]:
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


async def yt_resolve(input_str: str) -> Optional[dict]:
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
            return {"channel_id": cid, "name": title, "avatar": avatar}
        except Exception:
            return {"channel_id": cid, "name": cid, "avatar": ""}
    # @handle
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
            return {"channel_id": cid, "name": title, "avatar": avatar}
        except Exception:
            return None
    return None


# ═══════════════════════════════════════════════════════════
#                    DISCORD BOT
# ═══════════════════════════════════════════════════════════
discord_client = discord.Client(intents=discord.Intents(
    guilds=True,
    guild_messages=True,
    message_content=True,
))


@discord_client.event
async def on_ready():
    print(f"[Discord] ✅ {discord_client.user} في {len(discord_client.guilds)} سيرفر")
    print(f"[Discord] يراقب {len(WATCH_CHANNELS)} روم: {WATCH_CHANNELS}")
    if ALLOWED_GUILDS:
        print(f"[Discord] 🛡️ السيرفرات المسموحة: {ALLOWED_GUILDS}")


def classify_message_source(msg: discord.Message) -> str:
    """يحدد نوع المصدر (تويتر/يوتيوب/عادي) عبر embeds والرابط."""
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
    """يستخرج اسم المؤلف والمحتوى من الرسالة أو من الـ embed."""
    author = msg.author.display_name or msg.author.name or ""
    content = (msg.content or "").strip()[:2000]
    # إذا الرسالة من بوت و فيها embed → استخدم بيانات embed
    if msg.author.bot and msg.embeds:
        e = msg.embeds[0]
        # اسم المصدر (تويتر/يوتيوب)
        if e.author and e.author.name:
            author = e.author.name
        elif e.provider and e.provider.name:
            author = e.provider.name
        # المحتوى
        parts = []
        if e.title:
            parts.append(e.title.strip())
        if e.description:
            parts.append(e.description.strip())
        if parts:
            content = "\n".join(parts)[:2000]
    return author, content


def extract_image_and_url(msg: discord.Message) -> tuple:
    """يستخرج الصورة والرابط من الرسالة."""
    image, url = "", ""
    if msg.embeds:
        e = msg.embeds[0]
        if e.image and e.image.url:
            image = e.image.url
        elif e.thumbnail and e.thumbnail.url:
            image = e.thumbnail.url
        url = e.url or ""
    if not image and msg.attachments:
        for a in msg.attachments:
            if a.content_type and a.content_type.startswith("image/"):
                image = a.url
                break
    return image, url


@discord_client.event
async def on_message(msg: discord.Message):
    # 🛡️ 1) تجاهل رسائل البوتات (منع الحلقات)
    if msg.author.bot and not msg.embeds:
        # نسمح لرسائل البوت فقط إذا كانت فيها embeds (تويتر/يوتيوب تعمل هكذا)
        return
    # 🛡️ 2) تجاهل DMs
    if msg.guild is None:
        return
    # 🛡️ 3) تحقق من السيرفر المسموح (إذا محدد)
    if ALLOWED_GUILDS and str(msg.guild.id) not in ALLOWED_GUILDS:
        return
    # 🛡️ 4) فقط الرومات المراقبة
    ch_id = str(msg.channel.id)
    if ch_id not in WATCH_CHANNELS:
        return

    # 🔒 منع التكرار
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

    # ابحث عن روابط المستخدمين لهذا الروم
    feeds = c.execute(
        "SELECT * FROM discord_feeds WHERE channel_id=? AND enabled=1", (ch_id,)
    ).fetchall()
    c.close()

    if not feeds:
        return

    for feed in feeds:
        owner = feed["added_by"]
        # 🛡️ Rate limit
        if not rate_ok(f"discord:{owner}", max_per_min=MAX_PER_MIN_TG):
            print(f"[Discord] Rate limit → {owner}")
            continue

        # اختر القالب المناسب
        if feed["template"]:
            tpl = feed["template"]
        elif source == "twitter":
            tpl = cfg("tpl_twitter") or cfg("tpl_discord")
        elif source == "youtube":
            tpl = cfg("tpl_youtube_dc") or cfg("tpl_discord")
        else:
            tpl = cfg("tpl_discord")

        text = (tpl
                .replace("{author}", author)
                .replace("{content}", content)
                .replace("{channel}", getattr(msg.channel, "name", "") or "")
                .replace("{source}", source))

        # أرسل لقنوات TG الخاصة بصاحب الربط
        c2 = db()
        tgs = c2.execute(
            "SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (owner,)
        ).fetchall()
        # أنشئ إشعار داخلي
        c2.execute(
            "INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) "
            "VALUES(?,?,?,?,?,?,'discord',?,0)",
            (owner, author or "رسالة ديسكورد", content[:500], image,
             "فتح الرابط" if url else "", url or "", now()),
        )
        c2.commit()
        c2.close()
        for tg in tgs:
            await tg_send(tg["chat_id"], text, image, "عرض", url)


# ═══════════════════════════════════════════════════════════
#                  BACKGROUND JOBS (batched)
# ═══════════════════════════════════════════════════════════
async def job_kick():
    """فحص قنوات كيك — يعالج BATCH_KICK قناة في كل دورة، دفعة واحدة."""
    c = db()
    rows = c.execute(
        "SELECT * FROM kick_channels WHERE enabled=1 AND last_check<? "
        "ORDER BY last_check LIMIT ?",
        (now() - 90, BATCH_KICK),
    ).fetchall()
    c.close()
    if not rows:
        return

    # 1) اجلب كل المعلومات أولاً (بالتوازي المحدود)
    infos = {}
    sem = asyncio.Semaphore(8)

    async def fetch_one(r):
        async with sem:
            infos[r["slug"]] = await kick_fetch(r["slug"])

    await asyncio.gather(*(fetch_one(r) for r in rows), return_exceptions=True)

    # 2) جهّز التحديثات دفعة واحدة
    updates = []
    live_events = []
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

    # 3) نفذ كل التحديثات في معاملة واحدة
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

    # 4) أرسل إشعارات البث (بالتوازي المحدود)
    async def notify_one(r, info):
        tpl = r["msg"] or cfg("tpl_kick")
        text = (tpl
                .replace("{name}", info["name"])
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
        for tg in tgs:
            await tg_send(tg["chat_id"], text, info["banner"] or info["thumb"],
                          cfg("btn_kick"), f"https://kick.com/{r['slug']}")

    await asyncio.gather(*(notify_one(r, info) for r, info in live_events),
                         return_exceptions=True)


async def job_yt():
    """فحص قنوات يوتيوب — دفعة واحدة."""
    c = db()
    rows = c.execute(
        "SELECT * FROM yt_channels WHERE enabled=1 AND last_check<? "
        "ORDER BY last_check LIMIT ?",
        (now() - 300, BATCH_YT),
    ).fetchall()
    c.close()
    if not rows:
        return

    # 1) اجلب كل الفيدات بالتوازي
    feeds = {}
    sem = asyncio.Semaphore(8)

    async def fetch_one(r):
        async with sem:
            feeds[r["channel_id"]] = await yt_feed(r["channel_id"])

    await asyncio.gather(*(fetch_one(r) for r in rows), return_exceptions=True)

    # 2) جهّز التحديثات والأحداث
    updates = []
    new_videos = []
    t = now()
    for r in rows:
        items = feeds.get(r["channel_id"])
        if not items:
            updates.append((t, r["id"]))
            continue
        latest = items[0]["id"]
        # احسب الجديد
        if r["last_video"] and latest != r["last_video"]:
            fresh = []
            for it in items:
                if it["id"] == r["last_video"]:
                    break
                fresh.append(it)
            for v in reversed(fresh[:3]):
                new_videos.append((r, v))
        updates.append((latest, t, r["id"]))

    # 3) نفذ في معاملة واحدة
    c = db()
    for u in updates:
        if len(u) == 2:
            c.execute("UPDATE yt_channels SET last_check=? WHERE id=?", u)
        else:
            c.execute("UPDATE yt_channels SET last_video=?,last_check=? WHERE id=?", u)
    c.commit()
    c.close()

    # 4) أرسل الإشعارات واحفظ الفيديوهات
    async def notify_one(r, v):
        thumb = f"https://i.ytimg.com/vi/{v['id']}/maxresdefault.jpg"
        url = f"https://youtube.com/watch?v={v['id']}"
        tpl = r["msg"] or cfg("tpl_yt")
        text = (tpl
                .replace("{name}", r["name"])
                .replace("{title}", v["title"])
                .replace("{url}", url))
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
        for tg in tgs:
            await tg_send(tg["chat_id"], text, thumb, cfg("btn_yt"), url)

    await asyncio.gather(*(notify_one(r, v) for r, v in new_videos),
                         return_exceptions=True)


async def job_cleanup():
    """تنظيف دوري — دفعة واحدة."""
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
    c.commit()
    c.close()


# ═══════════════════════════════════════════════════════════
#                    FASTAPI APP
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
        print("[Discord] ⚠️ DISCORD_BOT_TOKEN غير مضبوط — البوت لن يعمل")
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)


# ═══════════════════════════════════════════════════════════
#                 API — AUTH
# ═══════════════════════════════════════════════════════════
@app.get("/api/boot")
async def boot(request: Request):
    """يُستدعى قبل تسجيل الدخول — يعطي معلومات الموقع فقط."""
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
        "discord_watching": len(WATCH_CHANNELS),
    }


@app.get("/api/guest-preview")
async def guest_preview():
    """يُعرض للزوار بدون تسجيل — نسخة عامة من البيانات."""
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


@app.post("/api/register")
async def register(response: Response, u: str = Form(...), p: str = Form(...)):
    u = u.strip()
    if len(u) < 3 or len(u) > 30 or not re.match(r"^[A-Za-z0-9_.-]+$", u):
        return JSONResponse({"error": "الاسم 3-30 حرف إنجليزي/رقم"}, 400)
    if len(p) < 6:
        return JSONResponse({"error": "كلمة المرور 6 أحرف على الأقل"}, 400)
    c = db()
    if c.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)", (u,)).fetchone():
        c.close()
        return JSONResponse({"error": "الاسم مستخدم"}, 409)
    salt = secrets.token_hex(16)
    c.execute(
        "INSERT INTO users(username,display,pass_hash,salt,role,active,banned,created) "
        "VALUES(?,?,?,?,'user',1,0,?)",
        (u, u, hash_pw(p, salt), salt, now()),
    )
    c.commit()
    c.close()
    tok = new_session(u)
    response.set_cookie("rl_sid", tok, max_age=SESSION_TTL,
                        httponly=True, samesite="lax", secure=False)
    return {"ok": True}


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
        "limits": limits,
        "usage": usage,
        "tpl_kick": cfg("tpl_kick"),
        "tpl_yt": cfg("tpl_yt"),
        "tpl_discord": cfg("tpl_discord"),
        "tpl_twitter": cfg("tpl_twitter"),
        "tpl_youtube_dc": cfg("tpl_youtube_dc"),
        "site_name": cfg("site_name", SITE_NAME),
        "has_telegram": bool(TELEGRAM_TOKEN),
        "has_discord": bool(DISCORD_TOKEN),
    }


# ═══════════════════════════════════════════════════════════
#                 API — CHANNELS
# ═══════════════════════════════════════════════════════════
def require_auth(request: Request):
    u = auth(request)
    if not u:
        raise HTTPException(401, "غير مسجل")
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
        rows = c.execute(f"SELECT * FROM {table} WHERE added_by=? ORDER BY id DESC",
                         (u["username"],)).fetchall()
    c.close()
    return {"rows": [dict(r) for r in rows]}


@app.get("/api/channels/{kind}/suggestions")
async def channel_suggestions(kind: str, request: Request):
    """القنوات الافتراضية التي لم يُضفها المستخدم بعد."""
    u = require_auth(request)
    if kind not in ("kick", "yt", "tg"):
        raise HTTPException(404)
    table = {"kick": "kick_channels", "yt": "yt_channels", "tg": "tg_channels"}[kind]
    ident_col = {"kick": "slug", "yt": "channel_id", "tg": "chat_id"}[kind]
    c = db()
    defaults = c.execute(
        "SELECT * FROM default_channels WHERE kind=? AND enabled=1 ORDER BY id DESC",
        (kind,),
    ).fetchall()
    mine = set(
        r[ident_col] for r in c.execute(
            f"SELECT {ident_col} FROM {table} WHERE added_by=?", (u["username"],)
        ).fetchall()
    )
    c.close()
    out = [dict(r) for r in defaults if r["identifier"] not in mine]
    return {"rows": out}


@app.post("/api/channels/{kind}")
async def add_channel(kind: str, request: Request):
    u = require_auth(request)
    if not rate_ok(f"add:{u['username']}", MAX_PER_MIN_CH):
        raise HTTPException(429, "عدد كبير من الإضافات، انتظر قليلاً")
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
    """يستقبل IDs القنوات الافتراضية المختارة ويضيفها دفعة واحدة."""
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

    c = db()
    rows = c.execute(
        f"SELECT * FROM default_channels WHERE id IN ({','.join('?' * len(ids))}) "
        f"AND kind=? AND enabled=1",
        (*ids, kind)
    ).fetchall()
    c.close()
    if not rows:
        return JSONResponse({"error": "لا توجد قنوات"}, 404)

    added = 0
    failed = 0
    errors = []

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
                     row["name"] or row["identifier"], row["avatar"] or "",
                     u["username"], t),
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
    if "msg" in body:
        sets.append("msg=?")
        vals.append(str(body["msg"])[:1500])
    if "name" in body:
        sets.append("name=?")
        vals.append(str(body["name"])[:80])
    if sets:
        vals.append(cid)
        c.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?", vals)
        c.commit()
    c.close()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════
#                 API — DISCORD FEEDS
# ═══════════════════════════════════════════════════════════
@app.get("/api/discord/feeds")
async def list_feeds(request: Request):
    u = require_auth(request)
    c = db()
    rows = c.execute(
        "SELECT * FROM discord_feeds WHERE added_by=? ORDER BY id DESC",
        (u["username"],)
    ).fetchall()
    c.close()
    known = {}
    if discord_client.is_ready():
        for g in discord_client.guilds:
            if ALLOWED_GUILDS and str(g.id) not in ALLOWED_GUILDS:
                continue
            for ch in g.text_channels:
                known[str(ch.id)] = {"name": ch.name, "guild": g.name}
    return {
        "rows": [dict(r) for r in rows],
        "known_channels": known,
        "watching": WATCH_CHANNELS,
    }


@app.post("/api/discord/feeds")
async def add_feed(request: Request):
    u = require_auth(request)
    body = await request.json()
    ch = str(body.get("channel_id") or "").strip()
    if not ch or not ch.isdigit():
        return JSONResponse({"error": "channel_id يجب أن يكون رقماً"}, 400)
    if ch not in WATCH_CHANNELS:
        return JSONResponse({"error": "هذا الروم غير مُراقب — راجع DISCORD_WATCH_CHANNELS"}, 400)
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
    if "template" in body:
        sets.append("template=?")
        vals.append(str(body["template"])[:2000])
    if "enabled" in body:
        sets.append("enabled=?")
        vals.append(1 if body["enabled"] else 0)
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
#                 API — NOTIFICATIONS
# ═══════════════════════════════════════════════════════════
@app.get("/api/notifs")
async def notifs(request: Request):
    u = require_auth(request)
    c = db()
    unread = c.execute(
        "SELECT COUNT(*) n FROM notifs WHERE username=? AND is_read=0",
        (u["username"],)
    ).fetchone()["n"]
    if request.query_params.get("count"):
        c.close()
        return {"unread": unread}
    rows = c.execute(
        "SELECT * FROM notifs WHERE username=? ORDER BY ts DESC LIMIT 50",
        (u["username"],)
    ).fetchall()
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
#                 API — SETTINGS (owner)
# ═══════════════════════════════════════════════════════════
@app.get("/api/settings")
async def get_settings(request: Request):
    u = require_auth(request)
    keys = ["site_name", "site_sub", "hero_title", "hero_accent", "hero_text",
            "tpl_kick", "tpl_yt", "tpl_discord", "tpl_twitter", "tpl_youtube_dc",
            "btn_kick", "btn_yt", "lim_kick", "lim_yt", "lim_tg",
            "guest_mode", "guest_blur"]
    return {k: cfg(k) for k in keys}


@app.post("/api/settings")
async def save_settings(request: Request):
    u = require_auth(request)
    if u["role"] != "owner":
        raise HTTPException(403)
    body = await request.json()
    allowed = ["site_name", "site_sub", "hero_title", "hero_accent", "hero_text",
               "tpl_kick", "tpl_yt", "tpl_discord", "tpl_twitter", "tpl_youtube_dc",
               "btn_kick", "btn_yt", "lim_kick", "lim_yt", "lim_tg",
               "guest_mode", "guest_blur"]
    for k in allowed:
        if k in body:
            set_cfg(k, str(body[k])[:2000])
    return {"ok": True}


# ═══════════════════════════════════════════════════════════
#          API — DEFAULT CHANNELS (owner manages)
# ═══════════════════════════════════════════════════════════
@app.get("/api/admin/default-channels")
async def list_default_channels(request: Request):
    u = require_auth(request)
    if u["role"] != "owner":
        raise HTTPException(403)
    kind = request.query_params.get("kind")
    c = db()
    if kind in ("kick", "yt", "tg"):
        rows = c.execute(
            "SELECT * FROM default_channels WHERE kind=? ORDER BY id DESC", (kind,)
        ).fetchall()
    else:
        rows = c.execute("SELECT * FROM default_channels ORDER BY kind, id DESC").fetchall()
    c.close()
    return {"rows": [dict(r) for r in rows]}


@app.post("/api/admin/default-channels")
async def add_default_channel(request: Request):
    u = require_auth(request)
    if u["role"] != "owner":
        raise HTTPException(403)
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
        name = body.get("name") or ident
        avatar = ""

    c = db()
    if c.execute("SELECT 1 FROM default_channels WHERE kind=? AND identifier=?",
                 (kind, ident)).fetchone():
        c.close()
        return JSONResponse({"error": "موجودة مسبقاً"}, 409)
    c.execute(
        "INSERT INTO default_channels(kind,identifier,name,avatar,enabled,created) "
        "VALUES(?,?,?,?,1,?)",
        (kind, ident, name, avatar, now()),
    )
    c.commit()
    c.close()
    return {"ok": True}


@app.delete("/api/admin/default-channels/{cid}")
async def del_default_channel(cid: int, request: Request):
    u = require_auth(request)
    if u["role"] != "owner":
        raise HTTPException(403)
    c = db()
    c.execute("DELETE FROM default_channels WHERE id=?", (cid,))
    c.commit()
    c.close()
    return {"ok": True}


@app.patch("/api/admin/default-channels/{cid}")
async def patch_default_channel(cid: int, request: Request):
    u = require_auth(request)
    if u["role"] != "owner":
        raise HTTPException(403)
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
#                 API — ADMIN USERS
# ═══════════════════════════════════════════════════════════
@app.get("/api/admin/users")
async def admin_users(request: Request):
    u = require_auth(request)
    if u["role"] != "owner":
        raise HTTPException(403)
    c = db()
    rows = c.execute(
        "SELECT id, username, display, role, active, banned, lim_kick, lim_yt, lim_tg, "
        "created, last_login FROM users ORDER BY id"
    ).fetchall()
    c.close()
    return {"rows": [dict(r) for r in rows]}


@app.post("/api/admin/users")
async def admin_add_user(request: Request):
    u = require_auth(request)
    if u["role"] != "owner":
        raise HTTPException(403)
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
    u = require_auth(request)
    if u["role"] != "owner":
        raise HTTPException(403)
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
    u = require_auth(request)
    if u["role"] != "owner":
        raise HTTPException(403)
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
    for t in ("notifs", "sessions"):
        c.execute(f"DELETE FROM {t} WHERE username=?", (uname,))
    c.execute("DELETE FROM users WHERE id=?", (uid,))
    c.commit()
    c.close()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════
#                    ROOT PAGE
# ═══════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def index():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>index.html غير موجود</h1>", status_code=500)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "discord_ready": discord_client.is_ready() if discord_client else False,
        "watching": len(WATCH_CHANNELS),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
    <!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#030508">
<title>Respect Live</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%230b55ea'%3E%3Cpath d='M11.35 2.76a1 1 0 0 1 1.3 0l9 7.5a1 1 0 0 1 .35.74V20a2 2 0 0 1-2 2h-4.5a1 1 0 0 1-1-1v-4h-3v4a1 1 0 0 1-1 1H5a2 2 0 0 1-2-2v-8.99a1 1 0 0 1 .35-.75l8-7.5z'/%3E%3C/svg%3E">
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Tajawal:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
/* ═══════════════════════════════════════════════════════
   ROOT VARIABLES — TEAM SOL style
   ═══════════════════════════════════════════════════════ */
:root{
  --blue:#0b55ea;--blue2:#1b67ff;--blue-rgb:11,85,234;
  --bg:#030508;--panel:#0a0f18;--card:linear-gradient(145deg,#0c1119,#040609);
  --text:#f4f6fa;--muted:#7c8799;
  --line:rgba(255,255,255,.08);--line-2:rgba(11,85,234,.22);
  --green:#10b981;--red:#ef4444;--gold:#f5b400;--orange:#f59e0b;--purple:#8b5cf6;
  --glow:0 0 30px rgba(var(--blue-rgb),.35);
  --font-ar:'Tajawal',system-ui,sans-serif;
  --font-en:'Orbitron',sans-serif;
  --ease:cubic-bezier(.16,1,.3,1);
  --ease-soft:cubic-bezier(.22,.61,.36,1);
  --radius:18px;--radius-sm:12px;
  --pad:6%;
}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent;outline:none}
html{scroll-behavior:smooth;background:var(--bg)}
body{
  background:var(--bg);color:var(--text);
  font-family:var(--font-ar);font-size:15px;line-height:1.75;
  min-height:100vh;overflow-x:hidden;padding-bottom:calc(110px + env(safe-area-inset-bottom));
  -webkit-font-smoothing:antialiased;position:relative;
}
/* خلفية بنقشة هندسية */
body::before{
  content:"";position:fixed;inset:0;z-index:-3;pointer-events:none;
  background-image:
    linear-gradient(rgba(var(--blue-rgb),.04) 1px,transparent 1px),
    linear-gradient(90deg,rgba(var(--blue-rgb),.04) 1px,transparent 1px);
  background-size:62px 62px;
  -webkit-mask-image:radial-gradient(ellipse 90% 80% at 50% 40%,#000 30%,transparent 90%);
  mask-image:radial-gradient(ellipse 90% 80% at 50% 40%,#000 30%,transparent 90%);
}
/* توهجات خلفية */
body::after{
  content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;
  background:
    radial-gradient(circle at 12% 18%,rgba(var(--blue-rgb),.10),transparent 42%),
    radial-gradient(circle at 88% 65%,rgba(var(--blue-rgb),.09),transparent 45%),
    radial-gradient(circle at 50% 100%,rgba(var(--blue-rgb),.06),transparent 55%);
}
a{color:inherit;text-decoration:none}
button{font:inherit;cursor:pointer;border:none;background:none;color:inherit}
input,textarea,select{font:inherit}
img{display:block;max-width:100%}
.hidden{display:none!important}

/* ═══════════════════════════════════════════════════════
   SPLASH SCREEN
   ═══════════════════════════════════════════════════════ */
#splash{
  position:fixed;inset:0;z-index:9000;display:grid;place-items:center;text-align:center;
  background:radial-gradient(circle at 50% 40%,rgba(var(--blue-rgb),.18),transparent 60%),var(--bg);
  transition:opacity .75s var(--ease),transform .75s var(--ease);
}
#splash.out{opacity:0;transform:scale(1.06);pointer-events:none}
.sp-wrap{display:flex;flex-direction:column;align-items:center;gap:26px}
.sp-logo{
  width:104px;height:104px;border-radius:26px;
  background:linear-gradient(135deg,var(--blue),var(--blue2));
  display:grid;place-items:center;color:#fff;
  box-shadow:0 0 0 0 rgba(var(--blue-rgb),.6),0 20px 60px rgba(var(--blue-rgb),.5);
  animation:spGlow 2.4s ease-in-out infinite;
}
.sp-logo svg{width:52px;height:52px}
@keyframes spGlow{
  0%,100%{box-shadow:0 0 0 0 rgba(var(--blue-rgb),.6),0 20px 60px rgba(var(--blue-rgb),.45)}
  50%{box-shadow:0 0 0 26px rgba(var(--blue-rgb),0),0 20px 60px rgba(var(--blue-rgb),.6)}
}
.sp-dots{display:flex;gap:9px}
.sp-dots i{
  width:10px;height:10px;border-radius:50%;background:var(--blue);
  animation:spBounce 1.5s ease-in-out infinite;
  box-shadow:0 0 12px rgba(var(--blue-rgb),.6);
}
.sp-dots i:nth-child(2){animation-delay:.18s}
.sp-dots i:nth-child(3){animation-delay:.36s}
@keyframes spBounce{0%,80%,100%{transform:scale(.35);opacity:.35}40%{transform:scale(1);opacity:1}}
.sp-foot{
  font-family:var(--font-en);font-size:11px;letter-spacing:4px;font-weight:800;
  color:var(--muted);opacity:0;animation:fadeIn .8s .9s forwards;
}

/* ═══════════════════════════════════════════════════════
   APP LAYOUT
   ═══════════════════════════════════════════════════════ */
.page{display:none;animation:pageIn .42s var(--ease) both}
.page.on{display:block}
@keyframes pageIn{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
@keyframes fadeIn{to{opacity:1}}

/* ---------- Header ---------- */
.top{
  position:sticky;top:0;z-index:50;
  padding:calc(14px + env(safe-area-inset-top)) var(--pad) 14px;
  display:flex;align-items:center;gap:12px;
  background:linear-gradient(rgba(3,5,8,.94) 60%,transparent);
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  border-bottom:1px solid transparent;transition:border-color .3s ease,background .3s ease;
}
.top.scrolled{border-bottom-color:var(--line);background:linear-gradient(rgba(3,5,8,.98) 80%,transparent)}
.brand{display:flex;align-items:center;gap:11px;flex:1;min-width:0}
.brand-logo{
  width:42px;height:42px;border-radius:12px;
  background:linear-gradient(135deg,var(--blue),var(--blue2));
  display:grid;place-items:center;flex-shrink:0;
  box-shadow:0 0 15px rgba(var(--blue-rgb),.4);
}
.brand-logo svg{width:22px;height:22px;color:#fff}
.brand-txt{min-width:0}
.brand-name{font-family:var(--font-en);font-size:15px;font-weight:900;letter-spacing:2px;line-height:1.1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.brand-name span{color:var(--blue);text-shadow:var(--glow)}
.brand-sub{font-family:var(--font-en);font-size:9px;font-weight:800;letter-spacing:2px;color:var(--muted);margin-top:2px}
.hdr-acts{display:flex;align-items:center;gap:8px}
.hdr-btn{
  position:relative;width:42px;height:42px;border-radius:12px;
  display:grid;place-items:center;
  background:rgba(255,255,255,.03);border:1px solid var(--line);
  color:var(--text);transition:.22s var(--ease-soft);
}
.hdr-btn:hover{border-color:var(--blue);transform:translateY(-1px)}
.hdr-btn svg{width:19px;height:19px}
.hdr-btn .badge{
  position:absolute;top:-5px;right:-5px;min-width:18px;height:18px;padding:0 5px;
  border-radius:9px;background:var(--red);color:#fff;
  font-size:10px;font-weight:900;display:grid;place-items:center;
  border:2px solid var(--bg);font-family:var(--font-en);line-height:1;
}
.avatar-btn{
  width:42px;height:42px;border-radius:50%;
  background:linear-gradient(135deg,var(--blue),var(--blue2));
  display:grid;place-items:center;color:#fff;
  font-family:var(--font-en);font-weight:900;font-size:15px;
  cursor:pointer;position:relative;flex-shrink:0;
  box-shadow:0 0 15px rgba(var(--blue-rgb),.4);
  transition:.22s var(--ease-soft);
}
.avatar-btn:hover{transform:scale(1.06)}
.avatar-btn .st{position:absolute;bottom:0;right:0;width:11px;height:11px;border-radius:50%;background:var(--green);border:2px solid var(--bg)}
.avatar-btn.guest{background:rgba(255,255,255,.06);border:1px solid var(--line);color:var(--muted);box-shadow:none}

/* ---------- Bottom tab bar ---------- */
.tabbar{
  position:fixed;bottom:calc(18px + env(safe-area-inset-bottom));
  left:50%;transform:translateX(-50%);
  width:92%;max-width:460px;height:64px;
  background:rgba(10,15,24,.94);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);
  border:1px solid var(--line);border-radius:34px;
  display:flex;justify-content:space-around;align-items:center;
  z-index:100;padding:0 10px;
  box-shadow:0 20px 40px rgba(0,0,0,.6),inset 0 1px 1px rgba(255,255,255,.05);
}
.tabbar button{
  width:52px;height:52px;border-radius:50%;
  display:grid;place-items:center;
  color:var(--muted);position:relative;
  transition:.28s var(--ease-soft);
}
.tabbar button svg{width:22px;height:22px;color:currentColor;transition:.28s var(--ease-soft)}
.tabbar button:hover{color:var(--text);background:rgba(255,255,255,.04)}
.tabbar button.on{color:var(--blue2)}
.tabbar button.on svg{transform:translateY(-2px) scale(1.15);filter:drop-shadow(0 0 8px var(--blue))}
.tabbar button.on::after{
  content:"";position:absolute;bottom:-2px;left:50%;transform:translateX(-50%);
  width:20px;height:3px;background:var(--blue);border-radius:3px;box-shadow:var(--glow);
}

/* ---------- Hero ---------- */
.hero{
  padding:36px var(--pad) 30px;text-align:center;
  position:relative;animation:pageIn .5s var(--ease) both;
}
.hero-lbl{
  font-family:var(--font-en);font-size:11px;font-weight:900;letter-spacing:3.5px;
  color:var(--muted);display:flex;align-items:center;justify-content:center;gap:8px;
}
.hero-lbl span{color:var(--blue);font-size:14px;text-shadow:var(--glow)}
.hero h1{
  font-family:var(--font-en);font-size:clamp(34px,8vw,60px);
  line-height:.92;letter-spacing:4px;font-weight:900;margin:20px 0 12px;
}
.hero h1 span{color:var(--blue);display:inline-block;transform:skewX(-8deg);text-shadow:var(--glow)}
.hero p{color:var(--muted);font-size:13.5px;max-width:520px;margin:0 auto;line-height:1.85;font-weight:500}

/* ---------- Stats strip ---------- */
.stats{
  display:grid;grid-template-columns:repeat(4,1fr);
  gap:1px;background:var(--line);border:1px solid var(--line);
  border-radius:16px;overflow:hidden;margin:22px var(--pad);
}
.stats .s{background:var(--panel);padding:16px 8px;text-align:center;transition:.24s var(--ease-soft)}
.stats .s:hover{background:rgba(var(--blue-rgb),.05)}
.stats .s b{display:block;font-family:var(--font-en);font-size:24px;font-weight:900;line-height:1;color:var(--text)}
.stats .s b.blue{color:var(--blue);text-shadow:var(--glow)}
.stats .s small{display:block;font-family:var(--font-en);font-size:10px;font-weight:800;color:var(--muted);margin-top:5px;letter-spacing:1.5px}
@media(max-width:520px){.stats{grid-template-columns:repeat(2,1fr)}}

/* ---------- Tabs (chips) ---------- */
.chips{
  display:flex;gap:8px;padding:20px var(--pad) 4px;
  overflow-x:auto;scrollbar-width:none;
}
.chips::-webkit-scrollbar{display:none}
.chip{
  flex-shrink:0;padding:10px 16px;border-radius:22px;
  background:rgba(255,255,255,.04);border:1px solid var(--line);
  color:var(--muted);font-size:12.5px;font-weight:800;
  display:inline-flex;align-items:center;gap:7px;
  transition:.24s var(--ease-soft);
}
.chip:hover{color:var(--text);border-color:var(--blue);transform:translateY(-1px)}
.chip.on{
  background:var(--blue);color:#fff;border-color:var(--blue);
  box-shadow:0 6px 18px rgba(var(--blue-rgb),.4);
}
.chip .cnt{
  background:rgba(255,255,255,.16);border-radius:10px;padding:0 7px;
  font-family:var(--font-en);font-size:10.5px;font-weight:900;
  min-width:20px;line-height:18px;text-align:center;
}
.chip.on .cnt{background:rgba(0,0,0,.28)}

/* ---------- Sections ---------- */
.sec{padding:22px var(--pad);animation:pageIn .42s var(--ease) both}
.sec-h{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;gap:12px;flex-wrap:wrap}
.sec-title{font-size:20px;font-weight:900}
.sec-title span{color:var(--blue);transform:skewX(-8deg);display:inline-block}

/* ---------- Channel cards ---------- */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
@media(max-width:640px){.grid{grid-template-columns:1fr}}
.ch{
  background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  overflow:hidden;position:relative;
  transition:transform .32s var(--ease-soft),border-color .32s ease,box-shadow .32s ease;
}
.ch::before{content:"";position:absolute;top:9px;left:9px;width:12px;height:12px;border-top:2px solid var(--blue);border-left:2px solid var(--blue);opacity:.4;pointer-events:none;border-radius:3px 0 0 0}
.ch:hover{transform:translateY(-3px);border-color:var(--line-2);box-shadow:0 15px 40px rgba(var(--blue-rgb),.16)}
.ch-cover{height:112px;position:relative;overflow:hidden;background:linear-gradient(135deg,rgba(var(--blue-rgb),.28),rgba(0,0,0,.5))}
.ch-cover img{width:100%;height:100%;object-fit:cover;transition:transform .5s var(--ease-soft)}
.ch:hover .ch-cover img{transform:scale(1.05)}
.ch-cover::after{content:"";position:absolute;inset:0;background:linear-gradient(transparent 40%,rgba(3,5,8,.9))}
.ch-badge{
  position:absolute;top:10px;right:10px;z-index:3;
  font-size:10.5px;padding:5px 10px;border-radius:8px;
  font-weight:900;font-family:var(--font-en);letter-spacing:.5px;
  display:inline-flex;align-items:center;gap:5px;
}
.ch-badge.live{background:var(--red);color:#fff;animation:chPulse 1.9s infinite}
.ch-badge.live::before{content:"";width:6px;height:6px;border-radius:50%;background:#fff}
.ch-badge.off{background:rgba(255,255,255,.15);color:var(--text);backdrop-filter:blur(6px)}
@keyframes chPulse{70%{box-shadow:0 0 0 12px rgba(239,68,68,0)}100%{box-shadow:0 0 0 0 rgba(239,68,68,0)}}
.ch-head{display:flex;align-items:flex-end;gap:12px;padding:0 16px;margin-top:-26px;position:relative;z-index:2}
.ch-head img{width:54px;height:54px;border-radius:14px;object-fit:cover;border:3px solid var(--bg);background:var(--panel);flex-shrink:0;box-shadow:0 0 15px rgba(var(--blue-rgb),.35)}
.ch-head .ph{width:54px;height:54px;border-radius:14px;background:linear-gradient(135deg,var(--blue),var(--blue2));display:grid;place-items:center;border:3px solid var(--bg);flex-shrink:0;color:#fff}
.ch-head .ph svg{width:24px;height:24px}
.ch-info{flex:1;min-width:0;padding-bottom:2px}
.ch-info b{display:block;font-size:15.5px;font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text)}
.ch-info small{display:inline-block;font-size:10.5px;color:var(--muted);font-family:var(--font-en);letter-spacing:1px;border:1px solid var(--line);border-radius:20px;padding:2px 10px;margin-top:3px}
.ch-live{margin:10px 16px 0;padding:10px 14px;border-radius:10px;background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.3);font-size:12px;display:flex;justify-content:space-between;gap:10px;font-weight:700}
.ch-live span{color:#f87171;white-space:nowrap;font-family:var(--font-en)}
.ch-note{padding:0 16px;font-size:12.5px;color:var(--muted);margin:8px 0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.ch-acts{display:flex;gap:7px;flex-wrap:wrap;padding:14px 16px 16px}

/* ---------- Buttons ---------- */
.btn{
  display:inline-flex;align-items:center;justify-content:center;gap:7px;
  padding:11px 18px;border-radius:var(--radius-sm);
  background:rgba(255,255,255,.04);border:1px solid var(--line);color:var(--text);
  font-size:13px;font-weight:800;
  transition:.24s var(--ease-soft);cursor:pointer;white-space:nowrap;
  font-family:inherit;position:relative;overflow:hidden;
}
.btn:hover{transform:translateY(-1px);border-color:var(--blue)}
.btn:active{transform:scale(.97)}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none!important}
.btn.pri{background:var(--blue);border-color:var(--blue);color:#fff;box-shadow:0 10px 26px rgba(var(--blue-rgb),.28)}
.btn.pri:hover{box-shadow:0 14px 36px rgba(var(--blue-rgb),.45)}
.btn.danger{background:var(--red);border-color:var(--red);color:#fff}
.btn.ghost{background:transparent}
.btn.sm{padding:8px 13px;font-size:11.5px;border-radius:10px}
.btn.wide{width:100%;padding:13px}
.btn svg{width:14px;height:14px;flex-shrink:0}

/* ---------- Empty state ---------- */
.empty{text-align:center;padding:56px 20px}
.empty .em-icon{width:96px;height:96px;margin:0 auto 16px;color:var(--blue);opacity:.35}
.empty .em-icon svg{width:100%;height:100%}
.empty h3{font-size:16px;font-weight:900;color:var(--text);margin-bottom:6px}
.empty p{font-size:13px;color:var(--muted);margin-bottom:18px}

/* ---------- Guest lock overlay ---------- */
.locked{position:relative}
.locked .lock-blur{
  filter:blur(14px) saturate(.7);pointer-events:none;user-select:none;
  transition:filter .3s ease;
}
.lock-cover{
  position:absolute;inset:0;z-index:5;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  text-align:center;padding:22px;
  background:linear-gradient(180deg,rgba(3,5,8,.15),rgba(3,5,8,.7));
  backdrop-filter:blur(2px);border-radius:var(--radius);
}
.lock-cover .lc-icon{
  width:64px;height:64px;border-radius:20px;
  background:linear-gradient(135deg,var(--blue),var(--blue2));
  display:grid;place-items:center;color:#fff;margin-bottom:14px;
  box-shadow:0 12px 34px rgba(var(--blue-rgb),.45);
  animation:lcFloat 3.4s ease-in-out infinite;
}
.lock-cover .lc-icon svg{width:30px;height:30px}
@keyframes lcFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}
.lock-cover h3{font-size:16px;font-weight:900;margin-bottom:6px}
.lock-cover p{font-size:12.5px;color:var(--muted);margin-bottom:16px;max-width:280px;line-height:1.7}

/* ---------- Guest banner ---------- */
.guest-banner{
  margin:18px var(--pad);
  padding:14px 18px;border-radius:14px;
  background:linear-gradient(135deg,rgba(var(--blue-rgb),.12),rgba(var(--blue-rgb),.02));
  border:1px solid rgba(var(--blue-rgb),.3);
  display:flex;align-items:center;gap:14px;flex-wrap:wrap;
  animation:pageIn .5s var(--ease) both;
}
.guest-banner .gb-ico{
  width:44px;height:44px;border-radius:12px;
  background:rgba(var(--blue-rgb),.15);border:1px solid rgba(var(--blue-rgb),.4);
  display:grid;place-items:center;color:var(--blue);flex-shrink:0;
}
.guest-banner .gb-ico svg{width:22px;height:22px}
.guest-banner .gb-txt{flex:1;min-width:160px;font-size:13px;font-weight:700;color:var(--text);line-height:1.6}
.guest-banner .gb-txt small{display:block;font-weight:500;color:var(--muted);font-size:11.5px;margin-top:2px}

/* ---------- Modal / Sheet ---------- */
.modal{
  position:fixed;inset:0;z-index:1200;
  background:rgba(3,5,8,.78);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
  display:flex;align-items:flex-end;justify-content:center;padding-top:44px;
  opacity:0;pointer-events:none;transition:opacity .28s ease;
}
.modal.on{opacity:1;pointer-events:auto}
.sheet{
  width:min(680px,100%);max-height:92vh;overflow-y:auto;
  background:var(--card);border:1px solid var(--line);border-bottom:0;
  border-radius:26px 26px 0 0;
  padding:16px 22px calc(26px + env(safe-area-inset-bottom));
  transform:translateY(70px);
  transition:transform .38s var(--ease-soft);
  position:relative;box-shadow:0 -20px 60px rgba(0,0,0,.55),0 0 60px rgba(var(--blue-rgb),.15);
}
.modal.on .sheet{transform:translateY(0)}
.sheet::before{content:"";position:absolute;top:0;left:20%;right:20%;height:2px;background:linear-gradient(90deg,transparent,var(--blue),transparent);box-shadow:var(--glow);border-radius:2px}
.sheet.sm{width:min(460px,100%)}
.sheet.wide{width:min(820px,100%)}
.grab{width:44px;height:4px;border-radius:9px;background:rgba(255,255,255,.22);margin:0 auto 18px}
@media(min-width:701px){.modal{align-items:center}.sheet{border-radius:22px;border-bottom:1px solid var(--line)}}
.sh-title{font-family:var(--font-en);font-size:16px;font-weight:900;letter-spacing:1px;margin-bottom:6px}
.sh-sub{color:var(--muted);font-size:12.5px;margin-bottom:16px;line-height:1.7}

/* ---------- Form fields ---------- */
.fld{display:block;margin:14px 0}
.fld>span{display:block;font-size:12.5px;color:var(--muted);margin-bottom:8px;font-weight:800;letter-spacing:.3px}
input[type=text],input[type=password],input[type=number],input[type=email],textarea,select{
  width:100%;font:inherit;font-size:14px;color:var(--text);
  background:rgba(5,8,16,.75);border:1px solid rgba(var(--blue-rgb),.25);
  border-radius:var(--radius-sm);padding:12px 14px;
  transition:.24s var(--ease-soft);font-weight:600;
}
input:focus,textarea:focus,select:focus{
  border-color:var(--blue);
  box-shadow:0 0 0 3px rgba(var(--blue-rgb),.16),0 0 18px rgba(var(--blue-rgb),.18);
}
textarea{resize:vertical;min-height:100px;line-height:1.7;font-family:inherit}
select option{background:var(--panel);color:var(--text)}
.row{display:flex;gap:10px;margin-top:18px}
.row>.btn{flex:1}
.err{color:#f87171;font-size:12.5px;text-align:center;min-height:18px;margin-top:10px}

/* ---------- Toasts ---------- */
.toasts{
  position:fixed;top:calc(14px + env(safe-area-inset-top));left:0;right:0;z-index:9000;
  display:flex;flex-direction:column;align-items:center;gap:8px;
  pointer-events:none;width:100%;padding:0 14px;
}
.toast{
  max-width:min(440px,100%);padding:13px 20px;border-radius:14px;
  font-size:13px;font-weight:800;
  background:var(--card);border:1px solid var(--line);
  backdrop-filter:blur(14px);
  box-shadow:0 15px 40px rgba(0,0,0,.5),0 0 30px rgba(var(--blue-rgb),.15);
  opacity:0;transform:translateY(-16px);
  transition:.32s var(--ease-soft);
  position:relative;overflow:hidden;
  text-align:center;color:var(--text);
  display:flex;align-items:center;gap:10px;justify-content:center;
}
.toast::before{content:"";position:absolute;top:0;bottom:0;right:0;width:4px;background:var(--blue)}
.toast.ok::before{background:var(--green)}
.toast.bad::before{background:var(--red)}
.toast.on{opacity:1;transform:translateY(0)}

/* ---------- Auth page ---------- */
.login-wrap{
  min-height:100vh;display:grid;place-items:center;padding:20px;
  animation:pageIn .55s var(--ease) both;
}
.login-card{
  width:min(440px,100%);
  padding:36px 28px;
  background:var(--card);border:1px solid var(--line);
  border-radius:22px;position:relative;
  box-shadow:0 30px 60px rgba(0,0,0,.55),0 0 60px rgba(var(--blue-rgb),.12);
}
.login-card::before{content:"";position:absolute;top:0;left:20%;right:20%;height:2px;background:linear-gradient(90deg,transparent,var(--blue),transparent);box-shadow:var(--glow);border-radius:2px}
.login-logo{
  width:88px;height:88px;border-radius:24px;margin:0 auto 16px;
  background:linear-gradient(135deg,var(--blue),var(--blue2));
  display:grid;place-items:center;color:#fff;
  box-shadow:0 0 0 0 rgba(var(--blue-rgb),.6),0 20px 60px rgba(var(--blue-rgb),.45);
  animation:spGlow 2.4s infinite;
}
.login-logo svg{width:44px;height:44px}
.login-head{text-align:center;margin-bottom:22px}
.login-head h1{font-family:var(--font-en);font-size:20px;letter-spacing:3px;font-weight:900;margin-bottom:6px}
.login-head h1 span{color:var(--blue);text-shadow:var(--glow)}
.login-head p{color:var(--muted);font-size:12.5px}
.tabs2{display:flex;gap:6px;margin-bottom:18px;background:rgba(5,8,16,.75);border:1px solid var(--line);padding:5px;border-radius:12px}
.tabs2 button{
  flex:1;padding:10px;border-radius:9px;
  font-size:12.5px;font-weight:800;color:var(--muted);
  transition:.22s var(--ease-soft);background:transparent;
}
.tabs2 button.on{background:var(--blue);color:#fff;box-shadow:0 6px 14px rgba(var(--blue-rgb),.35)}
.skip-row{margin-top:20px;padding-top:16px;border-top:1px solid var(--line);text-align:center}
.skip-row button{
  display:inline-flex;align-items:center;gap:7px;
  padding:10px 18px;border-radius:22px;
  background:transparent;border:1px dashed var(--line);
  color:var(--muted);font-weight:800;font-size:12.5px;
  transition:.22s var(--ease-soft);
}
.skip-row button:hover{color:var(--blue);border-color:var(--blue)}

/* ---------- Notification rows ---------- */
.notif{
  display:flex;gap:12px;padding:14px;border-radius:14px;margin:10px 0;
  background:var(--panel);border:1px solid var(--line);
  transition:.22s var(--ease-soft);cursor:pointer;
}
.notif:hover{border-color:var(--blue)}
.notif.un{background:rgba(var(--blue-rgb),.08);border-color:rgba(var(--blue-rgb),.3);box-shadow:0 0 20px rgba(var(--blue-rgb),.1)}
.notif img{width:52px;height:52px;border-radius:12px;object-fit:cover;flex-shrink:0;background:var(--panel);border:1px solid var(--line)}
.notif .nt-b{flex:1;min-width:0}
.notif b{display:block;font-size:13.5px;font-weight:900;margin-bottom:3px}
.notif p{font-size:12.5px;color:var(--muted);white-space:pre-wrap;line-height:1.65;margin-top:2px}
.notif .nt-t{font-size:10.5px;color:var(--muted);font-family:var(--font-en);letter-spacing:1px;margin-top:6px}

/* ---------- Suggestion picker ---------- */
.sug-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin-top:10px}
.sug-item{
  display:flex;align-items:center;gap:10px;
  padding:11px 12px;border-radius:12px;
  background:rgba(255,255,255,.03);border:1px solid var(--line);
  cursor:pointer;transition:.22s var(--ease-soft);
}
.sug-item:hover{border-color:var(--blue);background:rgba(var(--blue-rgb),.06)}
.sug-item.on{border-color:var(--blue);background:rgba(var(--blue-rgb),.1);box-shadow:0 4px 14px rgba(var(--blue-rgb),.2)}
.sug-item .av{
  width:38px;height:38px;border-radius:10px;
  background:rgba(var(--blue-rgb),.15);border:1px solid rgba(var(--blue-rgb),.35);
  display:grid;place-items:center;color:var(--blue);flex-shrink:0;
  font-weight:900;font-family:var(--font-en);font-size:14px;
  overflow:hidden;
}
.sug-item .av img{width:100%;height:100%;object-fit:cover}
.sug-item .if{flex:1;min-width:0}
.sug-item .if b{display:block;font-size:13px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sug-item .if small{display:block;font-size:10.5px;color:var(--muted);font-family:var(--font-en);letter-spacing:.5px;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sug-item .ck{
  width:22px;height:22px;border-radius:6px;flex-shrink:0;
  border:2px solid var(--line);display:grid;place-items:center;
  color:transparent;transition:.2s var(--ease-soft);
}
.sug-item.on .ck{background:var(--blue);border-color:var(--blue);color:#fff}
.sug-item .ck svg{width:13px;height:13px}
.sug-toolbar{
  display:flex;justify-content:space-between;align-items:center;
  padding:10px 12px;margin-top:10px;border-radius:12px;
  background:rgba(var(--blue-rgb),.06);border:1px solid rgba(var(--blue-rgb),.2);
  font-size:12.5px;font-weight:800;
}
.sug-toolbar button{
  padding:6px 12px;border-radius:16px;
  background:transparent;border:1px dashed rgba(var(--blue-rgb),.5);
  color:var(--blue);font-size:11.5px;font-weight:900;
  transition:.2s var(--ease-soft);
}
.sug-toolbar button:hover{background:rgba(var(--blue-rgb),.1)}

/* ---------- Account menu ---------- */
.acc-menu{
  position:fixed;top:calc(70px + env(safe-area-inset-top));left:var(--pad);
  min-width:290px;max-width:calc(100vw - 2*var(--pad));
  background:var(--card);border:1px solid var(--line-2);border-radius:18px;
  box-shadow:0 30px 60px rgba(0,0,0,.6),0 0 60px rgba(var(--blue-rgb),.15);
  padding:8px;z-index:1500;
  opacity:0;transform:translateY(-12px) scale(.96);
  transition:.26s var(--ease-soft);pointer-events:none;
}
.acc-menu.on{opacity:1;transform:translateY(0) scale(1);pointer-events:auto}
.acc-head{padding:14px 14px 12px;border-bottom:1px solid var(--line);margin-bottom:6px}
.acc-head .nm{font-size:15px;font-weight:900;margin-bottom:3px}
.acc-head .mt{font-size:11.5px;color:var(--muted);font-family:var(--font-en);letter-spacing:1px}
.acc-head .stats-mini{display:flex;gap:14px;margin-top:10px}
.acc-head .stats-mini span{font-size:11px;color:var(--muted);font-weight:700;display:flex;align-items:center;gap:5px}
.acc-head .stats-mini b{color:var(--blue);font-family:var(--font-en);font-weight:900;font-size:13px}
.acc-item{
  display:flex;align-items:center;gap:11px;
  padding:11px 14px;border-radius:11px;
  font-size:13px;font-weight:800;color:var(--text);
  transition:.2s var(--ease-soft);cursor:pointer;
  width:100%;text-align:right;background:transparent;
}
.acc-item:hover{background:rgba(var(--blue-rgb),.08);color:var(--blue)}
.acc-item.danger{color:var(--red)}
.acc-item.danger:hover{background:rgba(239,68,68,.1);color:var(--red)}
.acc-item svg{width:17px;height:17px;flex-shrink:0}
.acc-sep{height:1px;background:var(--line);margin:6px 4px}

/* ---------- Admin panel ---------- */
.admin-h{display:flex;gap:8px;padding:8px var(--pad) 0;overflow-x:auto;scrollbar-width:none}
.admin-h::-webkit-scrollbar{display:none}
.ad-tab{
  flex-shrink:0;padding:8px 14px;border-radius:20px;
  background:rgba(255,255,255,.04);border:1px solid var(--line);
  color:var(--muted);font-size:12px;font-weight:800;
  transition:.22s var(--ease-soft);
}
.ad-tab.on{background:var(--blue);color:#fff;border-color:var(--blue)}
.ad-user-card{
  padding:14px 16px;border-radius:14px;
  background:var(--panel);border:1px solid var(--line);
  margin-bottom:10px;display:flex;flex-direction:column;gap:10px;
}
.ad-user-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.ad-user-head .av{
  width:42px;height:42px;border-radius:12px;flex-shrink:0;
  background:linear-gradient(135deg,var(--blue),var(--blue2));
  display:grid;place-items:center;color:#fff;
  font-family:var(--font-en);font-weight:900;font-size:15px;
}
.ad-user-head .if{flex:1;min-width:0}
.ad-user-head b{display:block;font-size:14px;font-weight:900}
.ad-user-head small{font-size:11px;color:var(--muted);font-family:var(--font-en);letter-spacing:.5px}
.ad-user-acts{display:flex;gap:6px;flex-wrap:wrap}

/* ---------- Misc ---------- */
.mu{color:var(--muted)}
.center{text-align:center}
.mt-2{margin-top:10px}
.mt-4{margin-top:20px}
.pill{
  display:inline-flex;align-items:center;gap:6px;
  padding:4px 11px;border-radius:14px;
  background:rgba(var(--blue-rgb),.12);border:1px solid rgba(var(--blue-rgb),.3);
  color:var(--blue);font-family:var(--font-en);
  font-size:10.5px;font-weight:900;letter-spacing:.5px;
}
.pill.ok{background:rgba(16,185,129,.12);border-color:rgba(16,185,129,.3);color:var(--green)}
.pill.bad{background:rgba(239,68,68,.12);border-color:rgba(239,68,68,.3);color:var(--red)}
.pill.warn{background:rgba(245,158,11,.12);border-color:rgba(245,158,11,.3);color:var(--orange)}
.meter{height:6px;border-radius:99px;background:rgba(255,255,255,.08);overflow:hidden;margin:8px 0}
.meter b{display:block;height:100%;border-radius:inherit;background:linear-gradient(270deg,var(--blue),var(--blue2));transition:width .6s var(--ease-soft)}

@media(prefers-reduced-motion:reduce){
  *{animation:none!important;transition:none!important}
}
</style>
</head>
<body>

<!-- SPLASH -->
<div id="splash">
  <div class="sp-wrap">
    <div class="sp-logo">
      <svg viewBox="0 0 24 24" fill="currentColor"><path d="M11.35 2.76a1 1 0 0 1 1.3 0l9 7.5a1 1 0 0 1 .35.74V20a2 2 0 0 1-2 2h-4.5a1 1 0 0 1-1-1v-4h-3v4a1 1 0 0 1-1 1H5a2 2 0 0 1-2-2v-8.99a1 1 0 0 1 .35-.75l8-7.5z"/></svg>
    </div>
    <div class="sp-dots"><i></i><i></i><i></i></div>
    <div class="sp-foot" id="spFoot">STREAM MONITOR</div>
  </div>
</div>

<!-- APP ROOT -->
<div id="app"></div>

<!-- MODAL -->
<div class="modal" id="modal"><div class="sheet" id="sheet"></div></div>

<!-- TOASTS -->
<div class="toasts" id="toasts"></div>

<script>
'use strict';

/* ═══════════════════════════════════════════════════════
   UTILS
   ═══════════════════════════════════════════════════════ */
const $  = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));
const el = (tag, cls, txt) => { const e=document.createElement(tag); if(cls) e.className=cls; if(txt!=null) e.textContent=txt; return e; };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stripTags = s => String(s ?? '').replace(/<[^>]+>/g,'').trim();
const fmtTime = ts => {
  if (!ts) return '';
  const d = Math.floor(Date.now()/1000) - ts;
  if (d < 60) return 'الآن';
  if (d < 3600) return 'قبل ' + Math.floor(d/60) + ' د';
  if (d < 86400) return 'قبل ' + Math.floor(d/3600) + ' س';
  if (d < 604800) return 'قبل ' + Math.floor(d/86400) + ' يوم';
  return new Date(ts*1000).toLocaleDateString('ar-EG');
};

/* ─── API ─── */
async function api(path, opts={}) {
  const o = { credentials:'include', method: opts.method || 'GET', headers: {} };
  if (opts.body !== undefined) {
    o.headers['content-type'] = 'application/json';
    o.body = JSON.stringify(opts.body);
  }
  if (opts.form) { o.body = opts.form; }
  try {
    const r = await fetch(path, o);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      const msg = j.error || j.detail || 'خطأ في الاتصال';
      const err = new Error(msg);
      err.status = r.status;
      throw err;
    }
    return j;
  } catch (e) {
    if (e.status === 401 && !opts.silent) throw e;
    throw e;
  }
}

/* ─── Toasts ─── */
function toast(msg, kind) {
  const t = el('div', 'toast ' + (kind || ''));
  const icon = kind === 'ok'
    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" width="14" height="14"><polyline points="20 6 9 17 4 12"/></svg>'
    : kind === 'bad'
    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" width="14" height="14"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" width="14" height="14"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>';
  t.innerHTML = icon + '<span>' + esc(msg) + '</span>';
  $('#toasts').appendChild(t);
  requestAnimationFrame(() => t.classList.add('on'));
  setTimeout(() => { t.classList.remove('on'); setTimeout(() => t.remove(), 400); }, 3400);
}

/* ─── Modal ─── */
function modal(opts) {
  return new Promise(resolve => {
    const m = $('#modal'), sh = $('#sheet');
    sh.className = 'sheet' + (opts.small ? ' sm' : '') + (opts.wide ? ' wide' : '');
    let html = '<div class="grab"></div>';
    if (opts.title) html += '<div class="sh-title">' + esc(opts.title) + '</div>';
    if (opts.sub)   html += '<div class="sh-sub">' + esc(opts.sub) + '</div>';
    if (opts.html)  html += opts.html;
    let inputEl = null;
    if (opts.input) {
      html += '<label class="fld"><span>' + esc(opts.inputLabel||'') + '</span><input id="__mi" type="text" value="' + esc(opts.inputValue||'') + '" placeholder="' + esc(opts.placeholder||'') + '"></label>';
    }
    html += '<div class="row">';
    if (opts.cancel !== false) html += '<button class="btn ghost" id="__mc" type="button">' + esc(opts.cancelText || 'إلغاء') + '</button>';
    html += '<button class="btn ' + (opts.danger ? 'danger' : 'pri') + '" id="__mo" type="button">' + esc(opts.okText || 'تأكيد') + '</button>';
    html += '</div>';
    sh.innerHTML = html;
    m.classList.add('on');
    const close = (v) => {
      m.classList.remove('on');
      setTimeout(() => resolve(v), 300);
    };
    const okBtn = $('#__mo'), cBtn = $('#__mc');
    if (okBtn) okBtn.onclick = () => close(opts.input ? ($('#__mi').value || '') : true);
    if (cBtn) cBtn.onclick = () => close(opts.input ? null : false);
    m.onclick = e => { if (e.target === m) close(opts.input ? null : false); };
    if (opts.input) setTimeout(() => { const i = $('#__mi'); if (i) i.focus(); }, 200);
  });
}
const dlgOk    = (msg, title) => modal({ title: title || 'تنبيه', sub: msg, okText:'حسناً', cancel:false });
const dlgConfirm = (msg, title, danger) => modal({ title: title || 'تأكيد', sub: msg, danger, okText:'تأكيد' });

/* ─── Icons ─── */
const IC = {
  home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l9-8 9 8"/><path d="M5 10v10a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V10"/></svg>',
  kick: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 2h4.5v6.5L14 2h5.5L13 10.5l7 11.5h-5.6l-4.6-7.6-1.3 1.3V22H4z"/></svg>',
  yt: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M23 12s0-3.8-.5-5.6a2.9 2.9 0 0 0-2-2C18.7 4 12 4 12 4s-6.7 0-8.5.4a2.9 2.9 0 0 0-2 2C1 8.2 1 12 1 12s0 3.8.5 5.6c.3 1 1.1 1.8 2 2 1.8.4 8.5.4 8.5.4s6.7 0 8.5-.4c1-.3 1.8-1 2-2 .5-1.8.5-5.6.5-5.6zM9.75 15.5v-7l6.25 3.5-6.25 3.5z"/></svg>',
  tg: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M22.05 3.1 2.44 10.66c-1.03.4-1.02 1.83.01 2.21l4.76 1.76 1.83 5.85c.28.9 1.42 1.13 2.02.4l2.4-2.94 5.06 3.72c.66.48 1.6.1 1.76-.7l3.02-15.6c.18-.94-.75-1.7-1.25-1.06z"/></svg>',
  dc: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M20.3 4.4A19.7 19.7 0 0 0 15.4 3l-.2.4a18 18 0 0 1 4.3 2.2 17 17 0 0 0-15-.1A18 18 0 0 1 8.8 3.4L8.6 3a19.7 19.7 0 0 0-4.9 1.4C.6 9-.2 13.6.2 18a19.8 19.8 0 0 0 6 3l1.3-1.7a13 13 0 0 1-2-1l.5-.4a14 14 0 0 0 12 0l.5.4a13 13 0 0 1-2 1l1.3 1.7a19.8 19.8 0 0 0 6-3c.5-5.1-.8-9.7-3.5-13.6zM8.5 15.4c-1.2 0-2.2-1.1-2.2-2.4s1-2.4 2.2-2.4 2.2 1.1 2.2 2.4-1 2.4-2.2 2.4zm7 0c-1.2 0-2.2-1.1-2.2-2.4s1-2.4 2.2-2.4 2.2 1.1 2.2 2.4-1 2.4-2.2 2.4z"/></svg>',
  bell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg>',
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
  gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1A1.7 1.7 0 0 0 15 4.6a1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
  logout: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5M21 12H9"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>',
  eye: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
  lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/></svg>',
  logo: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M11.35 2.76a1 1 0 0 1 1.3 0l9 7.5a1 1 0 0 1 .35.74V20a2 2 0 0 1-2 2h-4.5a1 1 0 0 1-1-1v-4h-3v4a1 1 0 0 1-1 1H5a2 2 0 0 1-2-2v-8.99a1 1 0 0 1 .35-.75l8-7.5z"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17.25V21h3.75L17.8 9.94l-3.75-3.75L3 17.25z"/><path d="M20.7 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>',
  shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
  users: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
};

/* ═══════════════════════════════════════════════════════
   STATE
   ═══════════════════════════════════════════════════════ */
const S = {
  boot: {},
  me: null,
  guest: false,
  view: 'home',
  kind: 'kick',
  channels: { kick: [], yt: [], tg: [] },
  feeds: [],
  knownChannels: {},
  watching: [],
  notifs: [],
  unread: 0,
  settings: {},
  admin: { users: [], defaults: [], tab: 'users' },
  preview: null,
};
const isOwner = () => S.me && S.me.user && S.me.user.role === 'owner';
const isLogged = () => !!(S.me && S.me.user);

/* ═══════════════════════════════════════════════════════
   BOOT
   ═══════════════════════════════════════════════════════ */
async function boot() {
  try {
    const b = await api('/api/boot', { silent:true });
    S.boot = b;
    document.title = b.site_name || 'Respect Live';
    $('#spFoot').textContent = (b.site_sub || 'STREAM MONITOR').toUpperCase();
  } catch (e) {
    S.boot = { site_name:'Respect Live', site_sub:'STREAM MONITOR', guest_mode: true, guest_blur: 14 };
  }
  // محاولة استعادة الجلسة
  try {
    const me = await api('/api/me', { silent:true });
    S.me = me;
    await loadAll();
    renderApp();
  } catch (e) {
    S.guest = true;
    if (S.boot.guest_mode) {
      await loadPreview();
      renderApp();
    } else {
      renderAuth();
    }
  }
  // اختفاء السبلاش
  setTimeout(() => {
    const sp = $('#splash');
    if (sp) { sp.classList.add('out'); setTimeout(() => sp.remove(), 900); }
  }, 1300);
}

async function loadAll() {
  await Promise.all([
    loadChannels('kick'),
    loadChannels('yt'),
    loadChannels('tg'),
    loadFeeds(),
    loadNotifs(),
    loadSettings(),
  ]);
}

async function loadPreview() {
  try {
    S.preview = await api('/api/guest-preview', { silent:true });
  } catch (e) {
    S.preview = { counts:{ kick:0, yt:0, tg:0 }, live:[] };
  }
}

async function loadChannels(kind) {
  try {
    const r = await api('/api/channels/' + kind);
    S.channels[kind] = r.rows || [];
  } catch (e) { S.channels[kind] = []; }
}
async function loadFeeds() {
  try {
    const r = await api('/api/discord/feeds');
    S.feeds = r.rows || [];
    S.knownChannels = r.known_channels || {};
    S.watching = r.watching || [];
  } catch (e) { S.feeds = []; S.knownChannels = {}; S.watching = []; }
}
async function loadNotifs() {
  try {
    const r = await api('/api/notifs');
    S.notifs = r.rows || [];
    S.unread = r.unread || 0;
  } catch (e) { S.notifs = []; S.unread = 0; }
}
async function loadSettings() {
  try {
    S.settings = await api('/api/settings');
  } catch (e) { S.settings = {}; }
}

/* ═══════════════════════════════════════════════════════
   RENDER — AUTH
   ═══════════════════════════════════════════════════════ */
function renderAuth() {
  $('#app').innerHTML = `
  <div class="login-wrap">
    <div class="login-card">
      <div class="login-logo">${IC.logo}</div>
      <div class="login-head">
        <h1>RESPECT <span>LIVE</span></h1>
        <p>سجّل الدخول للوصول إلى لوحتك</p>
      </div>
      <div class="tabs2" id="authTabs">
        <button class="on" data-t="login">دخول</button>
        <button data-t="register">حساب جديد</button>
      </div>
      <form id="authForm">
        <label class="fld"><span>اسم المستخدم</span><input name="u" autocomplete="username" required></label>
        <label class="fld" id="pw2Wrap" style="display:none"><span>تأكيد كلمة المرور</span><input name="p2" type="password" autocomplete="new-password"></label>
        <label class="fld"><span>كلمة المرور</span><input name="p" type="password" autocomplete="current-password" required></label>
        <button class="btn pri wide" type="submit" id="authBtn">دخول</button>
        <div class="err" id="authErr"></div>
      </form>
      ${S.boot.guest_mode ? `
      <div class="skip-row">
        <button id="skipBtn" type="button">${IC.eye} تصفح كزائر</button>
      </div>` : ''}
    </div>
  </div>`;

  let mode = 'login';
  $$('#authTabs button').forEach(b => {
    b.onclick = () => {
      mode = b.dataset.t;
      $$('#authTabs button').forEach(x => x.classList.toggle('on', x === b));
      $('#pw2Wrap').style.display = mode === 'register' ? '' : 'none';
      $('#authBtn').textContent = mode === 'register' ? 'إنشاء حساب' : 'دخول';
      $('#authErr').textContent = '';
    };
  });

  $('#authForm').onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    const btn = $('#authBtn');
    const err = $('#authErr');
    err.textContent = '';
    btn.disabled = true;
    try {
      const fd = new FormData();
      fd.append('u', f.u.value.trim());
      fd.append('p', f.p.value);
      const url = mode === 'register' ? '/api/register' : '/api/login';
      const r = await fetch(url, { method:'POST', body: fd, credentials:'include' });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || j.detail || 'فشل');
      location.reload();
    } catch (e2) {
      err.textContent = e2.message;
      toast(e2.message, 'bad');
    } finally {
      btn.disabled = false;
    }
  };

  const skip = $('#skipBtn');
  if (skip) skip.onclick = async () => {
    S.guest = true;
    await loadPreview();
    renderApp();
  };
}

/* ═══════════════════════════════════════════════════════
   RENDER — MAIN APP
   ═══════════════════════════════════════════════════════ */
function renderApp() {
  const name = (S.boot.site_name || 'Respect Live').split(' ');
  const brandHTML = name.length >= 2
    ? esc(name[0]).toUpperCase() + ' <span>' + esc(name.slice(1).join(' ')).toUpperCase() + '</span>'
    : '<span>' + esc(name[0]).toUpperCase() + '</span>';

  const avatarHTML = isLogged()
    ? '<div class="avatar-btn" id="accBtn">' + esc(S.me.user.username.charAt(0).toUpperCase()) + '<div class="st"></div></div>'
    : '<div class="avatar-btn guest" id="accBtn">' + IC.user + '</div>';

  $('#app').innerHTML = `
    <div class="top" id="top">
      <div class="brand">
        <div class="brand-logo">${IC.logo}</div>
        <div class="brand-txt">
          <div class="brand-name">${brandHTML}</div>
          <div class="brand-sub">${esc((S.boot.site_sub || 'STREAM MONITOR').toUpperCase())}</div>
        </div>
      </div>
      <div class="hdr-acts">
        ${isLogged() ? `<button class="hdr-btn" id="notifBtn" aria-label="الإشعارات">${IC.bell}${S.unread>0?'<span class="badge" id="unreadBadge">'+(S.unread>99?'99+':S.unread)+'</span>':''}</button>` : ''}
        ${avatarHTML}
      </div>
    </div>

    ${S.guest ? `
    <div class="guest-banner">
      <div class="gb-ico">${IC.eye}</div>
      <div class="gb-txt">
        أنت تتصفح كزائر — المحتوى مغبّش
        <small>سجّل دخولك لعرض كل التفاصيل وإدارة قنواتك</small>
      </div>
      <button class="btn pri sm" id="loginNow">تسجيل الدخول</button>
    </div>` : ''}

    <div class="chips" id="tabs">
      <button class="chip ${S.view==='kick'?'on':''}" data-v="kick">${IC.kick} KICK <span class="cnt">${isLogged()?S.channels.kick.length:(S.preview?.counts.kick||0)}</span></button>
      <button class="chip ${S.view==='yt'?'on':''}" data-v="yt">${IC.yt} YOUTUBE <span class="cnt">${isLogged()?S.channels.yt.length:(S.preview?.counts.yt||0)}</span></button>
      <button class="chip ${S.view==='tg'?'on':''}" data-v="tg">${IC.tg} TELEGRAM <span class="cnt">${isLogged()?S.channels.tg.length:(S.preview?.counts.tg||0)}</span></button>
      ${isLogged() ? `<button class="chip ${S.view==='dc'?'on':''}" data-v="dc">${IC.dc} DISCORD <span class="cnt">${S.feeds.length}</span></button>` : ''}
    </div>

    <div id="view"></div>

    <div class="tabbar">
      <button data-v="home" class="${S.view==='home'?'on':''}">${IC.home}</button>
      <button data-v="kick" class="${S.view==='kick'?'on':''}">${IC.kick}</button>
      <button data-v="yt" class="${S.view==='yt'?'on':''}">${IC.yt}</button>
      <button data-v="tg" class="${S.view==='tg'?'on':''}">${IC.tg}</button>
      ${isLogged() ? `<button data-v="dc" class="${S.view==='dc'?'on':''}">${IC.dc}</button>` : `<button data-v="acc">${IC.user}</button>`}
    </div>
  `;

  $$('[data-v]').forEach(b => b.onclick = () => { S.view = b.dataset.v; renderApp(); });
  const ab = $('#accBtn');
  if (ab) ab.onclick = openAccountMenu;
  const nb = $('#notifBtn');
  if (nb) nb.onclick = () => { S.view = 'notifs'; renderApp(); };
  const ln = $('#loginNow');
  if (ln) ln.onclick = () => { S.guest = false; renderAuth(); };

  // sticky header border
  window.addEventListener('scroll', () => {
    const t = $('#top'); if (t) t.classList.toggle('scrolled', window.scrollY > 8);
  }, { passive: true, once: false });

  renderView();
}

/* ═══════════════════════════════════════════════════════
   RENDER VIEWS
   ═══════════════════════════════════════════════════════ */
function renderView() {
  const v = $('#view');
  if (!v) return;
  if (S.view === 'home') return viewHome(v);
  if (S.view === 'notifs') return viewNotifs(v);
  if (S.view === 'dc') return viewDiscord(v);
  if (S.view === 'acc') return openAccountMenu();
  return viewChannels(v, S.view);
}

/* ─── HOME ─── */
function viewHome(v) {
  const counts = isLogged()
    ? { kick:S.channels.kick.length, yt:S.channels.yt.length, tg:S.channels.tg.length, dc:S.feeds.length }
    : { kick:S.preview?.counts.kick||0, yt:S.preview?.counts.yt||0, tg:S.preview?.counts.tg||0, dc:0 };

  v.innerHTML = `
    <div class="hero">
      <div class="hero-lbl"><span>◆</span> RESPECT LIVE</div>
      <h1>${esc((S.boot.hero_title||'مراقبة').toUpperCase())} <span>${esc((S.boot.hero_accent||'القنوات.'))}</span></h1>
      <p>${esc(S.boot.hero_text||'تابع قنواتك على كيك ويوتيوب وتيليجرام في مكان واحد. إشعارات فورية عند أي بث أو فيديو جديد.')}</p>
    </div>
    <div class="stats">
      <div class="s"><b class="blue">${counts.kick}</b><small>KICK</small></div>
      <div class="s"><b>${counts.yt}</b><small>YOUTUBE</small></div>
      <div class="s"><b>${counts.tg}</b><small>TELEGRAM</small></div>
      <div class="s"><b>${isLogged()?counts.dc:(S.boot.discord_watching||0)}</b><small>DISCORD</small></div>
    </div>
    ${!isLogged() ? `
    <div class="sec">
      <div class="locked" style="padding:0">
        <div class="lock-cover" style="position:relative;background:var(--card);border:1px solid var(--line);padding:40px 20px;border-radius:var(--radius)">
          <div class="lc-icon">${IC.lock}</div>
          <h3>سجّل دخولك للبدء</h3>
          <p>أنشئ حسابك المجاني وابدأ بمتابعة قنواتك المفضلة</p>
          <button class="btn pri" id="ctaLogin">دخول / حساب جديد</button>
        </div>
      </div>
    </div>` : ''}
  `;
  const btn = $('#ctaLogin');
  if (btn) btn.onclick = () => { S.guest = false; renderAuth(); };
}

/* ─── CHANNELS ─── */
function viewChannels(v, kind) {
  const rows = isLogged() ? (S.channels[kind] || []) : (S.preview?.live || []);

  v.innerHTML = `
    <div class="sec" style="padding-top:0">
      <div class="sec-h">
        <div class="sec-title">${kind==='kick'?'قنوات كيك':kind==='yt'?'قنوات يوتيوب':'قنوات تيليجرام'} <span>.</span></div>
        ${isLogged() ? `<button class="btn pri sm" id="addBtn">${IC.plus} إضافة</button>` : ''}
      </div>
      <div id="cList"></div>
    </div>
  `;
  const list = $('#cList');
  if (!rows.length) {
    list.innerHTML = `
      <div class="empty">
        <div class="em-icon">${IC[kind]||IC.home}</div>
        <h3>لا توجد قنوات بعد</h3>
        <p>${isLogged()?'ابدأ بإضافة أول قناة لتبدأ المراقبة':'سجّل دخولك لتتمكن من إضافة قنواتك'}</p>
        ${isLogged()?`<button class="btn pri" id="emptyAdd">${IC.plus} إضافة قناة</button>`:`<button class="btn pri" id="emptyLogin">تسجيل الدخول</button>`}
      </div>`;
    const eb = $('#emptyAdd'); if (eb) eb.onclick = () => openAddChannel(kind);
    const elb = $('#emptyLogin'); if (elb) elb.onclick = () => { S.guest = false; renderAuth(); };
  } else {
    const grid = el('div', 'grid');
    rows.forEach(r => grid.appendChild(chCard(kind, r)));
    list.appendChild(grid);
  }
  const ab = $('#addBtn'); if (ab) ab.onclick = () => openAddChannel(kind);
}

function chCard(kind, r) {
  const card = el('div', 'ch');

  if (!isLogged()) {
    // كارت الزائر: مغبش
    card.innerHTML = `
      <div class="lock-blur" style="padding:14px">
        <div style="display:flex;gap:12px;align-items:center;margin-bottom:12px">
          <div style="width:54px;height:54px;border-radius:14px;background:linear-gradient(135deg,var(--blue),var(--blue2))"></div>
          <div style="flex:1">
            <div style="height:16px;background:rgba(255,255,255,.15);border-radius:6px;margin-bottom:6px;width:70%"></div>
            <div style="height:12px;background:rgba(255,255,255,.08);border-radius:6px;width:50%"></div>
          </div>
        </div>
        <div style="height:140px;background:rgba(255,255,255,.05);border-radius:12px;margin-bottom:10px"></div>
        <div style="display:flex;gap:6px">
          <div style="flex:1;height:34px;background:rgba(255,255,255,.05);border-radius:10px"></div>
          <div style="flex:1;height:34px;background:rgba(255,255,255,.05);border-radius:10px"></div>
        </div>
      </div>
      <div class="lock-cover">
        <div class="lc-icon" style="width:52px;height:52px">${IC.lock}</div>
        <h3>سجّل دخولك</h3>
        <p>لرؤية تفاصيل هذه القناة</p>
        <button class="btn pri sm" onclick="window.__goLogin()">دخول سريع</button>
      </div>
    `;
    return card;
  }

  let slug = '', title = '', sub = '';
  if (kind === 'kick') { slug='@'+(r.slug||''); title=r.name||r.slug||''; sub=r.live&&r.title?r.title:'قناة كيك'; }
  else if (kind === 'yt') { slug=r.channel_id||''; title=r.name||r.channel_id||''; sub='قناة يوتيوب'; }
  else { slug=r.chat_id||''; title=r.name||r.chat_id||''; sub='قناة تيليجرام'; }

  const liveBadge = kind==='kick' && r.live && r.enabled
    ? '<span class="ch-badge live">مباشر</span>'
    : (!r.enabled ? '<span class="ch-badge off">موقوف</span>' : '');

  const cover = r.banner || r.avatar || '';
  const avatarHTML = r.avatar
    ? `<img src="${esc(r.avatar)}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'ph',innerHTML:'${IC[kind].replace(/'/g,"\\'")}'}))">`
    : `<div class="ph">${IC[kind]}</div>`;

  card.innerHTML = `
    <div class="ch-cover">
      ${cover?`<img src="${esc(cover)}" onerror="this.remove()">`:''}
      ${liveBadge}
    </div>
    <div class="ch-head">
      ${avatarHTML}
      <div class="ch-info">
        <b>${esc(title)}</b>
        <small>${esc(slug)}</small>
      </div>
    </div>
    ${kind==='kick' && r.live && r.title ? `<div class="ch-live"><div>${esc(r.title)}</div><span>${r.viewers||0} 👁</span></div>` : ''}
    ${r.msg ? `<div class="ch-note">${esc(stripTags(r.msg))}</div>` : ''}
    <div class="ch-acts">
      ${kind==='kick' ? `<a class="btn sm" href="https://kick.com/${esc(r.slug)}" target="_blank" rel="noopener">${IC.play} مشاهدة</a>` : ''}
      ${kind==='yt' ? `<a class="btn sm" href="https://youtube.com/channel/${esc(r.channel_id)}" target="_blank" rel="noopener">${IC.play} زيارة</a>` : ''}
      ${kind!=='tg' ? `<button class="btn sm ghost" data-act="edit">${IC.edit} رسالة</button>` : ''}
      <button class="btn sm ghost" data-act="toggle">${r.enabled?'إيقاف':'تفعيل'}</button>
      <button class="btn sm danger" data-act="del">${IC.trash}</button>
    </div>
  `;

  card.querySelectorAll('[data-act]').forEach(b => {
    b.onclick = async (e) => {
      e.stopPropagation();
      const act = b.dataset.act;
      if (act === 'del') {
        const ok = await dlgConfirm('حذف هذه القناة نهائياً؟', 'حذف قناة', true);
        if (!ok) return;
        try {
          await api('/api/channels/' + kind + '/' + r.id, { method:'DELETE' });
          toast('تم الحذف', 'ok');
          await loadChannels(kind);
          renderApp();
        } catch (e2) { toast(e2.message, 'bad'); }
      } else if (act === 'toggle') {
        try {
          await api('/api/channels/' + kind + '/' + r.id, { method:'PATCH', body:{ enabled: !r.enabled }});
          toast(r.enabled ? 'تم الإيقاف' : 'تم التفعيل', 'ok');
          await loadChannels(kind);
          renderApp();
        } catch (e2) { toast(e2.message, 'bad'); }
      } else if (act === 'edit') {
        const msg = await modal({
          title:'تخصيص رسالة الإشعار',
          sub:'المتغيرات: {name} {title} {url}',
          html:'<label class="fld"><span>نص الرسالة</span><textarea id="__msg" rows="5">' + esc(r.msg || '') + '</textarea></label>',
          okText:'حفظ'
        });
        if (msg === null || msg === false) return;
        const txt = $('#__msg').value;
        try {
          await api('/api/channels/' + kind + '/' + r.id, { method:'PATCH', body:{ msg: txt }});
          toast('تم الحفظ', 'ok');
          await loadChannels(kind);
          renderApp();
        } catch (e2) { toast(e2.message, 'bad'); }
      }
    };
  });
  return card;
}
window.__goLogin = () => { S.guest = false; renderAuth(); };

/* ─── ADD CHANNEL ─── */
async function openAddChannel(kind) {
  if (!isLogged()) return;

  // اجلب اقتراحات أولاً
  let suggestions = [];
  try {
    const r = await api('/api/channels/' + kind + '/suggestions');
    suggestions = r.rows || [];
  } catch (e) {}

  const labels = {
    kick: { title:'إضافة قناة كيك', label:'اسم القناة (slug)', ph:'xqc', icon:IC.kick },
    yt:   { title:'إضافة قناة يوتيوب', label:'Channel ID (@handle أو UC...)', ph:'@MrBeast', icon:IC.yt },
    tg:   { title:'إضافة قناة تيليجرام', label:'@username أو chat_id', ph:'@mychannel', icon:IC.tg },
  }[kind];

  let sel = new Set();

  const sugHTML = suggestions.length ? `
    <div style="margin-top:20px;padding-top:18px;border-top:1px solid var(--line)">
      <div class="sh-sub" style="margin-bottom:6px">${IC.plus} قنوات مُقترحة من الإدارة</div>
      <div class="sug-grid" id="sugGrid">
        ${suggestions.map(s => `
          <div class="sug-item" data-id="${s.id}">
            <div class="av">${s.avatar ? `<img src="${esc(s.avatar)}" onerror="this.remove()">` : esc((s.name||'?').charAt(0).toUpperCase())}</div>
            <div class="if">
              <b>${esc(s.name || s.identifier)}</b>
              <small>${esc(s.identifier)}</small>
            </div>
            <div class="ck">${IC.check}</div>
          </div>
        `).join('')}
      </div>
      <div class="sug-toolbar">
        <span id="sugCount">0 محددة</span>
        <button type="button" id="sugToggleAll">تحديد الكل</button>
      </div>
    </div>
  ` : '';

  const html = `
    <label class="fld"><span>${esc(labels.label)}</span><input id="__ci" placeholder="${esc(labels.ph)}"></label>
    <label class="fld"><span>الاسم المخصص (اختياري)</span><input id="__cn" placeholder="اسم ودّي"></label>
    ${sugHTML}
  `;

  const result = await modal({
    title: labels.title,
    html: html,
    okText: 'إضافة',
    cancelText: 'إلغاء',
    wide: suggestions.length > 0,
  });

  if (result === false || result === null) return;

  // إذا كان فيه اقتراحات محددة → bulk-add
  if (sel.size > 0) {
    try {
      const r = await api('/api/channels/' + kind + '/bulk-add', {
        method: 'POST',
        body: { ids: Array.from(sel) }
      });
      const added = r.added || 0;
      const failed = r.failed || 0;
      if (added > 0) toast('تمت إضافة ' + added + ' قناة' + (failed ? '، فشل ' + failed : ''), failed ? '' : 'ok');
      else toast('لم تُضف أي قناة', 'bad');
      await loadChannels(kind);
      renderApp();
    } catch (e) { toast(e.message, 'bad'); }
    return;
  }

  // إضافة يدوية
  const val = $('#__ci').value.trim();
  const customName = $('#__cn').value.trim();
  if (!val) return toast('اكتب القيمة', 'bad');

  try {
    const body = kind === 'kick' ? { slug: val, msg: '' }
              : kind === 'yt'   ? { channel_id: val, name: customName }
                                : { chat_id: val, name: customName };
    await api('/api/channels/' + kind, { method: 'POST', body });
    toast('تمت الإضافة', 'ok');
    await loadChannels(kind);
    renderApp();
  } catch (e) { toast(e.message, 'bad'); }
}

/* ─── DISCORD ─── */
function viewDiscord(v) {
  v.innerHTML = `
    <div class="sec" style="padding-top:0">
      <div class="sec-h">
        <div class="sec-title">ديسكورد <span>.</span></div>
        <button class="btn pri sm" id="addFeedBtn">${IC.plus} ربط روم</button>
      </div>

      <div class="pill ${S.watching.length?'ok':'warn'}" style="margin-bottom:12px">${IC.dc} ${S.watching.length} روم مراقب من البوت</div>

      ${S.feeds.length ? `<div id="feedsList"></div>` : `
        <div class="empty">
          <div class="em-icon">${IC.dc}</div>
          <h3>لا توجد رومات مربوطة</h3>
          <p>اربط روم ديسكورد ليستقبل رسائله على قنوات تيليجرام</p>
          <button class="btn pri" id="emptyAddFeed">${IC.plus} ربط روم</button>
        </div>
      `}
    </div>
  `;

  const emptyBtn = $('#emptyAddFeed');
  if (emptyBtn) emptyBtn.onclick = openAddFeed;
  const addBtn = $('#addFeedBtn');
  if (addBtn) addBtn.onclick = openAddFeed;

  const list = $('#feedsList');
  if (list) {
    S.feeds.forEach(f => {
      const card = el('div', 'ch');
      const name = (S.knownChannels[f.channel_id]?.name) || f.channel_name || f.channel_id;
      const sourceLabel = f.source_type === 'twitter' ? 'تويتر' : f.source_type === 'youtube' ? 'يوتيوب' : 'عام';
      card.innerHTML = `
        <div style="padding:16px">
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px">
            <div style="width:44px;height:44px;border-radius:12px;background:rgba(var(--blue-rgb),.15);border:1px solid rgba(var(--blue-rgb),.35);display:grid;place-items:center;color:var(--blue);flex-shrink:0">${IC.dc}</div>
            <div style="flex:1;min-width:0">
              <div style="font-weight:900;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">#${esc(name)}</div>
              <div style="font-family:var(--font-en);font-size:10.5px;color:var(--muted);letter-spacing:.5px;margin-top:2px">ID: ${esc(f.channel_id)}</div>
            </div>
            <span class="pill">${esc(sourceLabel)}</span>
          </div>
          ${f.template ? `<div style="padding:10px 12px;background:rgba(0,0,0,.25);border-radius:10px;font-size:12px;white-space:pre-wrap;font-family:monospace;color:var(--muted);margin-bottom:10px">${esc(f.template)}</div>` : ''}
          <div style="display:flex;gap:6px;flex-wrap:wrap">
            <button class="btn sm ghost" data-fa="edit">${IC.edit} تعديل القالب</button>
            <button class="btn sm ghost" data-fa="toggle">${f.enabled ? 'إيقاف' : 'تفعيل'}</button>
            <button class="btn sm danger" data-fa="del">${IC.trash} حذف</button>
          </div>
        </div>
      `;
      card.querySelectorAll('[data-fa]').forEach(b => {
        b.onclick = async () => {
          const act = b.dataset.fa;
          if (act === 'del') {
            const ok = await dlgConfirm('حذف هذا الربط؟', 'تأكيد', true);
            if (!ok) return;
            try {
              await api('/api/discord/feeds/' + f.id, { method:'DELETE' });
              toast('تم الحذف', 'ok');
              await loadFeeds();
              renderApp();
            } catch (e) { toast(e.message, 'bad'); }
          } else if (act === 'toggle') {
            try {
              await api('/api/discord/feeds/' + f.id, { method:'PATCH', body:{ enabled: !f.enabled }});
              toast(f.enabled ? 'تم الإيقاف' : 'تم التفعيل', 'ok');
              await loadFeeds();
              renderApp();
            } catch (e) { toast(e.message, 'bad'); }
          } else if (act === 'edit') {
            const tpl = await modal({
              title:'تعديل القالب',
              sub:'المتغيرات: {author} {content} {channel} {source}',
              html:'<label class="fld"><span>القالب</span><textarea id="__tp" rows="5">' + esc(f.template || '') + '</textarea></label>',
              okText:'حفظ'
            });
            if (tpl === null || tpl === false) return;
            try {
              await api('/api/discord/feeds/' + f.id, { method:'PATCH', body:{ template: $('#__tp').value }});
              toast('تم الحفظ', 'ok');
              await loadFeeds();
              renderApp();
            } catch (e) { toast(e.message, 'bad'); }
          }
        };
      });
      list.appendChild(card);
    });
  }
}

async function openAddFeed() {
  if (!isLogged()) return;
  const known = S.knownChannels || {};
  const options = Object.entries(known).map(([id, info]) =>
    `<option value="${esc(id)}">#${esc(info.name || id)} — ${esc(info.guild||'')}</option>`
  ).join('');

  const html = `
    ${S.watching.length ? `
      <label class="fld"><span>من قائمة الرومات المراقبة</span>
        <select id="__chList">
          <option value="">— اختر —</option>
          ${S.watching.map(id => {
            const info = known[id];
            return `<option value="${esc(id)}">${info ? '#'+esc(info.name) : id}</option>`;
          }).join('')}
        </select>
      </label>
      <div class="center mu" style="font-size:11.5px;margin:4px 0 12px">أو</div>
    ` : ''}
    <label class="fld"><span>channel_id (رقم الروم)</span><input id="__ch" placeholder="123456789012345678" inputmode="numeric"></label>
    <label class="fld"><span>نوع المصدر</span>
      <select id="__src">
        <option value="generic">عام (كل الرسائل)</option>
        <option value="twitter">تويتر / X فقط</option>
        <option value="youtube">يوتيوب فقط</option>
      </select>
    </label>
    <label class="fld"><span>قالب مخصص (اختياري)</span><textarea id="__tpl" rows="4" placeholder="<b>{author}</b>\n{content}"></textarea></label>
    <div class="mu" style="font-size:11.5px;margin-top:-6px">المتغيرات: {author} {content} {channel} {source}</div>
  `;

  const r = await modal({
    title:'ربط روم ديسكورد',
    sub:'كل رسالة جديدة في الروم تُرسل لقنواتك على تيليجرام',
    html, okText:'ربط'
  });
  if (!r) return;

  let cid = $('#__chList')?.value || $('#__ch')?.value.trim() || '';
  if (S.watching.length && $('#__chList')?.value && !$('#__ch')?.value) {
    cid = $('#__chList').value;
  }
  if (!cid) return toast('اختر الروم أو اكتب الـ ID', 'bad');

  try {
    await api('/api/discord/feeds', { method:'POST', body: {
      channel_id: cid,
      channel_name: known[cid]?.name || '',
      template: $('#__tpl').value.trim(),
      source_type: $('#__src').value,
    }});
    toast('تم الربط', 'ok');
    await loadFeeds();
    renderApp();
  } catch (e) { toast(e.message, 'bad'); }
}

/* ─── NOTIFICATIONS ─── */
function viewNotifs(v) {
  v.innerHTML = `
    <div class="sec" style="padding-top:0">
      <div class="sec-h">
        <div class="sec-title">الإشعارات <span>.</span></div>
        ${S.notifs.length ? `
          <div style="display:flex;gap:6px">
            <button class="btn sm ghost" id="readAll">قرأت الكل</button>
            <button class="btn sm danger" id="clearAll">مسح</button>
          </div>` : ''}
      </div>
      <div id="ntList"></div>
    </div>
  `;
  const l = $('#ntList');
  if (!S.notifs.length) {
    l.innerHTML = `<div class="empty">
      <div class="em-icon">${IC.bell}</div>
      <h3>لا توجد إشعارات</h3>
      <p>ستظهر هنا إشعارات البث والفيديو ورسائل الإدارة</p>
    </div>`;
    return;
  }
  S.notifs.forEach(n => {
    const c = el('div', 'notif' + (n.is_read ? '' : ' un'));
    c.innerHTML = `
      ${n.image ? `<img src="${esc(n.image)}" alt="" onerror="this.remove()">` : ''}
      <div class="nt-b">
        <b>${esc(n.title||'')}</b>
        ${n.body ? `<p>${esc(n.body)}</p>` : ''}
        ${n.btn_text && n.btn_url ? `<a class="btn sm pri" href="${esc(n.btn_url)}" target="_blank" rel="noopener" style="margin-top:8px">${esc(n.btn_text)}</a>` : ''}
        <div class="nt-t">${fmtTime(n.ts)}</div>
      </div>
    `;
    if (!n.is_read) {
      c.onclick = async () => {
        try {
          // استعمل endpoint read-all فقط، يمكننا إضافة read per-id لكن هذا يكفي
          await api('/api/notifs/read-all', { method:'POST' });
          await loadNotifs();
          renderApp();
        } catch (e) {}
      };
    }
    l.appendChild(c);
  });

  const ra = $('#readAll');
  if (ra) ra.onclick = async () => {
    try { await api('/api/notifs/read-all', { method:'POST' }); await loadNotifs(); renderApp(); } catch (e) {}
  };
  const ca = $('#clearAll');
  if (ca) ca.onclick = async () => {
    const ok = await dlgConfirm('مسح كل الإشعارات؟', 'تأكيد', true);
    if (!ok) return;
    try { await api('/api/notifs/clear', { method:'POST' }); await loadNotifs(); renderApp(); } catch (e) {}
  };
}

/* ═══════════════════════════════════════════════════════
   ACCOUNT MENU
   ═══════════════════════════════════════════════════════ */
function openAccountMenu() {
  if (!isLogged()) {
    if (S.guest) { S.guest = false; renderAuth(); }
    return;
  }
  const old = $('#accMenu'); if (old) old.remove();
  const m = el('div', 'acc-menu'); m.id = 'accMenu';
  const u = S.me.user;
  const usage = S.me.usage || { kick:0, yt:0, tg:0 };
  const limits = S.me.limits || { kick:10, yt:5, tg:3 };

  m.innerHTML = `
    <div class="acc-head">
      <div class="nm">${esc(u.display || u.username)}</div>
      <div class="mt">@${esc(u.username)} · ${u.role==='owner'?'الإدارة':'مستخدم'}</div>
      <div class="stats-mini">
        <span>${IC.kick} <b>${usage.kick}/${limits.kick}</b></span>
        <span>${IC.yt} <b>${usage.yt}/${limits.yt}</b></span>
        <span>${IC.tg} <b>${usage.tg}/${limits.tg}</b></span>
      </div>
    </div>
    <button class="acc-item" data-a="settings">${IC.gear} الإعدادات</button>
    ${isOwner() ? `<button class="acc-item" data-a="admin">${IC.shield} لوحة الإدارة</button>` : ''}
    <div class="acc-sep"></div>
    <button class="acc-item danger" data-a="logout">${IC.logout} تسجيل الخروج</button>
  `;
  document.body.appendChild(m);
  requestAnimationFrame(() => m.classList.add('on'));

  m.querySelectorAll('[data-a]').forEach(b => {
    b.onclick = () => {
      m.classList.remove('on');
      setTimeout(() => m.remove(), 260);
      const a = b.dataset.a;
      if (a === 'logout') doLogout();
      else if (a === 'settings') openSettings();
      else if (a === 'admin') openAdmin();
    };
  });
  setTimeout(() => {
    const close = e => {
      if (!m.contains(e.target) && e.target.id !== 'accBtn' && !e.target.closest('#accBtn')) {
        m.classList.remove('on');
        setTimeout(() => m.remove(), 260);
        document.removeEventListener('click', close);
      }
    };
    document.addEventListener('click', close);
  }, 50);
}

async function doLogout() {
  const ok = await dlgConfirm('هل تريد تسجيل الخروج؟', 'تأكيد', true);
  if (!ok) return;
  try { await api('/api/logout', { method:'POST' }); } catch (e) {}
  location.reload();
}

/* ═══════════════════════════════════════════════════════
   SETTINGS
   ═══════════════════════════════════════════════════════ */
async function openSettings() {
  await loadSettings();
  const s = S.settings;
  const html = `
    <label class="fld"><span>اسم الموقع</span><input id="__sn" value="${esc(s.site_name||'')}"></label>
    <label class="fld"><span>العنوان الفرعي</span><input id="__ss" value="${esc(s.site_sub||'')}"></label>
    <label class="fld"><span>عنوان الهيرو</span><input id="__ht" value="${esc(s.hero_title||'')}"></label>
    <label class="fld"><span>الجزء المميز</span><input id="__ha" value="${esc(s.hero_accent||'')}"></label>
    <label class="fld"><span>نص الهيرو</span><textarea id="__hx" rows="2">${esc(s.hero_text||'')}</textarea></label>

    <div class="sh-sub mt-4" style="border-top:1px solid var(--line);padding-top:14px">قوالب الإشعارات</div>
    <label class="fld"><span>قالب كيك</span><textarea id="__tk" rows="3">${esc(s.tpl_kick||'')}</textarea></label>
    <label class="fld"><span>قالب يوتيوب</span><textarea id="__ty" rows="3">${esc(s.tpl_yt||'')}</textarea></label>
    <label class="fld"><span>قالب ديسكورد (عام)</span><textarea id="__td" rows="3">${esc(s.tpl_discord||'')}</textarea></label>
    <label class="fld"><span>قالب تويتر من ديسكورد</span><textarea id="__tt" rows="3">${esc(s.tpl_twitter||'')}</textarea></label>
    <label class="fld"><span>قالب يوتيوب من ديسكورد</span><textarea id="__tyc" rows="3">${esc(s.tpl_youtube_dc||'')}</textarea></label>

    ${isOwner() ? `
    <div class="sh-sub mt-4" style="border-top:1px solid var(--line);padding-top:14px">إعدادات المالك</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px">
      <label class="fld"><span>حد كيك</span><input id="__lk" type="number" value="${esc(s.lim_kick||'10')}"></label>
      <label class="fld"><span>حد يوتيوب</span><input id="__ly" type="number" value="${esc(s.lim_yt||'5')}"></label>
      <label class="fld"><span>حد تيليجرام</span><input id="__lt" type="number" value="${esc(s.lim_tg||'3')}"></label>
    </div>
    <label class="fld"><span>درجة تغبيش الزوار (px)</span><input id="__gb" type="number" value="${esc(s.guest_blur||'14')}"></label>
    <label style="display:flex;align-items:center;gap:8px;margin:14px 0;font-weight:800"><input type="checkbox" id="__gm" ${s.guest_mode==='1'?'checked':''} style="width:auto;transform:scale(1.2)"> السماح بالتصفح كزائر</label>
    ` : ''}
  `;

  const ok = await modal({ title:'الإعدادات', html, okText:'حفظ', wide:true });
  if (!ok) return;

  const body = {
    site_name: $('#__sn').value,
    site_sub: $('#__ss').value,
    hero_title: $('#__ht').value,
    hero_accent: $('#__ha').value,
    hero_text: $('#__hx').value,
    tpl_kick: $('#__tk').value,
    tpl_yt: $('#__ty').value,
    tpl_discord: $('#__td').value,
    tpl_twitter: $('#__tt').value,
    tpl_youtube_dc: $('#__tyc').value,
  };
  if (isOwner()) {
    body.lim_kick = $('#__lk').value;
    body.lim_yt = $('#__ly').value;
    body.lim_tg = $('#__lt').value;
    body.guest_blur = $('#__gb').value;
    body.guest_mode = $('#__gm').checked ? '1' : '0';
  }

  try {
    await api('/api/settings', { method:'POST', body });
    toast('تم الحفظ', 'ok');
    await loadSettings();
    renderApp();
  } catch (e) { toast(e.message, 'bad'); }
}

/* ═══════════════════════════════════════════════════════
   ADMIN PANEL
   ═══════════════════════════════════════════════════════ */
async function openAdmin() {
  if (!isOwner()) return toast('غير مصرح', 'bad');
  S.view = 'admin';
  await loadAdminData();
  renderAdmin();
}

async function loadAdminData() {
  try {
    const [users, defaults] = await Promise.all([
      api('/api/admin/users'),
      api('/api/admin/default-channels'),
    ]);
    S.admin.users = users.rows || [];
    S.admin.defaults = defaults.rows || [];
  } catch (e) { toast(e.message, 'bad'); }
}

function renderAdmin() {
  $('#app').innerHTML = `
    <div class="top">
      <div class="brand">
        <div class="brand-logo">${IC.shield}</div>
        <div class="brand-txt">
          <div class="brand-name">لوحة <span>الإدارة</span></div>
          <div class="brand-sub">ADMIN PANEL</div>
        </div>
      </div>
      <button class="hdr-btn" id="adBack" aria-label="رجوع">${IC.x}</button>
    </div>
    <div class="admin-h" id="adTabs">
      <button class="ad-tab ${S.admin.tab==='users'?'on':''}" data-t="users">المستخدمون</button>
      <button class="ad-tab ${S.admin.tab==='defaults'?'on':''}" data-t="defaults">القنوات الافتراضية</button>
      <button class="ad-tab ${S.admin.tab==='sec'?'on':''}" data-t="sec">الأمان</button>
    </div>
    <div id="adContent" class="sec" style="padding-top:14px"></div>
    <div class="tabbar" style="justify-content:center">
      <button id="adBack2">${IC.home}</button>
    </div>
  `;
  $('#adBack').onclick = backHome;
  $('#adBack2').onclick = backHome;
  $$('#adTabs .ad-tab').forEach(b => {
    b.onclick = () => { S.admin.tab = b.dataset.t; renderAdmin(); };
  });
  renderAdminContent();
}

function backHome() { S.view = 'home'; renderApp(); }

function renderAdminContent() {
  const c = $('#adContent'); if (!c) return;
  if (S.admin.tab === 'users') return renderAdminUsers(c);
  if (S.admin.tab === 'defaults') return renderAdminDefaults(c);
  if (S.admin.tab === 'sec') return renderAdminSec(c);
}

function renderAdminUsers(c) {
  c.innerHTML = `
    <div class="sec-h">
      <div class="sec-title">المستخدمون <span>(${S.admin.users.length})</span></div>
      <button class="btn pri sm" id="adAddUser">${IC.plus} مستخدم</button>
    </div>
    <div id="adUsers"></div>
  `;
  const wrap = $('#adUsers');
  S.admin.users.forEach(u => {
    const card = el('div', 'ad-user-card');
    card.innerHTML = `
      <div class="ad-user-head">
        <div class="av">${esc((u.display||u.username||'?').charAt(0).toUpperCase())}</div>
        <div class="if">
          <b>${esc(u.display||u.username)}${u.banned?' <span class="pill bad">محظور</span>':''}${u.role==='owner'?' <span class="pill">إدارة</span>':''}</b>
          <small>@${esc(u.username)} · ${u.lim_kick ?? 'افتراضي'} / ${u.lim_yt ?? 'افتراضي'} / ${u.lim_tg ?? 'افتراضي'}</small>
        </div>
      </div>
      <div class="ad-user-acts">
        <button class="btn sm ghost" data-ua="edit">${IC.edit} تعديل</button>
        ${u.role!=='owner'?`<button class="btn sm ${u.banned?'ghost':'danger'}" data-ua="ban">${u.banned?'إلغاء الحظر':'حظر'}</button>`:''}
        ${u.role!=='owner'?`<button class="btn sm danger" data-ua="del">${IC.trash}</button>`:''}
      </div>
    `;
    card.querySelectorAll('[data-ua]').forEach(b => {
      b.onclick = () => adminUserAction(u, b.dataset.ua);
    });
    wrap.appendChild(card);
  });

  $('#adAddUser').onclick = adminAddUser;
}

async function adminAddUser() {
  const ok = await modal({
    title:'إنشاء مستخدم',
    html:`
      <label class="fld"><span>اسم المستخدم</span><input id="__un" placeholder="user123"></label>
      <label class="fld"><span>الاسم المعروض</span><input id="__dn"></label>
      <label class="fld"><span>كلمة المرور</span><input id="__pw" type="password"></label>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px">
        <label class="fld"><span>حد كيك</span><input id="__lk" type="number" placeholder="10"></label>
        <label class="fld"><span>حد يوتيوب</span><input id="__ly" type="number" placeholder="5"></label>
        <label class="fld"><span>حد تيليجرام</span><input id="__lt" type="number" placeholder="3"></label>
      </div>
    `,
    okText:'إنشاء'
  });
  if (!ok) return;
  try {
    await api('/api/admin/users', { method:'POST', body: {
      username: $('#__un').value.trim(),
      display: $('#__dn').value.trim(),
      password: $('#__pw').value,
      lim_kick: $('#__lk').value,
      lim_yt: $('#__ly').value,
      lim_tg: $('#__lt').value,
    }});
    toast('تم الإنشاء', 'ok');
    await loadAdminData();
    renderAdminContent();
  } catch (e) { toast(e.message, 'bad'); }
}

async function adminUserAction(u, act) {
  if (act === 'edit') {
    const ok = await modal({
      title:'تعديل ' + u.username,
      html:`
        <label class="fld"><span>الاسم المعروض</span><input id="__dn" value="${esc(u.display||'')}"></label>
        <label class="fld"><span>كلمة مرور جديدة (اتركها فارغة)</span><input id="__pw" type="password"></label>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px">
          <label class="fld"><span>حد كيك</span><input id="__lk" type="number" value="${u.lim_kick ?? ''}" placeholder="افتراضي"></label>
          <label class="fld"><span>حد يوتيوب</span><input id="__ly" type="number" value="${u.lim_yt ?? ''}" placeholder="افتراضي"></label>
          <label class="fld"><span>حد تيليجرام</span><input id="__lt" type="number" value="${u.lim_tg ?? ''}" placeholder="افتراضي"></label>
        </div>
      `,
      okText:'حفظ'
    });
    if (!ok) return;
    try {
      await api('/api/admin/users/' + u.id, { method:'PATCH', body: {
        display: $('#__dn').value,
        password: $('#__pw').value,
        lim_kick: $('#__lk').value,
        lim_yt: $('#__ly').value,
        lim_tg: $('#__lt').value,
      }});
      toast('تم الحفظ', 'ok');
      await loadAdminData();
      renderAdminContent();
    } catch (e) { toast(e.message, 'bad'); }
  } else if (act === 'ban') {
    try {
      await api('/api/admin/users/' + u.id, { method:'PATCH', body:{ banned: !u.banned }});
      toast('تم', 'ok');
      await loadAdminData();
      renderAdminContent();
    } catch (e) { toast(e.message, 'bad'); }
  } else if (act === 'del') {
    const ok = await dlgConfirm('حذف المستخدم وكل بياناته؟', 'تأكيد', true);
    if (!ok) return;
    try {
      await api('/api/admin/users/' + u.id, { method:'DELETE' });
      toast('تم الحذف', 'ok');
      await loadAdminData();
      renderAdminContent();
    } catch (e) { toast(e.message, 'bad'); }
  }
}

function renderAdminDefaults(c) {
  c.innerHTML = `
    <div class="sec-h">
      <div class="sec-title">القنوات الافتراضية <span>(${S.admin.defaults.length})</span></div>
      <button class="btn pri sm" id="adAddDef">${IC.plus} قناة</button>
    </div>
    <div class="sh-sub">تظهر هذه القنوات كمقترحات للمستخدمين عند الإضافة</div>
    <div id="adDefs"></div>
  `;
  const wrap = $('#adDefs');
  if (!S.admin.defaults.length) {
    wrap.innerHTML = `<div class="empty"><div class="em-icon">${IC.plus}</div><h3>لا توجد قنوات افتراضية</h3><p>أضف قنوات لتظهر للمستخدمين كمقترحات</p></div>`;
  } else {
    S.admin.defaults.forEach(d => {
      const card = el('div', 'ad-user-card');
      const kindLabel = d.kind === 'kick' ? 'كيك' : d.kind === 'yt' ? 'يوتيوب' : 'تيليجرام';
      card.innerHTML = `
        <div class="ad-user-head">
          <div class="av">${d.avatar ? `<img src="${esc(d.avatar)}" style="width:100%;height:100%;object-fit:cover;border-radius:inherit" onerror="this.remove()">` : esc((d.name||'?').charAt(0).toUpperCase())}</div>
          <div class="if">
            <b>${esc(d.name||d.identifier)}</b>
            <small>${esc(d.identifier)} · ${kindLabel} ${d.enabled?'':'· <span style="color:var(--red)">معطل</span>'}</small>
          </div>
        </div>
        <div class="ad-user-acts">
          <button class="btn sm ghost" data-da="toggle">${d.enabled?'إيقاف':'تفعيل'}</button>
          <button class="btn sm danger" data-da="del">${IC.trash} حذف</button>
        </div>
      `;
      card.querySelectorAll('[data-da]').forEach(b => {
        b.onclick = async () => {
          const act = b.dataset.da;
          if (act === 'del') {
            const ok = await dlgConfirm('حذف القناة الافتراضية؟', 'تأكيد', true);
            if (!ok) return;
            try {
              await api('/api/admin/default-channels/' + d.id, { method:'DELETE' });
              toast('تم', 'ok');
              await loadAdminData();
              renderAdminContent();
            } catch (e) { toast(e.message, 'bad'); }
          } else if (act === 'toggle') {
            try {
              await api('/api/admin/default-channels/' + d.id, { method:'PATCH', body:{ enabled: !d.enabled }});
              await loadAdminData();
              renderAdminContent();
            } catch (e) { toast(e.message, 'bad'); }
          }
        };
      });
      wrap.appendChild(card);
    });
  }

  $('#adAddDef').onclick = async () => {
    const ok = await modal({
      title:'إضافة قناة افتراضية',
      html:`
        <label class="fld"><span>النوع</span>
          <select id="__kd">
            <option value="kick">كيك</option>
            <option value="yt">يوتيوب</option>
            <option value="tg">تيليجرام</option>
          </select>
        </label>
        <label class="fld"><span>المعرّف (slug / channel_id / @username)</span><input id="__id" placeholder="xqc أو UC... أو @channel"></label>
        <label class="fld"><span>الاسم المعروض (اختياري)</span><input id="__nm"></label>
      `,
      okText:'إضافة'
    });
    if (!ok) return;
    try {
      await api('/api/admin/default-channels', { method:'POST', body: {
        kind: $('#__kd').value,
        identifier: $('#__id').value.trim(),
        name: $('#__nm').value.trim(),
      }});
      toast('تمت الإضافة', 'ok');
      await loadAdminData();
      renderAdminContent();
    } catch (e) { toast(e.message, 'bad'); }
  };
}

function renderAdminSec(c) {
  c.innerHTML = `
    <div class="sec-h"><div class="sec-title">الأمان <span>.</span></div></div>
    <div class="card" style="padding:18px">
      <ul style="list-style:none;padding:0;display:flex;flex-direction:column;gap:10px">
        <li style="display:flex;gap:10px;align-items:center"><span class="pill ok">نشط</span> PBKDF2 لتشفير كلمات المرور (100,000 دورة)</li>
        <li style="display:flex;gap:10px;align-items:center"><span class="pill ok">نشط</span> منع تكرار رسائل ديسكورد</li>
        <li style="display:flex;gap:10px;align-items:center"><span class="pill ok">نشط</span> Rate limiting لكل مستخدم</li>
        <li style="display:flex;gap:10px;align-items:center"><span class="pill ok">نشط</span> تحديث جماعي (batch) لتقليل الحمل</li>
        <li style="display:flex;gap:10px;align-items:center"><span class="pill ok">نشط</span> سجل أمني (5000 حدث)</li>
      </ul>
    </div>
  `;
}

/* ═══════════════════════════════════════════════════════
   BOOT
   ═══════════════════════════════════════════════════════ */
boot();
</script>
</body>
</html>
