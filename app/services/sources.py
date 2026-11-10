"""مصادر المحتوى: كيك، يوتيوب، X (تويتر)، تيك توك."""
import html as htmllib
import json
import re
import time
from urllib.parse import unquote

from .. import config as C
from .. import state
from ..db import q1, cfg, now


# ═══ أدوات مشتركة ═══
def find_default(kind, ident):
    ident = (ident or "").strip()
    if not ident:
        return None
    try:
        return q1("SELECT * FROM default_channels WHERE kind=? AND enabled=1 AND (lower(identifier)=lower(?) OR (alias!='' AND lower(alias)=lower(?))) LIMIT 1", (kind, ident, ident))
    except Exception:
        return None


def shared_row(kind, ident):
    table, col = C.KIND_TABLE[kind], C.KIND_IDCOL[kind]
    try:
        return q1("SELECT * FROM " + table + " WHERE lower(" + col + ")=lower(?) ORDER BY last_check DESC LIMIT 1", (ident,))
    except Exception:
        return None


def user_has(kind, ident, username):
    table, col = C.KIND_TABLE[kind], C.KIND_IDCOL[kind]
    return bool(q1("SELECT 1 x FROM " + table + " WHERE lower(" + col + ")=lower(?) AND added_by=?", (ident, username)))


def split_msg_img(msg):
    msg = msg or ""
    m = re.search(r"\{img:([^}]+)\}", msg)
    img = m.group(1).strip() if m else ""
    return re.sub(r"\{img:[^}]+\}", "", msg).strip(), img


async def _get_json(url, params=None, headers=None):
    h = {"Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9"}
    h.update(headers or {})
    try:
        r = await state.http().get(url, params=params, headers=h)
        if r.status_code == 200:
            j = r.json()
            if isinstance(j, dict) and j:
                return j
    except Exception:
        pass
    try:  # بديل اختياري لو الموقع يحجب (Cloudflare) وكان curl_cffi مثبتاً
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome") as s:
            r = await s.get(url, params=params, headers={"User-Agent": C.UA, **h}, timeout=15)
        if r.status_code == 200:
            j = r.json()
            if isinstance(j, dict) and j:
                return j
    except Exception:
        pass
    return None


# ═══ كيك ═══
def norm_kick(s):
    s = (s or "").strip().lower()
    m = re.search(r"kick\.com/([a-z0-9_-]+)", s)
    if m:
        s = m.group(1)
    return re.sub(r"[^a-z0-9_-]", "", s.replace("@", ""))


async def kick_fetch(slug):
    def _u(x):
        if isinstance(x, dict):
            return x.get("url") or x.get("src") or ""
        return x if isinstance(x, str) else ""
    for v in ("v2", "v1"):
        j = await _get_json("https://kick.com/api/" + v + "/channels/" + slug, headers={"Referer": "https://kick.com/"})
        if not j:
            continue
        try:
            ls = j.get("livestream") or {}
            u = j.get("user") or {}
            bn = _u(j.get("banner_image")) or _u(j.get("offline_banner_image"))
            return {"name": u.get("username") or slug, "avatar": u.get("profile_pic") or j.get("profile_pic") or "", "banner": bn or "",
                    "live": bool(ls.get("is_live")), "title": ls.get("session_title") or "", "viewers": ls.get("viewer_count") or 0,
                    "thumb": _u(ls.get("thumbnail"))}
        except Exception:
            continue
    return None


async def kick_record(slug):
    sh = shared_row("kick", slug)
    if sh and sh.get("name") and (now() - (sh.get("last_check") or 0) < 600):
        return {"name": sh["name"], "avatar": sh["avatar"], "banner": sh["banner"], "live": bool(sh["live"]), "title": sh["title"], "viewers": sh["viewers"], "thumb": sh["thumb"]}
    info = await kick_fetch(slug)
    if info:
        return info
    d = find_default("kick", slug) or {}
    return {"name": d.get("name") or slug, "avatar": d.get("avatar") or "", "banner": "", "live": False, "title": "", "viewers": 0, "thumb": ""}


