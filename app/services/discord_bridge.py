"""جسر ديسكورد → تيليجرام (نفس المنطق السابق: قراءة الرومات المربوطة وتحويلها)."""
import asyncio
import json
import re

from .. import config as C
from .. import state
from ..db import q, q1, run, tx, cfg, now
from ..security import rate_ok
from . import telegram as tg
from .extras import groq_available, groq_rewrite, add_notif, push_bg, strip_tags

try:
    import discord  # discord.py-self
except Exception:  # المكتبة غير مثبتة → وضع HTTP فقط
    discord = None

_MENTION_RE = re.compile(r"<@[!&]?\d+>")
_CHAN_RE = re.compile(r"<#\d+>")
_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")


def clean_mentions(text):
    if not text:
        return ""
    t = _MENTION_RE.sub("", str(text))
    t = _CHAN_RE.sub("", t)
    t = re.sub(r"@everyone\b|@here\b", "", t)
    t = _EMOJI_RE.sub("", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n", "\n\n", t)
    return t.strip()


def extract_msg(msg):
    author = msg.author.display_name or msg.author.name or ""
    author_no_at = re.sub(r"^@", "", author).strip()
    raw_content = (msg.content or "").strip()
    content = clean_mentions(raw_content)
    title = desc = img = url = footer = ""
    for e in (msg.embeds or []):
        if e.author and e.author.name and not author:
            author = e.author.name
            author_no_at = re.sub(r"^@", "", author).strip()
        if e.title and not title:
            title = e.title.strip()
        if e.description and not desc:
            desc = clean_mentions(e.description.strip())
        if e.url and not url:
            url = e.url
        if e.footer and e.footer.text and not footer:
            footer = e.footer.text
        if e.image and e.image.url and not img:
            img = e.image.url
        elif e.thumbnail and e.thumbnail.url and not img:
            img = e.thumbnail.url
        try:
            parts = []
            for f in (e.fields or []):
                fname = (f.name or "").strip()
                fval = clean_mentions((f.value or "").strip())
                if fval:
                    parts.append((fname + ": " + fval) if fname else fval)
            ft = "\n".join(parts).strip()
            if ft and ft not in desc:
                desc = (desc + "\n\n" + ft).strip() if desc else ft
        except Exception:
            pass
    if not img:
        for a in (msg.attachments or []):
            if (getattr(a, "content_type", "") or "").startswith("image/"):
                img = a.url
                break
    if not content:
        content = desc or title
    final = content or desc or title
    if title and desc and title not in desc:
        final = title + "\n\n" + desc
    elif title and not desc:
        final = title
    g = msg.guild
    return {"author": author[:200], "author_no_at": author_no_at[:200], "username": getattr(msg.author, "name", "")[:100],
            "user_id": str(msg.author.id), "is_bot": bool(getattr(msg.author, "bot", False)), "content": content[:4000],
            "content_raw": raw_content[:4000], "title": title[:300], "description": desc[:4000], "footer": footer[:300],
            "image": img, "url": url, "final_text": final[:4000], "guild_id": str(g.id) if g else "", "guild_name": g.name if g else "",
            "channel_id": str(msg.channel.id), "channel_name": getattr(msg.channel, "name", "") or "", "message_id": str(msg.id),
            "message_url": ("https://discord.com/channels/" + str(g.id) + "/" + str(msg.channel.id) + "/" + str(msg.id)) if g else ""}


def match_kw_full(kw_json, text, default_img="", default_text=""):
    if not kw_json:
        return default_img, default_text
    try:
        rules = json.loads(kw_json)
    except Exception:
        return default_img, default_text
    if not isinstance(rules, list):
        return default_img, default_text
    tl = (text or "").lower()
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        for kw in (rule.get("keywords") or []):
            if str(kw).lower() in tl:
                return rule.get("image") or default_img, rule.get("caption") or rule.get("text") or default_text
    return default_img, default_text


def build_text(tpl, data, site=""):
    if not tpl:
        tpl = "<b>{author_no_at}</b>\n\n<b>{content}</b>"
    v = {"name": data.get("author_no_at") or data.get("author") or "", "author": data.get("author") or "", "author_no_at": data.get("author_no_at") or "",
         "username": data.get("username") or "", "user_id": data.get("user_id") or "", "content": data.get("content") or "",
         "content_raw": data.get("content_raw") or "", "description": data.get("description") or "", "title": data.get("title") or "",
         "footer": data.get("footer") or "", "channel": data.get("channel_name") or "", "channel_id": data.get("channel_id") or "",
         "guild": data.get("guild_name") or "", "guild_id": data.get("guild_id") or "", "url": data.get("url") or data.get("message_url") or "",
         "message_url": data.get("message_url") or "", "site": site}
    return re.sub(r"\{(\w+)\}", lambda m: str(v.get(m.group(1), m.group(0))), str(tpl))


def refresh_cache():
    cl = state.DC["client"]
    state.DC["channels"].clear()
    state.DC["guilds"].clear()
    if not cl or not cl.is_ready():
        return
    u = cl.user
    if u:
        state.DC["bot"].update({"id": str(u.id), "name": u.name, "avatar": str(u.display_avatar.url) if getattr(u, "display_avatar", None) else ""})
    for g in cl.guilds:
        state.DC["guilds"][str(g.id)] = {"name": g.name, "id": str(g.id)}
        if C.ALLOWED_GUILDS and str(g.id) not in C.ALLOWED_GUILDS:
            continue
        for ch in g.text_channels:
            state.DC["channels"][str(ch.id)] = {"name": ch.name, "guild": g.name, "guild_id": str(g.id)}
    print("[Discord] Cache: " + str(len(state.DC["channels"])) + " channels")


def is_ready():
    cl = state.DC["client"]
    return bool(cl and cl.is_ready())


def watching():
    return list(state.DC["channels"].keys()) if not C.WATCH_CHANNELS else C.WATCH_CHANNELS


def _ignores_bot(feed, bot_id):
    try:
        bots = json.loads(feed["ignore_bots"] or "[]")
        return isinstance(bots, list) and str(bot_id) in [str(x) for x in bots]
    except Exception:
        return False


def _track_bot(msg):
    try:
        aid = str(msg.author.id)
        name = msg.author.name or ""
        avatar = str(msg.author.display_avatar.url) if getattr(msg.author, "display_avatar", None) else ""
        if q1("SELECT 1 x FROM discord_bots WHERE id=?", (aid,)):
            run("UPDATE discord_bots SET last_seen=?, seen_count=seen_count+1, name=?, avatar=? WHERE id=?", (now(), name, avatar, aid))
        else:
            run("INSERT INTO discord_bots(id,name,avatar,first_seen,last_seen,seen_count) VALUES(?,?,?,?,?,1)", (aid, name, avatar, now(), now()))
    except Exception:
        pass


async def on_message(msg):
    cl = state.DC["client"]
    if cl.user and msg.author.id == cl.user.id:
        return
    if not msg.guild:
        return
    if C.ALLOWED_GUILDS and str(msg.guild.id) not in C.ALLOWED_GUILDS:
        return
    if getattr(msg.author, "bot", False):
        _track_bot(msg)
    feeds = q("SELECT * FROM discord_feeds WHERE channel_id=? AND enabled=1", (str(msg.channel.id),))
    if not feeds:
        return
    try:
        run("INSERT INTO discord_seen(message_id,ts) VALUES(?,?)", (str(msg.id), now()))
    except Exception:
        return  # مكررة
    data = extract_msg(msg)
    if not data["final_text"] and not data["image"]:
        return
    site = cfg("site_name", C.SITE_NAME)
    for feed in feeds:
        try:
            await _deliver_feed(feed, data, site)
        except Exception as e:
            print("[Discord feed] " + repr(e))


async def _deliver_feed(feed, data, site):
    if data["is_bot"] and _ignores_bot(feed, data["user_id"]):
        return
    if not rate_ok("discord:" + str(feed["id"]), C.MAX_PER_MIN_TG):
        return
    if feed.get("use_original", 1):
        text = data["final_text"] or ""
        text = ("<b>" + data["author_no_at"] + "</b>\n\n<b>" + text + "</b>") if data["author_no_at"] else ("<b>" + text + "</b>")
    else:
        text = build_text(feed["template"] or cfg("tpl_discord"), data, site)
    if feed.get("use_ai") and groq_available():
        out = await groq_rewrite(text, feed.get("ai_prompt") or "")
        if out:
            text = "<b>" + out + "</b>"
    final_img, final_text = "", text
    if feed.get("keyword_rules"):
        kw_img, kw_caption = match_kw_full(feed["keyword_rules"], text, "", "")
        if kw_img:
            final_img = kw_img
        if kw_caption:
            final_text = "<b>" + kw_caption + "</b>"
    if not final_img:
        final_img = feed.get("fixed_image") or data["image"]
    btn = feed["btn_text"] or cfg("btn_discord", "عرض الروم")
    room_url = feed.get("room_url") or data["message_url"]
    ids = set()
    try:
        for x in json.loads(feed["target_tg_ids"] or "[]"):
            try:
                ids.add(int(x))
            except Exception:
                pass
    except Exception:
        pass
    for s in q("SELECT tg_channel_id FROM feed_subs WHERE feed_id=? AND enabled=1", (feed["id"],)):
        ids.add(int(s["tg_channel_id"]))
    tgs = q("SELECT * FROM tg_channels WHERE enabled=1 AND id IN (" + ",".join("?" * len(ids)) + ")", tuple(ids)) if ids else []
    title = data["author_no_at"] or "رسالة"
    plain = strip_tags(final_text)
    notified = {feed["added_by"]} | {t["added_by"] for t in tgs}
    for un in notified:
        add_notif(un, title, plain[:500], final_img, btn, room_url, "discord")
        push_bg(un, title, plain[:200], final_img, room_url, "discord")
    await tg.tg_deliver(tgs, final_text, final_img, btn, room_url, "dc", feed["channel_name"] or data["channel_name"] or "")


def build_client():
    if discord is None:
        print("[Discord] المكتبة غير مثبتة — وضع HTTP فقط")
        return None
    cl = None
    try:
        if hasattr(discord, "Intents"):
            intents = discord.Intents(guilds=True, guild_messages=True, message_content=True)
            try:
                cl = discord.Client(self_bot=True, intents=intents)
                state.DC["self_bot"] = True
            except TypeError:
                cl = discord.Client(intents=intents)
        else:
            cl = discord.Client(self_bot=True)
            state.DC["self_bot"] = True
    except Exception as e:
        print("[Discord] Init error: " + str(e))
        return None

    @cl.event
    async def on_ready():
        print("[Discord] ✅ Logged in: " + str(cl.user))
        refresh_cache()

    for ev in ("on_guild_channel_create", "on_guild_channel_delete", "on_guild_join", "on_guild_remove"):
        async def _h(*_a, **_k):
            refresh_cache()
        _h.__name__ = ev
        cl.event(_h)

    @cl.event
    async def on_message(msg):  # noqa: F811
        try:
            await globals()["on_message"](msg)
        except Exception as e:
            print("[Discord on_message] " + repr(e))

    state.DC["client"] = cl
    return cl


async def start():
    if not C.DISCORD_TOKEN:
        print("[Discord] No token — HTTP-only mode")
        return
    cl = build_client()
    if not cl:
        return

    async def runner():
        delay = 10
        while True:
            try:
                await cl.start(C.DISCORD_TOKEN)
                return
            except asyncio.CancelledError:
                return
            except Exception as e:
                msg = str(e)
                print("[Discord] start error: " + msg[:200])
                if "401" in msg or "Improper token" in msg or "LoginFailure" in type(e).__name__:
                    return  # التوكن خاطئ — لا داعي لإعادة المحاولة
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300)
    asyncio.create_task(runner())


async def stop():
    cl = state.DC["client"]
    if cl:
        try:
            await cl.close()
        except Exception:
            pass
