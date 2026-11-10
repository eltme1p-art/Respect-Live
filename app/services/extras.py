"""إشعارات المتصفح (Push)، الذكاء الاصطناعي (Groq)، الحدود، والتوزيع الموحّد للتنبيهات."""
import asyncio
import json
import re

from .. import config as C
from .. import state
from ..db import q, q1, run, val, cfg, cfg_int
from . import telegram as tg


# ═══ Push ═══
def push_available():
    return bool(C.VAPID_PUBLIC and C.VAPID_PRIVATE)


def _webpush_blocking(sub, payload):
    from pywebpush import webpush
    webpush(subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
            data=payload, vapid_private_key=C.VAPID_PRIVATE, vapid_claims={"sub": C.VAPID_EMAIL}, timeout=10)


async def push_send_to_user(username, title, body, image="", url="/", tag=""):
    if not push_available():
        return 0
    try:
        from pywebpush import WebPushException
    except ImportError:
        return 0
    subs = q("SELECT * FROM push_subs WHERE username=?", (username,))
    if not subs:
        return 0
    if image and image.startswith("/") and C.PUBLIC_URL:
        image = C.PUBLIC_URL + image
    payload = json.dumps({"title": (title or "")[:80], "body": (body or "")[:200], "image": image or "", "url": url or "/", "tag": tag or "rl"})
    sent = 0
    for sub in subs:
        try:
            # webpush متزامن — نشغله في Thread حتى لا يجمّد الخادم
            await asyncio.to_thread(_webpush_blocking, sub, payload)
            sent += 1
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410):
                run("DELETE FROM push_subs WHERE id=?", (sub["id"],))
        except Exception:
            pass
    state.STATS["push_sent"] += sent
    return sent


def push_bg(*a, **kw):
    if push_available():
        asyncio.create_task(push_send_to_user(*a, **kw))


# ═══ Groq ═══
def get_groq_key():
    return C.GROQ_ENV_KEY or cfg("groq_api_key", "")


def groq_available():
    return bool(get_groq_key())


def groq_source():
    return "env" if C.GROQ_ENV_KEY else ("db" if cfg("groq_api_key", "") else "none")


async def groq_rewrite(text, prompt="", model=None):
    key = get_groq_key()
    if not key:
        return None
    model = model or cfg("groq_model", "llama-3.3-70b-versatile")
    sysmsg = prompt.strip() if prompt else "أعد صياغة الرسالة بأسلوب واضح ومختصر بالعربية. لا تكتب أي مقدمة أو خاتمة، أعد النص فقط."
    try:
        r = await state.http().post("https://api.groq.com/openai/v1/chat/completions", timeout=30,
                                    headers={"authorization": "Bearer " + key, "content-type": "application/json"},
                                    json={"model": model, "messages": [{"role": "system", "content": sysmsg}, {"role": "user", "content": text[:4000]}],
                                          "temperature": 0.4, "max_tokens": 1024})
        if r.status_code != 200:
            return None
        return (r.json().get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    except Exception as e:
        print("[Groq] " + str(e))
        return None


# ═══ الحدود ═══
def get_user_limits(username, role):
    """الأولوية: تخصيص الإدارة ← حدود الأعضاء ← الافتراضي"""
    if role == "owner":
        return {"kick": 9999, "yt": 9999, "tg": 9999, "tw": 9999, "tt": 9999, "is_member": True, "has_linked_tg": True}
    u = q1("SELECT lim_kick,lim_yt,lim_tg,lim_tw,is_member,linked_tg_id FROM users WHERE username=?", (username,)) or \
        {"lim_kick": None, "lim_yt": None, "lim_tg": None, "lim_tw": None, "is_member": 0, "linked_tg_id": ""}
    member = bool(u["is_member"]) and bool(u["linked_tg_id"] or "")

    def d(k, dflt_def, dflt_bonus):
        return cfg_int(("bonus_lim_" if member else "default_lim_") + k, dflt_bonus if member else dflt_def)
    return {
        "kick": u["lim_kick"] if u["lim_kick"] is not None else d("kick", 10, 50),
        "yt": u["lim_yt"] if u["lim_yt"] is not None else d("yt", 5, 25),
        "tg": u["lim_tg"] if u["lim_tg"] is not None else d("tg", 1, 5),
        "tw": u["lim_tw"] if u["lim_tw"] is not None else d("tw", 3, 10),
        "tt": d("tt", 5, 25),
        "is_member": member, "has_linked_tg": bool(u["linked_tg_id"]),
    }


def usage_counts(username):
    out = {}
    for k, t in C.KIND_TABLE.items():
        out[k] = val("SELECT COUNT(*) FROM " + t + " WHERE added_by=?", (username,), 0)
    return out


def limit_info(username, kind, role, lim=None):
    lim = lim or get_user_limits(username, role)
    limit = lim.get(kind, 10)
    used = val("SELECT COUNT(*) FROM " + C.KIND_TABLE[kind] + " WHERE added_by=?", (username,), 0)
    return {"used": used, "limit": limit, "remaining": max(0, limit - used), "is_member": lim.get("is_member", False), "has_linked_tg": lim.get("has_linked_tg", False)}


def check_limit(username, kind, role, adding=1):
    if role == "owner":
        return True
    i = limit_info(username, kind, role)
    return i["used"] + adding <= i["limit"]


# ═══ التوزيع الموحّد: إشعار داخلي + Push + تيليجرام ═══
def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "")


def add_notif(username, title, body, image="", btn="", url="", kind="admin", ts=None):
    from ..db import now
    run("INSERT INTO notifs(username,title,body,image,btn_text,btn_url,kind,ts,is_read) VALUES(?,?,?,?,?,?,?,?,0)",
        (username, (title or "")[:200], (body or "")[:500], image or "", btn or "", url or "", kind, ts or now()))


async def fanout(owner, *, kind, title, body, text, image, btn, url, source, source_name, push_tag):
    """تنبيه واحد لصاحب القناة: سجل داخلي + إشعار متصفح + كل قنواته في تيليجرام"""
    state.STATS["events"] += 1
    add_notif(owner, title, body, image, btn, url, kind)
    push_bg(owner, title, body or title, image, url, push_tag)
    rows = q("SELECT * FROM tg_channels WHERE added_by=? AND enabled=1", (owner,))
    if rows:
        await tg.tg_deliver(rows, text, image, btn, url, source, source_name)
