"""الواجهة: ملفات ثابتة مضغوطة ومخزنة، صفحات مستقلة، manifest، service worker."""
import gzip
import hashlib
import json
import mimetypes
import os
import re

from starlette.responses import Response, HTMLResponse, RedirectResponse

from .. import config as C
from .. import state
from ..db import q1, cfg
from ..http import api, Json
from ..services import telegram as tg
from ..services.extras import push_available, groq_available
from ..services.sources import tw_available
from .admin import get_glass, get_features

TEXT_TYPES = (".js", ".css", ".html", ".svg", ".json", ".txt", ".webmanifest", ".map")
_assets = {}       # path -> (body, gz, mime, etag)
BUILD = "dev"

# كل صفحة لها رابطها الخاص — الخادم يعيد هيكل التطبيق لها (والتطبيق يفتح الصفحة الصحيحة مباشرة)
PAGE_PATHS = {"/", "/login", "/register", "/kick", "/youtube", "/x", "/tiktok", "/telegram", "/discord", "/notifications",
              "/news", "/account", "/activity", "/live", "/platforms", "/send", "/settings"}
ADMIN_RE = re.compile(r"^/admin(/[a-z-]+)?/?$")


def load_assets():
    """يقرأ ملفات web/ مرة واحدة، يضغطها، ويحسب بصمة الإصدار (لتخزين طويل بلا مشاكل تحديث)"""
    global BUILD
    _assets.clear()
    h = hashlib.sha1()
    for root, _, files in os.walk(C.WEB_DIR):
        for fn in sorted(files):
            full = os.path.join(root, fn)
            rel = "/" + os.path.relpath(full, C.WEB_DIR).replace(os.sep, "/")
            with open(full, "rb") as f:
                body = f.read()
            h.update(rel.encode())
            h.update(body)
            mime = mimetypes.guess_type(fn)[0] or "application/octet-stream"
            if fn.endswith(".js"):
                mime = "text/javascript"
            if fn.endswith(TEXT_TYPES) and not mime.endswith("charset=utf-8"):
                mime += "; charset=utf-8"
            gz = gzip.compress(body, 9) if fn.endswith(TEXT_TYPES) and len(body) > 600 else None
            _assets[rel] = [body, gz, mime, '"' + hashlib.md5(body).hexdigest()[:16] + '"']
    BUILD = h.hexdigest()[:10]
    # نحقن رقم الإصدار في كل روابط الملفات داخل الكود (import / href)
    for rel, a in _assets.items():
        if rel.endswith((".js", ".css", ".html")):
            txt = a[0].decode("utf-8").replace("__BUILD__", BUILD)
            a[0] = txt.encode("utf-8")
            a[1] = gzip.compress(a[0], 9) if len(a[0]) > 600 else None
            a[3] = '"' + hashlib.md5(a[0]).hexdigest()[:16] + '"'
    print("[Web] " + str(len(_assets)) + " assets, build " + BUILD)