# ═══ تيك توك ═══
def norm_tt(s):
    s = (s or "").strip()
    m = re.search(r"tiktok\.com/@([A-Za-z0-9_.]{2,24})", s)
    if m:
        s = m.group(1)
    s = s.lstrip("@").strip().lower()
    return s if re.match(r"^[a-z0-9_.]{2,24}$", s) else ""


async def tt_fetch(uname):
    ref = {"Referer": "https://www.tiktok.com/"}
    room = await _get_json("https://www.tiktok.com/api-live/user/room/", {"aid": "1988", "sourceType": "54", "uniqueId": uname}, ref)
    d = (room or {}).get("data") or {}
    user = d.get("user") or {}
    lr = d.get("liveRoom") or {}
    name = user.get("nickname") or ""
    avatar = user.get("avatarLarger") or user.get("avatarMedium") or ""
    if not name or not avatar:
        prof = await _get_json("https://www.tiktok.com/api/user/detail/", {"uniqueId": uname, "aid": "1988"}, ref)
        u2 = ((prof or {}).get("userInfo") or {}).get("user") or {}
        name = name or u2.get("nickname") or ""
        avatar = avatar or u2.get("avatarLarger") or u2.get("avatarMedium") or ""
    if not room and not name:
        return None
    live = (user.get("status") == 2) or (lr.get("status") == 2)
    stats = lr.get("liveRoomStats") or {}
    cover = lr.get("coverUrl") or ""
    if isinstance(cover, dict):
        cover = (cover.get("urlList") or [""])[0]
    return {"name": name or uname, "avatar": avatar, "banner": "", "live": bool(live), "title": lr.get("title") or "",
            "viewers": stats.get("userCount") or 0, "thumb": cover if isinstance(cover, str) else ""}


async def tt_record(uname):
    sh = shared_row("tt", uname)
    if sh and sh.get("name") and (now() - (sh.get("last_check") or 0) < 600):
        return {"name": sh["name"], "avatar": sh["avatar"], "banner": "", "live": bool(sh["live"]), "title": sh["title"], "viewers": sh["viewers"], "thumb": sh["thumb"]}, ""
    info = await tt_fetch(uname)
    if info:
        return info, ""
    d = find_default("tt", uname) or {}
    return {"name": d.get("name") or uname, "avatar": d.get("avatar") or "", "banner": "", "live": False, "title": "", "viewers": 0, "thumb": ""}, "warn"


# ═══ يوتيوب ═══
async def yt_feed(channel_id):
    try:
        r = await state.http().get("https://www.youtube.com/feeds/videos.xml?channel_id=" + channel_id)
        if r.status_code != 200:
            return None
        items = []
        for m in re.finditer(r"<entry>(.*?)</entry>", r.text, re.S):
            e = m.group(1)
            vid = (re.search(r"<yt:videoId>([^<]+)", e) or [None, ""])[1]
            title = htmllib.unescape((re.search(r"<title>([^<]*)", e) or [None, ""])[1])
            pub = (re.search(r"<published>([^<]+)", e) or [None, ""])[1]
            if vid:
                items.append({"id": vid, "title": title, "pub": pub})
        return items
    except Exception:
        return None


