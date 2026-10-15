"""
Respect Live — نظام مراقبة قنوات البث + بوت ديسكورد
FastAPI + Discord.py + SQLite + APScheduler
"""
import os, re, json, time, hashlib, secrets, sqlite3, asyncio, html
from datetime import datetime
from contextlib import asynccontextmanager

import httpx
import discord
from fastapi import FastAPI, Request, Response, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════
#                        CONFIG
# ═══════════════════════════════════════════════════════════
ADMIN_USERNAME   = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD   = os.getenv("ADMIN_PASSWORD", "changeme")
SESSION_SECRET   = os.getenv("SESSION_SECRET", secrets.token_hex(32))
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
DISCORD_TOKEN    = os.getenv("DISCORD_BOT_TOKEN", "")
WATCH_CHANNELS   = [c.strip() for c in os.getenv("DISCORD_WATCH_CHANNELS", "").split(",") if c.strip()]
SITE_NAME        = os.getenv("SITE_NAME", "Respect Live")
DB_PATH          = os.getenv("DB_PATH", "respect.db")
SESSION_TTL      = 7 * 24 * 3600
UA               = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"


# ═══════════════════════════════════════════════════════════
#                       DATABASE
# ═══════════════════════════════════════════════════════════
def db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
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
CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS kick_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL,
    name TEXT DEFAULT '', avatar TEXT DEFAULT '', banner TEXT DEFAULT '',
    msg TEXT DEFAULT '', enabled INTEGER DEFAULT 1, live INTEGER DEFAULT 0,
    title TEXT DEFAULT '', viewers INTEGER DEFAULT 0, thumb TEXT DEFAULT '',
    last_check INTEGER DEFAULT 0, added_by TEXT NOT NULL, created INTEGER,
    UNIQUE(slug, added_by)
);
CREATE TABLE IF NOT EXISTS yt_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL, handle TEXT DEFAULT '', name TEXT DEFAULT '',
    avatar TEXT DEFAULT '', msg TEXT DEFAULT '', enabled INTEGER DEFAULT 1,
    last_video TEXT DEFAULT '', last_check INTEGER DEFAULT 0,
    added_by TEXT NOT NULL, created INTEGER, UNIQUE(channel_id, added_by)
);
CREATE TABLE IF NOT EXISTS tg_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL, username TEXT DEFAULT '', name TEXT DEFAULT '',
    avatar TEXT DEFAULT '', enabled INTEGER DEFAULT 1,
    added_by TEXT NOT NULL, created INTEGER, UNIQUE(chat_id, added_by)
);
CREATE TABLE IF NOT EXISTS notifs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL, title TEXT DEFAULT '', body TEXT DEFAULT '',
    image TEXT DEFAULT '', btn_text TEXT DEFAULT '', btn_url TEXT DEFAULT '',
    kind TEXT DEFAULT 'admin', ts INTEGER, is_read INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS discord_feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL, channel_name TEXT DEFAULT '',
    template TEXT DEFAULT '', enabled INTEGER DEFAULT 1,
    added_by TEXT NOT NULL, created INTEGER,
    UNIQUE(channel_id, added_by)
);
CREATE TABLE IF NOT EXISTS discord_seen (
    message_id TEXT PRIMARY KEY, ts INTEGER
);
CREATE TABLE IF NOT EXISTS recent_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL, ch_name TEXT DEFAULT '', title TEXT DEFAULT '',
    thumb TEXT DEFAULT '', url TEXT DEFAULT '', ts INTEGER,
    added_by TEXT NOT NULL, UNIQUE(video_id, added_by)
);
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
    # إعدادات افتراضية
    for k, v in {
        "site_name": SITE_NAME,
        "tpl_kick": "<b>{name}</b>\nبدأ بثاً مباشراً الآن\n\n<b>{title}</b>",
        "tpl_yt": "<b>{name}</b>\nنشر فيديو جديداً\n\n<b>{title}</b>",
        "tpl_discord": "<b>{author}</b>\n{content}",
        "btn_kick": "شاهد البث",
        "btn_yt": "شاهد الفيديو",
    }.items():
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
    c.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
    c.commit()
    c.close()


def hash_pw(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 100000).hex()


# ═══════════════════════════════════════════════════════════
#                        AUTH
# ═══════════════════════════════════════════════════════════
def auth(request: Request) -> dict | None:
    tok = request.cookies.get("rl_sid")
    if not tok:
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