def _serve(request, rel, immutable):
    a = _assets.get(rel)
    if not a:
        return None
    body, gz, mime, etag = a
    headers = {"etag": etag, "cache-control": "public, max-age=31536000, immutable" if immutable else "no-cache", "vary": "Accept-Encoding",
               "x-content-type-options": "nosniff"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    if gz and "gzip" in (request.headers.get("accept-encoding") or ""):
        headers["content-encoding"] = "gzip"
        return Response(gz, media_type=mime, headers=headers)
    return Response(body, media_type=mime, headers=headers)


def boot_payload():
    theme = _theme()
    return {
        "build": BUILD, "glass": get_glass(), "features": get_features(),
        "ui_mode_prompt": cfg("ui_mode_prompt", "1") == "1", "ui_default_mode": cfg("ui_default_mode", "full"),
        "bot_link": tg.bot_link(), "bot_username": state.TG_BOT.get("username", ""),
        "site_name": cfg("site_name", C.SITE_NAME), "site_sub": cfg("site_sub"),
        "hero_title": cfg("hero_title"), "hero_accent": cfg("hero_accent"), "hero_text": cfg("hero_text"),
        "guest_mode": cfg("guest_mode", "1") == "1", "guest_blur": int(cfg("guest_blur", "14") or 14),
        "has_telegram": bool(C.TELEGRAM_TOKEN), "has_discord": bool(C.DISCORD_TOKEN), "has_push": push_available(), "has_groq": groq_available(),
        "theme": theme, "site_logo": cfg("site_logo", ""),
        "maintenance": cfg("maintenance", "0") == "1", "maintenance_title": cfg("maintenance_title", "صيانة مؤقتة"), "maintenance_text": cfg("maintenance_text"),
        "registration_enabled": cfg("registration_enabled", "1") == "1", "bot_name_custom": cfg("bot_name_custom", "Respect Live"),
        "has_twitter": tw_available(), "announce_bar": cfg("announce_bar", ""),
        "required_channel_url": cfg("required_channel_url", ""), "required_channel_name": cfg("required_channel_name", ""),
        "required_channel_msg": cfg("required_channel_msg", ""), "self_bot_mode": False,
    }


def _theme():
    tid = cfg("site_theme", "default")
    if tid == "custom":
        return {"id": "custom", "n": "مخصص", "c1": cfg("site_c1", "#05070c"), "c2": cfg("site_c2", "#0c111b"), "ac": cfg("site_ac", C.SITE_COLOR)}
    return next((t for t in C.THEMES if t["id"] == tid), C.THEMES[0])


@api("/api/boot")
async def boot(req):
    if C.TELEGRAM_TOKEN and not state.TG_BOT["username"]:
        try:
            await tg.tg_bot_id()
        except Exception:
            pass
    return boot_payload()


def _index(request):
    a = _assets.get("/index.html")
    if not a:
        return HTMLResponse("<h1>web/index.html غير موجود</h1>", 500)
    # نضمّن بيانات الإقلاع داخل الصفحة → أول رسم فوري بدون انتظار طلب إضافي
    html = a[0].decode("utf-8")
    bp = json.dumps(boot_payload(), ensure_ascii=False).replace("</", "<\\/")
    theme = _theme()
    html = html.replace("/*__BOOT__*/null", bp).replace("__THEME_BG__", theme["c1"]).replace("__SITE_NAME__", _esc(cfg("site_name", C.SITE_NAME)))
    body = html.encode("utf-8")
    headers = {"cache-control": "no-cache", "vary": "Accept-Encoding", "x-content-type-options": "nosniff"}
    if "gzip" in (request.headers.get("accept-encoding") or ""):
        headers["content-encoding"] = "gzip"
        body = gzip.compress(body, 6)
    return Response(body, media_type="text/html; charset=utf-8", headers=headers)


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


async def page_or_asset(request):
    path = request.url.path
    if path.startswith("/assets/"):
        r = _serve(request, path[len("/assets"):], immutable=bool(request.query_params.get("v")) or BUILD in path)
        return r or Response("not found", 404)
    if path in PAGE_PATHS or ADMIN_RE.match(path):
        return _index(request)
    if path.endswith("/") and path.rstrip("/") in PAGE_PATHS:
        return RedirectResponse(path.rstrip("/"), 301)
    return _index(request) if "." not in path.rsplit("/", 1)[-1] and not path.startswith("/api/") else Response("not found", 404)


@api("/manifest.json")
async def manifest(req):
    theme = _theme()
    logo = cfg("site_logo", "")
    name = cfg("site_name", C.SITE_NAME)
    icons = [{"src": logo or "/assets/icon.svg", "sizes": "any", "type": "image/svg+xml" if not logo else "image/png", "purpose": "any"},
             {"src": "/assets/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "maskable"}]
    return Json({"name": name, "short_name": name[:12], "id": "/", "scope": "/", "start_url": "/", "display": "standalone",
                 "display_override": ["standalone", "minimal-ui"], "orientation": "any", "background_color": theme["c1"], "theme_color": theme["c1"],
                 "dir": "rtl", "lang": "ar", "icons": icons, "categories": ["productivity", "utilities"],
                 "shortcuts": [{"name": "التنبيهات", "url": "/notifications"}, {"name": "كيك", "url": "/kick"}, {"name": "تيليجرام", "url": "/telegram"}]},
                headers={"cache-control": "no-cache"})


@api("/sw.js")
async def sw(req):
    a = _assets.get("/sw.js")
    js = a[0].decode("utf-8") if a else ""
    js = js.replace("__PWA__", "1" if cfg("pwa_enhance", "1") == "1" else "0")
    return Response(js, media_type="text/javascript; charset=utf-8", headers={"cache-control": "no-cache", "service-worker-allowed": "/"})


@api("/favicon.ico")
async def favicon(req):
    logo = cfg("site_logo", "")
    if logo.startswith("/api/image/"):
        row = q1("SELECT mime,data FROM images WHERE id=?", (logo.replace("/api/image/", ""),))
        if row:
            return Response(row["data"], media_type=row["mime"], headers={"cache-control": "public, max-age=3600"})
    a = _assets.get("/icon.svg")
    if a:
        return Response(a[0], media_type="image/svg+xml", headers={"cache-control": "public, max-age=86400"})
    return Response(b"", status_code=204)


@api("/health")
async def health(req):
    from ..services import discord_bridge as dcb
    return {"ok": True, "build": BUILD, "discord_ready": dcb.is_ready(), "discord_channels": len(state.DC["channels"]),
            "auto_discovery": not bool(C.WATCH_CHANNELS), "push_enabled": push_available(), "telegram_enabled": bool(C.TELEGRAM_TOKEN),
            "groq_enabled": groq_available(), "maintenance": cfg("maintenance", "0") == "1", "public_url": C.PUBLIC_URL}