def _yt_grab(page):
    title = htmllib.unescape((re.search(r'<meta property="og:title" content="([^"]*)"', page) or [None, ""])[1])
    avatar = (re.search(r'<meta property="og:image" content="([^"]*)"', page) or [None, ""])[1]
    banner = (re.search(r'"banner":{"imageBannerViewModel":{"image":{"sources":\[\{"url":"([^"]*)"', page) or [None, ""])[1]
    if not banner:
        banner = (re.search(r'"tvBanner":{"thumbnails":\[\{"url":"([^"]*)"', page) or re.search(r'"mobileBanner":{"thumbnails":\[\{"url":"([^"]*)"', page) or [None, ""])[1]
    banner = banner.replace("\\u0026", "&")
    if not avatar:
        avatar = (re.search(r'"avatar":{"thumbnails":\[\{"url":"([^"]*)"', page) or [None, ""])[1].replace("\\u0026", "&")
    handle = (re.search(r'"canonicalBaseUrl":"/(@[^"]+)"', page) or [None, ""])[1]
    return title, avatar, banner, handle.lower()


async def yt_resolve(input_str):
    input_str = (input_str or "").strip()[:300]
    if not input_str:
        return None
    m = re.search(r"UC[\w-]{22}", input_str)
    if m:
        cid = m.group(0)
        try:
            r = await state.http().get("https://www.youtube.com/channel/" + cid, headers=C.YT_HEADERS)
            title, avatar, banner, handle = _yt_grab(r.text)
            return {"channel_id": cid, "name": title or cid, "avatar": avatar, "banner": banner, "handle": handle}
        except Exception:
            return {"channel_id": cid, "name": cid, "avatar": "", "banner": "", "handle": ""}
    h = re.search(r"@([\w.\-]+)", input_str) or (re.match(r"^([\w.\-]{3,})$", input_str))
    if h:
        try:
            r = await state.http().get("https://www.youtube.com/@" + h.group(1), headers=C.YT_HEADERS)
            page = r.text
            cid_m = re.search(r'"externalId":"(UC[\w-]{22})"', page) or re.search(r'"channelId":"(UC[\w-]{22})"', page)
            if not cid_m:
                return None
            title, avatar, banner, handle = _yt_grab(page)
            return {"channel_id": cid_m.group(1), "name": title or cid_m.group(1), "avatar": avatar, "banner": banner, "handle": handle or ("@" + h.group(1).lower())}
        except Exception:
            return None
    return None


async def resolve_yt(raw):
    raw = (raw or "").strip()[:300]
    m = re.search(r"UC[\w-]{22}", raw)
    if m:
        return m.group(0), ""
    h = re.search(r"@([\w.\-]+)", raw) or re.match(r"^([\w.\-]{3,})$", raw)
    if h:
        handle = "@" + h.group(1).lower()
        d = find_default("yt", handle)
        if d:
            return d["identifier"], handle
        r = q1("SELECT channel_id FROM yt_channels WHERE lower(handle)=? LIMIT 1", (handle,))
        if r:
            return r["channel_id"], handle
        info = await yt_resolve(handle)
        if info:
            return info["channel_id"], (info.get("handle") or handle)
    return None, ""


async def yt_record(raw):
    cid, handle = await resolve_yt(raw)
    if not cid:
        return None
    sh = shared_row("yt", cid)
    if sh and sh.get("avatar"):
        return {"channel_id": cid, "handle": handle or sh.get("handle", ""), "name": sh["name"] or cid, "avatar": sh["avatar"], "banner": sh["banner"], "last_video": sh["last_video"]}
    d = find_default("yt", cid) or {}
    info = await yt_resolve(cid) or {}
    feed = await yt_feed(cid)
    return {"channel_id": cid, "handle": handle or info.get("handle", "") or d.get("alias", ""),
            "name": info.get("name") or d.get("name") or cid, "avatar": info.get("avatar") or d.get("avatar") or "",
            "banner": info.get("banner") or "", "last_video": feed[0]["id"] if feed else ""}


# ═══ X / تويتر (API v2 — Bearer) ═══
TW_BASES = ["https://api.x.com/2", "https://api.twitter.com/2"]


def get_tw_key():
    k = (C.TWITTER_ENV_KEY or cfg("twitter_bearer", "") or "").strip()
    if k.lower().startswith("bearer "):
        k = k[7:].strip()
    if "%" in k:
        k = unquote(k)
    return k