# ═══════════════════════════════════════════════════════════
#                     TELEGRAM
# ═══════════════════════════════════════════════════════════
async def tg_send(chat_id: str, text: str, image: str = "", btn: str = "", url: str = "") -> bool:
    if not TELEGRAM_TOKEN:
        return False
    markup = {"inline_keyboard": [[{"text": btn[:60], "url": url}]]} if (btn and url) else None
    base = {"chat_id": str(chat_id), "parse_mode": "HTML"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            if image:
                r = await c.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                    json={**base, "photo": image, "caption": (text or ".")[:1024], "reply_markup": markup},
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


# ═══════════════════════════════════════════════════════════
#                        KICK
# ═══════════════════════════════════════════════════════════
async def kick_fetch(slug: str) -> dict | None:
    h = {"User-Agent": UA, "Accept": "application/json", "Referer": "https://kick.com/"}
    async with httpx.AsyncClient(timeout=15, headers=h) as c:
        for v in ("v2", "v1"):
            try:
                r = await c.get(f"https://kick.com/api/{v}/channels/{slug}")
                if r.status_code != 200:
                    continue
                j = r.json()
                ls = j.get("livestream") or {}
                u = j.get("user") or {}
                return {
                    "name": u.get("username") or slug,
                    "avatar": u.get("profile_pic") or "",
                    "banner": j.get("banner_image") or "",
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
async def yt_feed(channel_id: str) -> list | None:
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


# ═══════════════════════════════════════════════════════════
#                    DISCORD BOT
# ═══════════════════════════════════════════════════════════
discord_client = discord.Client(intents=discord.Intents.all())


@discord_client.event
async def on_ready():
    print(f"[Discord] ✅ Logged in as {discord_client.user}")
    print(f"[Discord] Watching {len(WATCH_CHANNELS)} channels: {WATCH_CHANNELS}")


@discord_client.event
async def on_message(msg: discord.Message):
    ch_id = str(msg.channel.id)
    if ch_id not in WATCH_CHANNELS:
        return
    # ✅ منع التكرار (حتى لو أُعيد تشغيل البوت)
    c = db()
    if c.execute("SELECT 1 FROM discord_seen WHERE message_id=?", (str(msg.id),)).fetchone():
        c.close()
        return
    c.execute("INSERT INTO discord_seen(message_id,ts) VALUES(?,?)", (str(msg.id), now()))
    c.commit()

    # استخراج المحتوى
    author = msg.author.display_name or msg.author.name
    content = msg.content or ""
    image = ""
    url = ""
    if msg.embeds:
        e = msg.embeds[0]
        if e.image and e.image.url:
            image = e.image.url
        elif e.thumbnail and e.thumbnail.url:
            image = e.thumbnail.url
        if e.url:
            url = e.url
        if not content:
            content = (e.title or "") + ("\n" + e.description if e.description else "")
    if not image and msg.attachments:
        for a in msg.attachments:
            if a.content_type and a.content_type.startswith("image/"):
                image = a.url
                break

    content = content.strip()[:2000]

    # ابحث عن feeds مرتبطة بهذه القناة
    feeds = c.execute(
        "SELECT * FROM discord_feeds WHERE channel_id=? AND enabled=1", (ch_id,)
    ).fetchall()
    c.close()

    for feed in feeds:
        tpl = feed["template"] or cfg("tpl_discord")
        text = (tpl
                .replace("{author}", author)
                .replace("{content}", content)
                .replace("{channel}", getattr(msg.channel, "name", "") or ""))
        # أرسل لقنوات صاحب الـ feed
        c2 = db()
        tgs = c2.execute(
            "SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (feed["added_by"],)
        ).fetchall()
        c2.close()
        for tg in tgs:
            await tg_send(tg["chat_id"], text, image, "عرض", url)


# ═══════════════════════════════════════════════════════════
#                  BACKGROUND JOBS
# ═══════════════════════════════════════════════════════════
async def job_kick():
    c = db()
    rows = c.execute(
        "SELECT * FROM kick_channels WHERE enabled=1 AND last_check<? LIMIT 30",
        (now() - 90,),
    ).fetchall()
    c.close()
    for r in rows:
        info = await kick_fetch(r["slug"])
        if not info:
            continue
        c = db()
        was = r["live"]
        c.execute(
            "UPDATE kick_channels SET name=?,avatar=?,banner=?,live=?,title=?,viewers=?,thumb=?,last_check=? WHERE id=?",
            (info["name"], info["avatar"], info["banner"], 1 if info["live"] else 0,
             info["title"], info["viewers"], info["thumb"], now(), r["id"]),
        )
        c.commit()
        if info["live"] and not was:
            tpl = r["msg"] or cfg("tpl_kick")
            text = (tpl
                    .replace("{name}", info["name"])
                    .replace("{title}", info["title"])
                    .replace("{url}", f"https://kick.com/{r['slug']}"))
            for tg in c.execute(
                "SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (r["added_by"],)
            ).fetchall():
                await tg_send(tg["chat_id"], text, info["banner"] or info["thumb"],
                              cfg("btn_kick"), f"https://kick.com/{r['slug']}")
        c.close()


async def job_yt():
    c = db()
    rows = c.execute(
        "SELECT * FROM yt_channels WHERE enabled=1 AND last_check<? LIMIT 30",
        (now() - 300,),
    ).fetchall()
    c.close()
    for r in rows:
        items = await yt_feed(r["channel_id"])
        c = db()
        c.execute("UPDATE yt_channels SET last_check=? WHERE id=?", (now(), r["id"]))
        c.commit()
        if not items:
            c.close()
            continue
        latest = items[0]["id"]
        if r["last_video"] and latest != r["last_video"]:
            fresh = []
            for it in items:
                if it["id"] == r["last_video"]:
                    break
                fresh.append(it)
            for v in reversed(fresh[:3]):
                thumb = f"https://i.ytimg.com/vi/{v['id']}/maxresdefault.jpg"
                tpl = r["msg"] or cfg("tpl_yt")
                text = (tpl
                        .replace("{name}", r["name"])
                        .replace("{title}", v["title"])
                        .replace("{url}", f"https://youtube.com/watch?v={v['id']}"))
                for tg in c.execute(
                    "SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (r["added_by"],)
                ).fetchall():
                    await tg_send(tg["chat_id"], text, thumb, cfg("btn_yt"),
                                  f"https://youtube.com/watch?v={v['id']}")
                c.execute(
                    "INSERT OR IGNORE INTO recent_videos(video_id,ch_name,title,thumb,url,ts,added_by) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (v["id"], r["name"], v["title"], thumb,
                     f"https://youtube.com/watch?v={v['id']}", now(), r["added_by"]),
                )
        c.execute("UPDATE yt_channels SET last_video=? WHERE id=?", (latest, r["id"]))
        c.commit()
        c.close()


async def job_cleanup():
    c = db()
    c.execute("DELETE FROM discord_seen WHERE ts<?", (now() - 7 * 86400,))
    c.execute("DELETE FROM sessions WHERE expires<?", (now(),))
    c.execute("DELETE FROM recent_videos WHERE id IN "
              "(SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY added_by ORDER BY ts DESC) rn "
              "FROM recent_videos) WHERE rn>12)")
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
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)


# ─────────────────────── AUTH ROUTES ───────────────────────
@app.post("/api/login")
async def login(response: Response, u: str = Form(...), p: str = Form(...)):
    u = u.strip()
    c = db()
    row = c.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
    c.close()
    if not row:
        return JSONResponse({"error": "بيانات خاطئة"}, 401)
    row = dict(row)
    if row["banned"]:
        return JSONResponse({"error": "حساب محظور"}, 403)
    if not secrets.compare_digest(hash_pw(p, row["salt"]), row["pass_hash"]):
        return JSONResponse({"error": "بيانات خاطئة"}, 401)
    tok = new_session(row["username"])
    c = db()
    c.execute("UPDATE users SET last_login=? WHERE id=?", (now(), row["id"]))
    c.commit()
    c.close()
    response.set_cookie("rl_sid", tok, max_age=SESSION_TTL, httponly=True, samesite="lax")
    return {"ok": True, "user": {"username": row["username"], "role": row["role"]}}


@app.post("/api/register")
async def register(response: Response, u: str = Form(...), p: str = Form(...)):
    u = u.strip()
    if len(u) < 3 or len(p) < 4:
        return JSONResponse({"error": "الاسم 3+ وكلمة المرور 4+"}, 400)
    c = db()
    if c.execute("SELECT 1 FROM users WHERE username=?", (u,)).fetchone():
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
    response.set_cookie("rl_sid", tok, max_age=SESSION_TTL, httponly=True, samesite="lax")
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
    return {
        "user": {"username": u["username"], "display": u["display"], "role": u["role"]},
        "site_name": cfg("site_name", SITE_NAME),
        "has_telegram": bool(TELEGRAM_TOKEN),
        "has_discord": bool(DISCORD_TOKEN),
    }


# ─────────────────────── CHANNELS API ───────────────────────
def require_auth(request: Request):
    u = auth(request)
    if not u:
        raise HTTPException(401, "غير مسجل")
    return u


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
    return {"rows": [dict(r) for r in rows]}


