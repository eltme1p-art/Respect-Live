"""تخزين الصور: الرفع، وتخزين صور القنوات الخارجية محلياً."""
import secrets
import time

from .. import config as C
from .. import state
from ..db import q, q1, run, tx, now

ALLOWED_MIME = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif", "image/avif"}


def sniff_mime(data: bytes, fallback=""):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    return fallback if fallback in ALLOWED_MIME else ""


def store_image(data: bytes, mime: str, by: str) -> str:
    img_id = secrets.token_urlsafe(16)
    run("INSERT INTO images(id,mime,data,size,uploaded_by,created) VALUES(?,?,?,?,?,?)", (img_id, mime, data, len(data), by, now()))
    return "/api/image/" + img_id


async def cache_remote_image(url):
    """يحمّل الصورة الخارجية مرة واحدة ويحفظها ويرجع /api/image/... — وإن فشل يرجع الرابط الأصلي"""
    url = (url or "").strip()
    if not url.startswith("http"):
        return url
    if state.IMG_FAIL.get(url, 0) > time.time():
        return url
    try:
        r = q1("SELECT i.id FROM img_cache k JOIN images i ON i.id=k.img_id WHERE k.url=?", (url,))
        if r:
            return "/api/image/" + r["id"]
    except Exception:
        pass
    try:
        resp = await state.http().get(url, headers={"Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
        ct = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        data = resp.content
        if resp.status_code != 200 or not data or len(data) > C.MAX_IMAGE_SIZE * 2:
            raise ValueError("bad image")
        mime = sniff_mime(data, ct)
        if not mime:
            raise ValueError("not image")
        img_id = secrets.token_urlsafe(16)
        with tx() as c:
            c.execute("INSERT INTO images(id,mime,data,size,uploaded_by,created) VALUES(?,?,?,?,?,?)", (img_id, mime, data, len(data), "cache", now()))
            c.execute("INSERT OR REPLACE INTO img_cache(url,img_id,ts) VALUES(?,?,?)", (url, img_id, now()))
        return "/api/image/" + img_id
    except Exception:
        if len(state.IMG_FAIL) > 2000:
            state.IMG_FAIL.clear()
        state.IMG_FAIL[url] = time.time() + 3600
        return url


async def localize_rec(rec):
    try:
        for k in ("avatar", "banner"):
            if rec.get(k):
                rec[k] = await cache_remote_image(rec[k])
    except Exception:
        pass
    return rec


async def job_backfill_images():
    """يحوّل صور القنوات القديمة (روابط خارجية) إلى صور محلية تدريجياً"""
    todo = []
    for tbl, cols in (("kick_channels", ("avatar", "banner")), ("yt_channels", ("avatar", "banner")), ("tw_channels", ("avatar", "banner")),
                      ("tg_channels", ("avatar", "banner")), ("tt_channels", ("avatar",)), ("default_channels", ("avatar",))):
        for col in cols:
            try:
                for r in q("SELECT DISTINCT " + col + " v FROM " + tbl + " WHERE " + col + " LIKE 'http%' LIMIT 40"):
                    if state.IMG_FAIL.get(r["v"], 0) < time.time():
                        todo.append((tbl, col, r["v"]))
            except Exception:
                pass
    for tbl, col, url in todo[:20]:
        new = await cache_remote_image(url)
        if new and new != url:
            run("UPDATE " + tbl + " SET " + col + "=? WHERE " + col + "=?", (new, url))