def tw_available():
    return bool(get_tw_key())


def norm_tw(s):
    s = (s or "").strip()
    m = re.search(r"(?:https?://)?(?:www\.|mobile\.)?(?:x|twitter)\.com/@?([A-Za-z0-9_]{1,15})", s)
    u = m.group(1) if m else s.lstrip("@")
    u = u.split("?")[0].split("/")[0].strip()
    return u if re.match(r"^[A-Za-z0-9_]{1,15}$", u) else None


async def tw_get(path, params=None):
    key = get_tw_key()
    if not key:
        return 0, {}, "مفتاح تويتر غير مضبوط"
    if state.TW["pause_until"] > time.time():
        return 429, {}, "تم تجاوز حد الطلبات مؤقتاً — سيُعاد المحاولة تلقائياً"
    last_exc = ""
    for base in TW_BASES:
        try:
            r = await state.http().get(base + path, params=params or {}, headers={"Authorization": "Bearer " + key}, timeout=20)
        except Exception as e:
            last_exc = str(e)[:120]
            continue
        try:
            j = r.json()
        except Exception:
            j = {}
        if r.status_code == 200:
            state.TW["last_error"] = ""
            state.TW["last_ok"] = now()
            return 200, j, ""
        detail = (j.get("detail") or j.get("title") or j.get("error") or "")[:160] if isinstance(j, dict) else ""
        sc = r.status_code
        if sc == 401:
            err = "مفتاح تويتر غير صالح أو منتهي (401)"
        elif sc == 402:
            err = "رصيد X API منتهي — اشحن الرصيد من console.x.com (402)"
        elif sc == 403:
            err = "المفتاح لا يملك صلاحية القراءة أو المشروع غير مفعّل (403) " + detail
        elif sc == 429:
            try:
                reset = int(r.headers.get("x-rate-limit-reset", "0"))
            except Exception:
                reset = 0
            state.TW["pause_until"] = reset if reset > time.time() else time.time() + 900
            err = "تجاوزت حد الطلبات (429) — توقف الجلب مؤقتاً"
        else:
            err = "خطأ من تويتر (" + str(sc) + ") " + detail
        state.TW["last_error"] = err
        return sc, j, err
    state.TW["last_error"] = "تعذّر الاتصال بتويتر: " + last_exc
    return 0, {}, state.TW["last_error"]


async def tw_resolve(username):
    st, j, err = await tw_get("/users/by/username/" + username, {"user.fields": "profile_image_url,name,protected,profile_banner_url"})
    if st != 200:
        return None, err, st
    d = j.get("data")
    if not d:
        return None, "الحساب @" + username + " غير موجود أو موقوف", 404
    if d.get("protected"):
        return None, "الحساب محمي (خاص) — لا يمكن متابعته", 403
    avatar = (d.get("profile_image_url") or "").replace("_normal", "_400x400")
    return {"user_id": d["id"], "username": d.get("username") or username, "name": d.get("name") or username, "avatar": avatar, "banner": d.get("profile_banner_url") or ""}, "", 200


def tw_parse(t, media):
    refs = t.get("referenced_tweets") or []
    types = [r.get("type") for r in refs]
    note = t.get("note_tweet") or {}
    text = note.get("text") or t.get("text") or ""
    ents = note.get("entities") or t.get("entities") or {}
    urls = []
    for u in (ents.get("urls") or []):
        full = u.get("unwound_url") or u.get("expanded_url") or u.get("url") or ""
        urls.append(full)
        short = u.get("url")
        if short:
            exp = u.get("expanded_url") or ""
            text = text.replace(short, "" if (u.get("media_key") or "/photo/" in exp or "/video/" in exp) else full)
    text = htmllib.unescape(text).strip()
    imgs = []
    for mk in ((t.get("attachments") or {}).get("media_keys") or []):
        m = media.get(mk)
        if m:
            u = m.get("url") if m.get("type") == "photo" else m.get("preview_image_url")
            if u:
                imgs.append(u)
    return {"id": str(t["id"]), "text": text, "urls": urls, "images": imgs, "is_rt": "retweeted" in types,
            "is_reply": ("replied_to" in types) or bool(t.get("in_reply_to_user_id")), "is_quote": "quoted" in types, "created": t.get("created_at", "")}