@app.post("/api/channels/{kind}")
async def add_channel(kind: str, request: Request):
    u = require_auth(request)
    body = await request.json()
    c = db()
    t = now()
    if kind == "kick":
        slug = re.sub(r"[^a-z0-9_-]", "", (body.get("slug") or "").lower().replace("@", ""))
        if not slug:
            return JSONResponse({"error": "اسم غير صالح"}, 400)
        if c.execute("SELECT 1 FROM kick_channels WHERE slug=? AND added_by=?", (slug, u["username"])).fetchone():
            c.close()
            return JSONResponse({"error": "مضافة مسبقاً"}, 409)
        info = await kick_fetch(slug)
        c.execute(
            "INSERT INTO kick_channels(slug,name,avatar,banner,msg,enabled,live,title,viewers,thumb,last_check,added_by,created) "
            "VALUES(?,?,?,?,?,1,?,?,?,?,?,?,?)",
            (slug, (info or {}).get("name") or slug, (info or {}).get("avatar") or "",
             (info or {}).get("banner") or "", body.get("msg", ""),
             1 if (info or {}).get("live") else 0, (info or {}).get("title") or "",
             (info or {}).get("viewers") or 0, (info or {}).get("thumb") or "",
             t, u["username"], t),
        )
    elif kind == "yt":
        cid = body.get("channel_id") or ""
        m = re.search(r"UC[\w-]{22}", cid)
        if not m:
            return JSONResponse({"error": "Channel ID غير صالح (UC...)"}, 400)
        cid = m.group(0)
        if c.execute("SELECT 1 FROM yt_channels WHERE channel_id=? AND added_by=?", (cid, u["username"])).fetchone():
            c.close()
            return JSONResponse({"error": "مضافة مسبقاً"}, 409)
        feed = await yt_feed(cid)
        last = feed[0]["id"] if feed else ""
        name = body.get("name") or cid
        c.execute(
            "INSERT INTO yt_channels(channel_id,handle,name,avatar,msg,enabled,last_video,last_check,added_by,created) "
            "VALUES(?,?,?,?,?,1,?,?,?,?)",
            (cid, "", name, "", body.get("msg", ""), last, t, u["username"], t),
        )
    elif kind == "tg":
        cid = (body.get("chat_id") or "").strip()
        if not cid:
            return JSONResponse({"error": "chat_id مطلوب"}, 400)
        if c.execute("SELECT 1 FROM tg_channels WHERE chat_id=? AND added_by=?", (cid, u["username"])).fetchone():
            c.close()
            return JSONResponse({"error": "مضافة مسبقاً"}, 409)
        c.execute(
            "INSERT INTO tg_channels(chat_id,username,name,avatar,enabled,added_by,created) "
            "VALUES(?,?,?,?,1,?,?)",
            (cid, "", body.get("name") or cid, "", u["username"], t),
        )
    else:
        c.close()
        raise HTTPException(404)
    c.commit()
    c.close()
    return {"ok": True}


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


# ─────────────────────── DISCORD FEEDS ───────────────────────
@app.get("/api/discord/feeds")
async def list_feeds(request: Request):
    u = require_auth(request)
    c = db()
    rows = c.execute(
        "SELECT * FROM discord_feeds WHERE added_by=? ORDER BY id DESC", (u["username"],)
    ).fetchall()
    c.close()
    # احصل على أسماء القنوات من البوت
    known = {}
    if discord_client.is_ready():
        for ch in discord_client.get_all_channels():
            known[str(ch.id)] = ch.name
    return {"rows": [dict(r) for r in rows], "known_channels": known,
            "watching": WATCH_CHANNELS}


@app.post("/api/discord/feeds")
async def add_feed(request: Request):
    u = require_auth(request)
    body = await request.json()
    ch = str(body.get("channel_id") or "").strip()
    if not ch:
        return JSONResponse({"error": "channel_id مطلوب"}, 400)
    tpl = str(body.get("template") or "")[:2000]
    name = str(body.get("channel_name") or "")[:100]
    c = db()
    if c.execute("SELECT 1 FROM discord_feeds WHERE channel_id=? AND added_by=?",
                 (ch, u["username"])).fetchone():
        c.close()
        return JSONResponse({"error": "مضاف مسبقاً"}, 409)
    c.execute(
        "INSERT INTO discord_feeds(channel_id,channel_name,template,enabled,added_by,created) "
        "VALUES(?,?,?,1,?,?)",
        (ch, name, tpl, u["username"], now()),
    )
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


# ─────────────────────── SETTINGS ───────────────────────
@app.get("/api/settings")
async def get_settings(request: Request):
    u = require_auth(request)
    return {
        "site_name": cfg("site_name", SITE_NAME),
        "tpl_kick": cfg("tpl_kick"),
        "tpl_yt": cfg("tpl_yt"),
        "tpl_discord": cfg("tpl_discord"),
        "btn_kick": cfg("btn_kick"),
        "btn_yt": cfg("btn_yt"),
        "has_telegram": bool(TELEGRAM_TOKEN),
    }


@app.post("/api/settings")
async def save_settings(request: Request):
    u = require_auth(request)
    if u["role"] != "owner":
        raise HTTPException(403)
    body = await request.json()
    for k in ("site_name", "tpl_kick", "tpl_yt", "tpl_discord", "btn_kick", "btn_yt"):
        if k in body:
            set_cfg(k, str(body[k])[:2000])
    return {"ok": True}


