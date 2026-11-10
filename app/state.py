"""حالة مشتركة في الذاكرة + عميل HTTP واحد مشترك (اتصالات مُعاد استخدامها = أسرع وأخف)."""
import time

import httpx

from . import config as C

STARTED = time.time()

# بوت تيليجرام
TG_BOT = {"id": "", "username": "", "name": ""}

# ديسكورد
DC = {"client": None, "self_bot": False, "channels": {}, "guilds": {}, "bot": {"id": "", "name": "", "avatar": ""}}

# تويتر
TW = {"pause_until": 0, "last_error": "", "last_ok": 0}

# فشل تحميل الصور (حتى لا نعيد المحاولة كل مرة)
IMG_FAIL = {}

# إحصائيات خفيفة
STATS = {"tg_sent": 0, "tg_failed": 0, "push_sent": 0, "events": 0}

_http = None


def http() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=8.0),
            follow_redirects=True,
            headers={"User-Agent": C.UA},
            limits=httpx.Limits(max_connections=60, max_keepalive_connections=20, keepalive_expiry=30),
        )
    return _http


async def close_http():
    global _http
    if _http is not None:
        try:
            await _http.aclose()
        except Exception:
            pass
        _http = None