async def tw_timeline(user_id, since_id="", exclude=None, max_results=10):
    params = {"max_results": max_results, "tweet.fields": "created_at,entities,attachments,referenced_tweets,note_tweet,in_reply_to_user_id",
              "expansions": "attachments.media_keys", "media.fields": "type,url,preview_image_url"}
    if since_id:
        params["since_id"] = since_id
    if exclude:
        params["exclude"] = ",".join(exclude)
    st, j, err = await tw_get("/users/" + str(user_id) + "/tweets", params)
    if st != 200:
        return None, err
    media = {m["media_key"]: m for m in ((j.get("includes") or {}).get("media") or []) if m.get("media_key")}
    return [tw_parse(t, media) for t in (j.get("data") or [])], ""


TW_FILTER_DEFAULT = {"skip_retweets": False, "skip_replies": False, "skip_quotes": False, "only_media": False,
                     "block_youtube": False, "block_words": [], "require_words": [], "block_domains": [], "min_chars": 0}
_YT_RE = re.compile(r"(youtube\.com|youtu\.be|youtube-nocookie\.com)", re.I)


def parse_tw_filters(raw):
    try:
        d = raw if isinstance(raw, dict) else (json.loads(raw) if raw else {})
        if not isinstance(d, dict):
            d = {}
    except Exception:
        d = {}
    out = json.loads(json.dumps(TW_FILTER_DEFAULT))
    for k in ("skip_retweets", "skip_replies", "skip_quotes", "only_media", "block_youtube"):
        out[k] = bool(d.get(k))
    for k in ("block_words", "require_words", "block_domains"):
        v = d.get(k) or []
        if isinstance(v, str):
            v = re.split(r"[,\n،]+", v)
        out[k] = [str(x).strip().lower()[:60] for x in v if str(x).strip()][:30]
    try:
        out["min_chars"] = max(0, min(280, int(d.get("min_chars") or 0)))
    except Exception:
        out["min_chars"] = 0
    return out


def tw_pass_filters(tw, f):
    if f["skip_retweets"] and tw["is_rt"]:
        return False
    if f["skip_replies"] and tw["is_reply"]:
        return False
    if f["skip_quotes"] and tw["is_quote"]:
        return False
    if f["only_media"] and not tw["images"]:
        return False
    urls = " ".join(tw["urls"]).lower()
    low = tw["text"].lower()
    if f["block_youtube"] and (_YT_RE.search(urls) or _YT_RE.search(low)):
        return False
    if any(d in urls or d in low for d in f["block_domains"]):
        return False
    if any(w in low for w in f["block_words"]):
        return False
    if f["require_words"] and not any(w in low for w in f["require_words"]):
        return False
    if f["min_chars"] and len(tw["text"]) < f["min_chars"]:
        return False
    return True


async def tw_record(uname):
    d = find_default("tw", uname.lower())
    sh = shared_row("tw", uname)
    if sh and sh.get("user_id"):
        return {"username": sh["username"], "user_id": sh["user_id"], "name": sh["name"] or sh["username"], "avatar": sh["avatar"], "banner": sh["banner"], "last_tweet": sh["last_tweet"]}, ""
    if d:
        return {"username": uname, "user_id": "", "name": d["name"] or uname, "avatar": d["avatar"] or "", "banner": "", "last_tweet": ""}, ""
    info, err, st = await tw_resolve(uname)
    if not info:
        return None, err
    info["last_tweet"] = ""
    return info, ""