# ═══════════════════════════════════════════════════════════
#                    HTML PAGE
# ═══════════════════════════════════════════════════════════
HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Respect Live</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Tajawal:wght@400;500;700;900&display=swap');
:root{--blue:#0b55ea;--blue2:#1b67ff;--bg:#030508;--panel:#0a0f18;--card:linear-gradient(145deg,#0c1119,#040609);--text:#f4f6fa;--muted:#7c8799;--line:rgba(255,255,255,.08);--green:#10b981;--red:#ef4444;--gold:#f5b400;--glow:0 0 30px rgba(11,85,234,.35);--fn:"Tajawal",sans-serif;--fe:"Orbitron",sans-serif}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{background:var(--bg);color:var(--text);font-family:var(--fn);min-height:100vh;padding-bottom:100px;overflow-x:hidden}
body::before{content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;background:radial-gradient(circle at 15% 20%,rgba(11,85,234,.12),transparent 45%),radial-gradient(circle at 85% 75%,rgba(11,85,234,.10),transparent 45%)}
body::after{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;background-image:linear-gradient(rgba(11,85,234,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(11,85,234,.04) 1px,transparent 1px);background-size:60px 60px;-webkit-mask-image:radial-gradient(ellipse 80% 60% at 50% 40%,#000,transparent 85%);mask-image:radial-gradient(ellipse 80% 60% at 50% 40%,#000,transparent 85%)}
a{color:inherit;text-decoration:none}button{font:inherit;cursor:pointer;border:none;background:none;color:inherit}
input,textarea,select{font:inherit;color:var(--text);background:rgba(5,8,16,.7);border:1px solid rgba(11,85,234,.25);border-radius:12px;padding:12px 14px;width:100%;outline:none;transition:.2s}
input:focus,textarea:focus,select:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(11,85,234,.18)}
.hide{display:none!important}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px;position:relative;box-shadow:0 15px 40px rgba(0,0,0,.35)}
.card::before{content:"";position:absolute;top:10px;left:10px;width:14px;height:14px;border-top:2px solid var(--blue);border-left:2px solid var(--blue);opacity:.5;border-radius:4px 0 0 0}
.card::after{content:"";position:absolute;bottom:10px;right:10px;width:14px;height:14px;border-bottom:2px solid var(--blue);border-right:2px solid var(--blue);opacity:.5;border-radius:0 0 4px 0}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:12px 22px;border-radius:12px;background:rgba(255,255,255,.04);border:1px solid var(--line);color:var(--text);font-weight:800;font-size:13.5px;transition:.25s cubic-bezier(.16,1,.3,1);cursor:pointer}
.btn:hover{transform:translateY(-2px);border-color:var(--blue)}
.btn:active{transform:scale(.97)}
.btn.pri{background:var(--blue);border-color:var(--blue);color:#fff;box-shadow:0 10px 30px rgba(11,85,234,.3)}
.btn.danger{background:var(--red);border-color:var(--red);color:#fff}
.btn.ghost{background:transparent}
.btn.sm{padding:8px 14px;font-size:12px;border-radius:10px}
.btn.wide{width:100%;padding:14px}
.header{position:sticky;top:0;z-index:50;padding:14px 6%;display:flex;align-items:center;gap:14px;background:linear-gradient(rgba(3,5,8,.94) 60%,transparent);backdrop-filter:blur(14px);border-bottom:1px solid transparent;transition:border-color .3s}
.header.scrolled{border-bottom-color:var(--line)}
.brand{display:flex;align-items:center;gap:10px;flex:1;min-width:0}
.brand-logo{width:42px;height:42px;border-radius:12px;background:linear-gradient(135deg,var(--blue),var(--blue2));display:grid;place-items:center;flex-shrink:0;box-shadow:var(--glow)}
.brand-logo svg{width:22px;height:22px;color:#fff}
.brand-name{font-family:var(--fe);font-size:16px;font-weight:900;letter-spacing:2px}
.brand-name span{color:var(--blue)}
.brand-sub{font-size:9.5px;color:var(--muted);letter-spacing:1.5px;font-family:var(--fe);font-weight:700}
.avatar{width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,var(--blue),var(--blue2));display:grid;place-items:center;color:#fff;font-weight:900;font-family:var(--fe);cursor:pointer;position:relative;box-shadow:0 0 15px rgba(11,85,234,.4)}
.avatar .status{position:absolute;bottom:0;right:0;width:11px;height:11px;border-radius:50%;background:var(--green);border:2px solid var(--bg)}
.hero{padding:50px 6% 40px;text-align:center;animation:fadeIn .6s cubic-bezier(.16,1,.3,1)}
.hero h1{font-family:var(--fe);font-size:clamp(34px,7vw,64px);line-height:.9;letter-spacing:3px;font-weight:900;margin:14px 0}
.hero h1 span{color:var(--blue);text-shadow:var(--glow);display:inline-block;transform:skewX(-8deg)}
.hero p{color:var(--muted);font-size:14px;max-width:500px;margin:0 auto 22px;line-height:1.8}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-radius:16px;overflow:hidden;margin:22px 6%}
.stat{background:var(--panel);padding:16px 8px;text-align:center}
.stat b{display:block;font-family:var(--fe);font-size:24px;font-weight:900;color:var(--blue)}
.stat small{font-size:11px;color:var(--muted);font-family:var(--fe);letter-spacing:1.5px}
.tabs{display:flex;gap:8px;padding:20px 6% 4px;overflow-x:auto;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tab{flex-shrink:0;padding:10px 18px;border-radius:22px;background:rgba(255,255,255,.04);border:1px solid var(--line);color:var(--muted);font-weight:800;font-size:12.5px;cursor:pointer;transition:.25s;display:inline-flex;align-items:center;gap:7px}
.tab:hover{color:var(--text);border-color:var(--blue)}
.tab.on{background:var(--blue);color:#fff;border-color:var(--blue);box-shadow:0 6px 18px rgba(11,85,234,.4)}
.tab .cnt{background:rgba(255,255,255,.15);border-radius:10px;padding:0 7px;font-size:10.5px;font-family:var(--fe);font-weight:900;min-width:20px;line-height:18px}
.tab.on .cnt{background:rgba(0,0,0,.25)}
.section{padding:22px 6%;animation:fadeIn .45s cubic-bezier(.16,1,.3,1)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.ch-card{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;position:relative;transition:.3s cubic-bezier(.16,1,.3,1)}
.ch-card:hover{transform:translateY(-3px);border-color:rgba(11,85,234,.4);box-shadow:0 15px 40px rgba(11,85,234,.15)}
.ch-cover{height:110px;position:relative;overflow:hidden;background:linear-gradient(135deg,rgba(11,85,234,.25),rgba(0,0,0,.4))}
.ch-cover img{width:100%;height:100%;object-fit:cover}
.ch-cover::after{content:"";position:absolute;inset:0;background:linear-gradient(transparent 40%,rgba(3,5,8,.9))}
.badge{position:absolute;top:10px;right:10px;z-index:3;font-size:10.5px;padding:5px 10px;border-radius:8px;font-weight:900;font-family:var(--fe);letter-spacing:.5px}
.badge.live{background:var(--red);color:#fff;animation:pulse 1.8s infinite}
@keyframes pulse{70%{box-shadow:0 0 0 12px rgba(239,68,68,0)}100%{box-shadow:0 0 0 0 rgba(239,68,68,0)}}
.badge.off{background:rgba(255,255,255,.15);color:var(--text)}
.ch-head{display:flex;align-items:flex-end;gap:12px;padding:0 16px;margin-top:-26px;position:relative;z-index:2}
.ch-head img{width:54px;height:54px;border-radius:14px;object-fit:cover;border:3px solid var(--bg);background:var(--panel);box-shadow:0 0 15px rgba(11,85,234,.35)}
.ch-info{flex:1;min-width:0}
.ch-info b{display:block;font-size:15.5px;font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ch-info small{color:var(--muted);font-size:11px;font-family:var(--fe);letter-spacing:1px}
.ch-live{margin:10px 16px 0;padding:10px 14px;border-radius:10px;background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.3);font-size:12px;display:flex;justify-content:space-between;font-weight:800}
.ch-live span{color:#f87171}
.ch-acts{display:flex;gap:8px;flex-wrap:wrap;padding:14px 16px 16px}
.empty{text-align:center;padding:60px 20px;color:var(--muted)}
.empty svg{width:90px;height:90px;opacity:.3;margin-bottom:16px;color:var(--blue)}
.empty h3{font-size:16px;color:var(--text);margin-bottom:6px}
.empty p{font-size:13px;margin-bottom:16px}
.tabbar{position:fixed;bottom:calc(16px + env(safe-area-inset-bottom));left:50%;transform:translateX(-50%);width:92%;max-width:460px;height:64px;background:rgba(10,15,24,.94);backdrop-filter:blur(22px);border:1px solid var(--line);border-radius:34px;display:flex;justify-content:space-around;align-items:center;z-index:100;padding:0 10px;box-shadow:0 20px 40px rgba(0,0,0,.6)}
.tabbar button{width:52px;height:52px;border-radius:50%;display:grid;place-items:center;color:var(--muted);transition:.3s cubic-bezier(.4,0,.2,1);position:relative}
.tabbar button svg{width:22px;height:22px;color:currentColor;transition:.3s cubic-bezier(.4,0,.2,1)}
.tabbar button:hover{color:var(--text);background:rgba(255,255,255,.03)}
.tabbar button.on{color:var(--blue2)}
.tabbar button.on svg{transform:translateY(-2px) scale(1.15);filter:drop-shadow(0 0 8px var(--blue))}
.tabbar button.on::after{content:"";position:absolute;bottom:0;left:50%;transform:translateX(-50%);width:20px;height:3px;background:var(--blue);border-radius:3px}
.modal{position:fixed;inset:0;z-index:500;background:rgba(3,5,8,.8);backdrop-filter:blur(12px);display:flex;align-items:flex-end;justify-content:center;padding-top:40px;opacity:0;pointer-events:none;transition:opacity .3s}
.modal.on{opacity:1;pointer-events:auto}
.sheet{width:min(620px,100%);max-height:92vh;overflow:auto;background:var(--card);border:1px solid var(--line);border-bottom:0;border-radius:26px 26px 0 0;padding:20px 22px calc(26px + env(safe-area-inset-bottom));transform:translateY(60px);transition:transform .35s cubic-bezier(.2,.9,.3,1);position:relative}
.modal.on .sheet{transform:translateY(0)}
.sheet::before{content:"";position:absolute;top:0;left:20%;right:20%;height:2px;background:linear-gradient(90deg,transparent,var(--blue),transparent)}
.grab{width:44px;height:4px;border-radius:9px;background:rgba(255,255,255,.22);margin:0 auto 16px}
@media(min-width:701px){.modal{align-items:center}.sheet{border-radius:22px;border-bottom:1px solid var(--line)}}
.sheet h3{font-family:var(--fe);letter-spacing:1px;font-size:16px;margin-bottom:16px;color:var(--blue)}
.fld{display:block;margin:14px 0}
.fld>span{display:block;font-size:12.5px;color:var(--muted);margin-bottom:7px;font-weight:800}
.row{display:flex;gap:10px;margin-top:18px}
.row>.btn{flex:1}
.toasts{position:fixed;top:16px;left:0;right:0;z-index:900;display:flex;flex-direction:column;align-items:center;gap:8px;pointer-events:none}
.toast{max-width:min(440px,calc(100% - 30px));padding:13px 20px;border-radius:12px;font-size:13px;font-weight:800;background:var(--card);border:1px solid var(--line);backdrop-filter:blur(12px);box-shadow:0 15px 40px rgba(0,0,0,.5);opacity:0;transform:translateY(-16px);transition:.3s cubic-bezier(.2,.9,.3,1.2);position:relative;overflow:hidden;text-align:center;color:var(--text)}
.toast::before{content:"";position:absolute;top:0;bottom:0;right:0;width:4px;background:var(--blue)}
.toast.ok::before{background:var(--green)}
.toast.bad::before{background:var(--red)}
.toast.on{opacity:1;transform:translateY(0)}
.splash{position:fixed;inset:0;z-index:2000;display:grid;place-items:center;background:radial-gradient(circle at 50% 40%,rgba(11,85,234,.18),transparent 60%),var(--bg);transition:opacity .7s cubic-bezier(.16,1,.3,1),transform .7s}
.splash.out{opacity:0;transform:scale(1.06);pointer-events:none}
.splash-logo{width:100px;height:100px;border-radius:26px;background:linear-gradient(135deg,var(--blue),var(--blue2));display:grid;place-items:center;box-shadow:0 0 0 0 rgba(11,85,234,.6),0 20px 60px rgba(11,85,234,.5);animation:glow 2.2s infinite;margin:0 auto 26px}
.splash-logo svg{width:52px;height:52px;color:#fff}
@keyframes glow{70%{box-shadow:0 0 0 32px rgba(11,85,234,0),0 20px 60px rgba(11,85,234,.5)}}
.dots{display:flex;gap:8px;justify-content:center}
.dots i{width:10px;height:10px;border-radius:50%;background:var(--blue);animation:bounce 1.4s infinite;box-shadow:0 0 12px rgba(11,85,234,.6)}
.dots i:nth-child(2){animation-delay:.18s}
.dots i:nth-child(3){animation-delay:.36s}
@keyframes bounce{0%,80%,100%{transform:scale(.4);opacity:.35}40%{transform:scale(1);opacity:1}}
.login-wrap{min-height:100vh;display:grid;place-items:center;padding:20px}
.login-card{width:min(420px,100%);padding:36px 28px;background:var(--card);border:1px solid var(--line);border-radius:22px;position:relative;box-shadow:0 30px 60px rgba(0,0,0,.6);animation:slideUp .5s cubic-bezier(.16,1,.3,1)}
.login-card::before{content:"";position:absolute;top:0;left:20%;right:20%;height:2px;background:linear-gradient(90deg,transparent,var(--blue),transparent)}
@keyframes slideUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
.login-logo{width:80px;height:80px;border-radius:22px;margin:0 auto 16px;background:linear-gradient(135deg,var(--blue),var(--blue2));display:grid;place-items:center;box-shadow:0 0 30px rgba(11,85,234,.5)}
.login-logo svg{width:40px;height:40px;color:#fff}
.login-head{text-align:center;margin-bottom:22px}
.login-head h1{font-family:var(--fe);font-size:20px;letter-spacing:3px;font-weight:900;margin-bottom:6px}
.login-head h1 span{color:var(--blue);text-shadow:var(--glow)}
.login-head p{color:var(--muted);font-size:12.5px}
.err{color:#f87171;font-size:12.5px;text-align:center;min-height:20px;margin-top:8px}
.lb-row{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:12px;background:rgba(255,255,255,.02);border:1px solid var(--line);margin-bottom:8px}
.lb-rank{font-family:var(--fe);font-size:13px;font-weight:900;color:var(--muted);width:32px}
.lb-avatar{width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,var(--blue),var(--blue2));display:grid;place-items:center;color:#fff;font-weight:900;font-family:var(--fe)}
.lb-name{flex:1;font-weight:800}
.lb-pts{font-family:var(--fe);font-weight:900;color:var(--blue);font-size:15px}
@keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.fade{animation:fadeIn .4s cubic-bezier(.16,1,.3,1)}
.notif-row{display:flex;gap:12px;padding:14px;border-radius:14px;margin:10px 0;background:var(--panel);border:1px solid var(--line)}
.notif-row.un{background:rgba(11,85,234,.08);border-color:rgba(11,85,234,.3)}
.notif-row b{display:block;font-size:13.5px;font-weight:900}
.notif-row p{font-size:12.5px;color:#d5d8e8;margin-top:4px;line-height:1.7;white-space:pre-wrap}
.chip{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;border-radius:16px;background:rgba(11,85,234,.12);border:1px solid rgba(11,85,234,.3);color:var(--blue);font-size:11px;font-weight:900;font-family:var(--fe);letter-spacing:.5px}
.chip.green{background:rgba(16,185,129,.12);border-color:rgba(16,185,129,.3);color:var(--green)}
.chip.red{background:rgba(239,68,68,.12);border-color:rgba(239,68,68,.3);color:var(--red)}
</style>
</head>
<body>

<div class="splash" id="splash">
  <div style="text-align:center">
    <div class="splash-logo"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M11.35 2.76a1 1 0 0 1 1.3 0l9 7.5a1 1 0 0 1 .35.74V20a2 2 0 0 1-2 2h-4.5a1 1 0 0 1-1-1v-4h-3v4a1 1 0 0 1-1 1H5a2 2 0 0 1-2-2v-8.99a1 1 0 0 1 .35-.75l8-7.5z"/></svg></div>
    <div class="dots"><i></i><i></i><i></i></div>
  </div>
</div>

<div id="app"></div>
<div class="toasts" id="toasts"></div>
<div class="modal" id="modal"><div class="sheet" id="sheet"></div></div>

<script>
'use strict';
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const api = async (p, o={}) => {
  const r = await fetch(p, { credentials:'include', headers:{'content-type': o.body?'application/json':undefined}, ...o, body: o.body?JSON.stringify(o.body):undefined });
  const j = await r.json().catch(()=>({}));
  if (!r.ok) throw new Error(j.error || j.detail || 'خطأ');
  return j;
};
const toast = (msg, kind) => {
  const e = document.createElement('div');
  e.className = 'toast ' + (kind||'');
  e.textContent = msg;
  $('#toasts').appendChild(e);
  requestAnimationFrame(() => e.classList.add('on'));
  setTimeout(() => { e.classList.remove('on'); setTimeout(()=>e.remove(),400); }, 3200);
};

const S = {
  user: null, view: 'home', kind: 'kick', channels: {kick:[],yt:[],tg:[]}, feeds:[], known:{}, watching: [], settings: {},
};

const ICONS = {
  home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M3 12l9-9 9 9M5 10v10a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V10"/></svg>',
  kick: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 2h4.5v6.5L14 2h5.5L13 10.5l7 11.5h-5.6l-4.6-7.6-1.3 1.3V22H4z"/></svg>',
  yt: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M23 12s0-3.8-.5-5.6a2.9 2.9 0 0 0-2-2C18.7 4 12 4 12 4s-6.7 0-8.5.4a2.9 2.9 0 0 0-2 2C1 8.2 1 12 1 12s0 3.8.5 5.6c.3 1 1.1 1.8 2 2 1.8.4 8.5.4 8.5.4s6.7 0 8.5-.4c1-.3 1.8-1 2-2 .5-1.8.5-5.6.5-5.6zM9.75 15.5v-7l6.25 3.5-6.25 3.5z"/></svg>',
  tg: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M22.05 3.1 2.44 10.66c-1.03.4-1.02 1.83.01 2.21l4.76 1.76 1.83 5.85c.28.9 1.42 1.13 2.02.4l2.4-2.94 5.06 3.72c.66.48 1.6.1 1.76-.7l3.02-15.6c.18-.94-.75-1.7-1.25-1.06z"/></svg>',
  discord: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M20.3 4.4A19.7 19.7 0 0 0 15.4 3l-.2.4a18 18 0 0 1 4.3 2.2 17 17 0 0 0-15-.1A18 18 0 0 1 8.8 3.4L8.6 3a19.7 19.7 0 0 0-4.9 1.4C.6 9-.2 13.6.2 18a19.8 19.8 0 0 0 6 3l1.3-1.7a13 13 0 0 1-2-1l.5-.4a14 14 0 0 0 12 0l.5.4a13 13 0 0 1-2 1l1.3 1.7a19.8 19.8 0 0 0 6-3c.5-5.1-.8-9.7-3.5-13.6zM8.5 15.4c-1.2 0-2.2-1.1-2.2-2.4s1-2.4 2.2-2.4 2.2 1.1 2.2 2.4-1 2.4-2.2 2.4zm7 0c-1.2 0-2.2-1.1-2.2-2.4s1-2.4 2.2-2.4 2.2 1.1 2.2 2.4-1 2.4-2.2 2.4z"/></svg>',
  bell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0"/></svg>',
  gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1A1.7 1.7 0 0 0 15 4.6a1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
  logo: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M11.35 2.76a1 1 0 0 1 1.3 0l9 7.5a1 1 0 0 1 .35.74V20a2 2 0 0 1-2 2h-4.5a1 1 0 0 1-1-1v-4h-3v4a1 1 0 0 1-1 1H5a2 2 0 0 1-2-2v-8.99a1 1 0 0 1 .35-.75l8-7.5z"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
};

function modal(html, onReady) {
  const m = $('#modal');
  $('#sheet').innerHTML = '<div class="grab"></div>' + html;
  m.classList.add('on');
  if (onReady) onReady();
}
function closeModal() { $('#modal').classList.remove('on'); }
$('#modal').addEventListener('click', e => { if (e.target.id === 'modal') closeModal(); });

async function boot() {
  try {
    const me = await api('/api/me');
    S.user = me.user;
    S.settings = me;
    await Promise.all([loadChannels('kick'), loadChannels('yt'), loadChannels('tg'), loadFeeds()]);
    render();
  } catch (e) {
    S.user = null;
    renderLogin();
  }
  setTimeout(() => { $('#splash').classList.add('out'); setTimeout(()=>$('#splash').remove(),900); }, 1400);
}

function renderLogin() {
  $('#app').innerHTML = `
  <div class="login-wrap">
    <div class="login-card fade">
      <div class="login-logo">${ICONS.logo}</div>
      <div class="login-head">
        <h1>RESPECT <span>LIVE</span></h1>
        <p>سجّل الدخول للوصول إلى لوحتك</p>
      </div>
      <form id="loginForm">
        <label class="fld"><span>اسم المستخدم</span><input name="u" autocomplete="username" required></label>
        <label class="fld"><span>كلمة المرور</span><input name="p" type="password" autocomplete="current-password" required></label>
        <button class="btn pri wide" type="submit">دخول</button>
        <div class="err" id="err"></div>
      </form>
    </div>
  </div>`;
  $('#loginForm').onsubmit = async e => {
    e.preventDefault();
    const f = e.target;
    const fd = new FormData();
    fd.append('u', f.u.value);
    fd.append('p', f.p.value);
    try {
      const r = await fetch('/api/login', { method:'POST', body: fd, credentials:'include' });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || j.detail || 'خطأ');
      location.reload();
    } catch (err) {
      $('#err').textContent = err.message;
      toast(err.message, 'bad');
    }
  };
}

async function loadChannels(kind) {
  try {
    const r = await api(`/api/channels/${kind}`);
    S.channels[kind] = r.rows || [];
  } catch (e) { S.channels[kind] = []; }
}
async function loadFeeds() {
  try {
    const r = await api('/api/discord/feeds');
    S.feeds = r.rows || [];
    S.known = r.known_channels || {};
    S.watching = r.watching || [];
  } catch (e) { S.feeds = []; }
}

function render() {
  $('#app').innerHTML = `
    <div class="header" id="hdr">
      <div class="brand">
        <div class="brand-logo">${ICONS.logo}</div>
        <div>
          <div class="brand-name">RESPECT <span>LIVE</span></div>
          <div class="brand-sub">STREAM MONITOR</div>
        </div>
      </div>
      <div class="avatar" onclick="showAccount()">${esc(S.user.username.charAt(0).toUpperCase())}<div class="status"></div></div>
    </div>
    <div class="hero fade">
      <div style="font-family:var(--fe);font-size:11px;letter-spacing:4px;color:var(--muted);font-weight:800">◆ STREAM MONITOR</div>
      <h1>مراقبة <span>القنوات.</span></h1>
      <p>تابع قنوات كيك ويوتيوب وتيليجرام في مكان واحد. إشعارات فورية عند أي بث أو فيديو جديد.</p>
    </div>
    <div class="stats fade">
      <div class="stat"><b>${S.channels.kick.length}</b><small>KICK</small></div>
      <div class="stat"><b>${S.channels.yt.length}</b><small>YOUTUBE</small></div>
      <div class="stat"><b>${S.channels.tg.length}</b><small>TELEGRAM</small></div>
      <div class="stat"><b>${S.feeds.length}</b><small>DISCORD</small></div>
    </div>
    <div class="tabs" id="tabs">
      <button class="tab ${S.view==='kick'?'on':''}" data-v="kick">${ICONS.kick} KICK <span class="cnt">${S.channels.kick.length}</span></button>
      <button class="tab ${S.view==='yt'?'on':''}" data-v="yt">${ICONS.yt} YOUTUBE <span class="cnt">${S.channels.yt.length}</span></button>
      <button class="tab ${S.view==='tg'?'on':''}" data-v="tg">${ICONS.tg} TELEGRAM <span class="cnt">${S.channels.tg.length}</span></button>
      <button class="tab ${S.view==='discord'?'on':''}" data-v="discord">${ICONS.discord} DISCORD <span class="cnt">${S.feeds.length}</span></button>
    </div>
    <div id="view"></div>
    <div class="tabbar">
      <button data-v="kick" class="${S.view==='kick'?'on':''}">${ICONS.kick}</button>
      <button data-v="yt" class="${S.view==='yt'?'on':''}">${ICONS.yt}</button>
      <button data-v="tg" class="${S.view==='tg'?'on':''}">${ICONS.tg}</button>
      <button data-v="discord" class="${S.view==='discord'?'on':''}">${ICONS.discord}</button>
      <button onclick="showAccount()">${ICONS.user}</button>
    </div>`;
  $$('[data-v]').forEach(b => b.onclick = () => { S.view = b.dataset.v; render(); });
  window.addEventListener('scroll', () => {
    $('#hdr').classList.toggle('scrolled', window.scrollY > 10);
  }, { passive: true });
  renderView();
}

function renderView() {
  const v = $('#view');
  if (S.view === 'discord') return renderDiscord(v);
  const kind = S.view;
  const rows = S.channels[kind] || [];
  if (!rows.length) {
    v.innerHTML = `<div class="section"><div class="empty">
      <div style="width:90px;height:90px;margin:0 auto 16px;color:var(--blue);opacity:.4">${ICONS[kind]}</div>
      <h3>لا توجد قنوات بعد</h3>
      <p>ابدأ بإضافة أول قناة لتبدأ المراقبة</p>
      <button class="btn pri" onclick="addChannel('${kind}')">${ICONS.plus} إضافة قناة</button>
    </div></div>`;
    return;
  }
  v.innerHTML = `
    <div class="section" style="padding-bottom:0">
      <button class="btn pri" onclick="addChannel('${kind}')" style="margin-bottom:16px">${ICONS.plus} إضافة قناة</button>
      <div class="grid" id="grid"></div>
    </div>`;
  const grid = $('#grid');
  rows.forEach(r => grid.appendChild(channelCard(kind, r)));
}

function channelCard(kind, r) {
  const el = document.createElement('div');
  el.className = 'ch-card';
  let slug = '', title = '', sub = '';
  if (kind === 'kick') { slug = '@' + r.slug; title = r.name || r.slug; sub = r.live && r.title ? r.title : 'متابعة قناة كيك'; }
  else if (kind === 'yt') { slug = r.channel_id; title = r.name || r.channel_id; sub = 'قناة يوتيوب'; }
  else { slug = r.chat_id; title = r.name || r.chat_id; sub = 'قناة تيليجرام'; }
  const liveBadge = kind === 'kick' && r.live && r.enabled ? '<span class="badge live">مباشر</span>' :
                    !r.enabled ? '<span class="badge off">موقوف</span>' : '';
  const cover = r.banner || r.avatar || '';
  el.innerHTML = `
    <div class="ch-cover">${cover ? `<img src="${esc(cover)}" onerror="this.remove()">` : ''}${liveBadge}</div>
    <div class="ch-head">
      ${r.avatar ? `<img src="${esc(r.avatar)}" onerror="this.remove()">` : '<div style="width:54px;height:54px;border-radius:14px;background:var(--blue);display:grid;place-items:center;border:3px solid var(--bg)">' + ICONS[kind] + '</div>'}
      <div class="ch-info"><b>${esc(title)}</b><small>${esc(slug)}</small></div>
    </div>
    ${kind === 'kick' && r.live && r.title ? `<div class="ch-live"><div>${esc(r.title)}</div><span>${r.viewers||0} 👁</span></div>` : ''}
    <div class="ch-acts">
      ${kind === 'kick' ? `<a class="btn sm" href="https://kick.com/${esc(r.slug)}" target="_blank">${ICONS.play} مشاهدة</a>` : ''}
      ${kind === 'yt' ? `<a class="btn sm" href="https://youtube.com/channel/${esc(r.channel_id)}" target="_blank">${ICONS.play} زيارة</a>` : ''}
      <button class="btn sm ghost" onclick="editMsg('${kind}',${r.id})">رسالة</button>
      <button class="btn sm danger" onclick="delChannel('${kind}',${r.id})">${ICONS.trash}</button>
    </div>`;
  return el;
}

async function addChannel(kind) {
  const labels = {
    kick: { title:'إضافة قناة كيك', label:'اسم القناة (slug)', ph:'xqc' },
    yt:   { title:'إضافة قناة يوتيوب', label:'Channel ID يبدأ بـ UC', ph:'UCxxxxxxxxxxxxxxxxxxxxx' },
    tg:   { title:'إضافة قناة تيليجرام', label:'Chat ID أو @username', ph:'@mychannel' },
  }[kind];
  modal(`
    <h3>${labels.title}</h3>
    <label class="fld"><span>${labels.label}</span><input id="ci" placeholder="${labels.ph}"></label>
    <label class="fld"><span>الاسم (اختياري)</span><input id="cn" placeholder="اسم ودّي"></label>
    <div class="row"><button class="btn" onclick="closeModal()">إلغاء</button><button class="btn pri" id="cok">إضافة</button></div>
  `, () => {
    $('#cok').onclick = async () => {
      const val = $('#ci').value.trim();
      if (!val) return toast('اكتب القيمة', 'bad');
      try {
        const body = kind === 'kick' ? { slug: val, msg: '' } :
                     kind === 'yt'   ? { channel_id: val, name: $('#cn').value.trim() } :
                                       { chat_id: val, name: $('#cn').value.trim() };
        await api(`/api/channels/${kind}`, { method:'POST', body });
        toast('تمت الإضافة', 'ok');
        closeModal();
        await loadChannels(kind);
        render();
      } catch (e) { toast(e.message, 'bad'); }
    };
  });
}

async function delChannel(kind, id) {
  if (!confirm('حذف هذه القناة؟')) return;
  try {
    await api(`/api/channels/${kind}/${id}`, { method:'DELETE' });
    toast('تم الحذف', 'ok');
    await loadChannels(kind);
    render();
  } catch (e) { toast(e.message, 'bad'); }
}

async function editMsg(kind, id) {
  const r = S.channels[kind].find(x => x.id === id);
  if (!r) return;
  modal(`
    <h3>تخصيص رسالة الإشعار</h3>
    <p style="color:var(--muted);font-size:12.5px;margin-bottom:12px">المتغيرات: {name} {title} {url}</p>
    <label class="fld"><span>نص الرسالة</span><textarea id="m" rows="5">${esc(r.msg||'')}</textarea></label>
    <div class="row"><button class="btn" onclick="closeModal()">إلغاء</button><button class="btn pri" id="ok">حفظ</button></div>
  `, () => {
    $('#ok').onclick = async () => {
      try {
        await api(`/api/channels/${kind}/${id}`, { method:'PATCH', body: { msg: $('#m').value } });
        toast('تم الحفظ', 'ok');
        closeModal();
        await loadChannels(kind);
        render();
      } catch (e) { toast(e.message, 'bad'); }
    };
  });
}

function renderDiscord(v) {
  v.innerHTML = `
    <div class="section">
      <div class="card" style="margin-bottom:16px">
        <div style="font-family:var(--fe);font-size:12px;letter-spacing:2px;color:var(--blue);font-weight:900;margin-bottom:12px">DISCORD INTEGRATION</div>
        <p style="color:var(--muted);font-size:13px;line-height:1.8;margin-bottom:12px">اربط روم معين — كل رسالة جديدة فيه تُرسل تلقائياً لقنواتك على تيليجرام.</p>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <span class="chip ${S.watching.length?'green':'red'}">${S.watching.length} روم مراقب</span>
          <span class="chip ${S.feeds.length?'green':''}">${S.feeds.length} ربط خاص</span>
        </div>
      </div>
      <button class="btn pri wide" onclick="addFeed()" style="margin-bottom:16px">${ICONS.plus} ربط روم جديد</button>
      ${S.feeds.length ? S.feeds.map(f => `
        <div class="card" style="margin-bottom:12px;padding:16px">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
            <div>
              <div style="font-weight:900;margin-bottom:4px">${esc(S.known[f.channel_id] || f.channel_name || f.channel_id)}</div>
              <div style="font-family:var(--fe);font-size:10.5px;color:var(--muted);letter-spacing:1px">ID: ${esc(f.channel_id)}</div>
            </div>
            <button class="btn sm danger" onclick="delFeed(${f.id})">${ICONS.trash}</button>
          </div>
          ${f.template ? `<div style="margin-top:10px;padding:10px 12px;background:rgba(0,0,0,.25);border-radius:10px;font-size:12px;white-space:pre-wrap;font-family:monospace;color:var(--muted)">${esc(f.template)}</div>` : ''}
        </div>
      `).join('') : `<div class="empty">
        <div style="width:90px;height:90px;margin:0 auto 16px;color:var(--blue);opacity:.4">${ICONS.discord}</div>
        <h3>لا توجد رومات مربوطة</h3>
        <p>اربط روم ديسكورد ليستقبل رسائله على تيليجرام</p>
      </div>`}
    </div>`;
}

async function addFeed() {
  const chs = Object.entries(S.known).map(([id, name]) =>
    `<option value="${esc(id)}">#${esc(name)} (${esc(id)})</option>`).join('');
  modal(`
    <h3>ربط روم ديسكورد</h3>
    <p style="color:var(--muted);font-size:12.5px;margin-bottom:12px">اختر الروم الذي تريد مراقبته. الرسائل الجديدة فيه ستُرسل لقنوات تيليجرام.</p>
    <label class="fld"><span>الروم</span>
      ${chs ? `<select id="fc">${chs}</select>` : `<input id="fc" placeholder="channel_id (الرقم)">`}
    </label>
    <label class="fld"><span>القالب (اختياري)</span><textarea id="ft" rows="4" placeholder="<b>{author}</b>\n{content}"></textarea></label>
    <p style="color:var(--muted);font-size:11.5px;margin-top:-6px">المتغيرات: {author} {content} {channel}</p>
    <div class="row"><button class="btn" onclick="closeModal()">إلغاء</button><button class="btn pri" id="ok">ربط</button></div>
  `, () => {
    $('#ok').onclick = async () => {
      const cid = $('#fc').value.trim();
      if (!cid) return toast('اختر الروم', 'bad');
      try {
        await api('/api/discord/feeds', { method:'POST', body: {
          channel_id: cid,
          channel_name: S.known[cid] || '',
          template: $('#ft').value.trim(),
        }});
        toast('تم الربط', 'ok');
        closeModal();
        await loadFeeds();
        render();
      } catch (e) { toast(e.message, 'bad'); }
    };
  });
}
async function delFeed(id) {
  if (!confirm('حذف الربط؟')) return;
  try {
    await api(`/api/discord/feeds/${id}`, { method:'DELETE' });
    toast('تم الحذف', 'ok');
    await loadFeeds();
    render();
  } catch (e) { toast(e.message, 'bad'); }
}

function showAccount() {
  modal(`
    <h3>حسابي</h3>
    <div style="text-align:center;margin-bottom:20px">
      <div style="width:80px;height:80px;border-radius:50%;background:linear-gradient(135deg,var(--blue),var(--blue2));margin:0 auto 12px;display:grid;place-items:center;color:#fff;font-weight:900;font-family:var(--fe);font-size:32px;box-shadow:0 0 30px rgba(11,85,234,.5)">${esc(S.user.username.charAt(0).toUpperCase())}</div>
      <div style="font-size:20px;font-weight:900">${esc(S.user.username)}</div>
      <div style="color:var(--muted);font-size:11.5px;font-family:var(--fe);letter-spacing:2px;margin-top:4px">${S.user.role.toUpperCase()}</div>
    </div>
    <div style="display:grid;gap:10px">
      <button class="btn" onclick="openSettings()">${ICONS.gear} الإعدادات</button>
      <button class="btn danger" onclick="doLogout()">تسجيل الخروج</button>
      <button class="btn ghost" onclick="closeModal()">إغلاق</button>
    </div>
  `);
}

function openSettings() {
  modal(`
    <h3>الإعدادات</h3>
    <label class="fld"><span>اسم الموقع</span><input id="sn" value="${esc(S.settings.site_name||'')}"></label>
    <label class="fld"><span>قالب كيك</span><textarea id="tk" rows="4">${esc(S.settings.tpl_kick||'')}</textarea></label>
    <label class="fld"><span>قالب يوتيوب</span><textarea id="ty" rows="4">${esc(S.settings.tpl_yt||'')}</textarea></label>
    <label class="fld"><span>قالب ديسكورد</span><textarea id="td" rows="4">${esc(S.settings.tpl_discord||'')}</textarea></label>
    <div class="row"><button class="btn" onclick="showAccount()">رجوع</button><button class="btn pri" id="ok">حفظ</button></div>
  `, () => {
    $('#ok').onclick = async () => {
      try {
        await api('/api/settings', { method:'POST', body: {
          site_name: $('#sn').value,
          tpl_kick: $('#tk').value,
          tpl_yt: $('#ty').value,
          tpl_discord: $('#td').value,
        }});
        toast('تم الحفظ', 'ok');
        closeModal();
      } catch (e) { toast(e.message, 'bad'); }
    };
  });
}

async function doLogout() {
  await api('/api/logout', { method:'POST' });
  location.reload();
}

boot();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


@app.get("/health")
async def health():
    return {"ok": True, "discord_ready": discord_client.is_ready() if discord_client else False}


# ═══════════════════════════════════════════════════════════
#                       RUN
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
