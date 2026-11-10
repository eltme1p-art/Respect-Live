"""المصادقة والجلسات والحماية."""
import hashlib
import secrets
import time

from . import config as C
from .db import q1, run, val, cfg, now


def new_salt():
    return secrets.token_hex(16)


def hash_pw(pw, salt):
    # نفس الخوارزمية السابقة بالضبط حتى تبقى كلمات المرور الحالية صالحة
    return hashlib.pbkdf2_hmac("sha256", str(pw).encode(), bytes.fromhex(salt), 100000).hex()


def check_pw(pw, salt, h):
    try:
        return secrets.compare_digest(hash_pw(pw, salt), h or "")
    except Exception:
        return False


# ═══ Rate limiting (ذاكرة — نافذة منزلقة) ═══
_rate = {}


def rate_ok(key, max_per_min=C.MAX_PER_MIN_TG, window=60):
    t = time.time()
    lst = _rate.get(key)
    if lst is None:
        lst = _rate[key] = []
    lst[:] = [x for x in lst if t - x < window]
    if len(lst) >= max_per_min:
        return False
    lst.append(t)
    if len(_rate) > 20000:
        for k in list(_rate.keys())[:5000]:
            _rate.pop(k, None)
    return True


def rate_hit_count(key, window=900):
    t = time.time()
    return len([x for x in _rate.get(key, []) if t - x < window])


def log_sec(username, action, detail="", ip=""):
    try:
        run("INSERT INTO security_log(ts,username,action,detail,ip) VALUES(?,?,?,?,?)",
            (now(), username or "anon", (action or "")[:60], (detail or "")[:300], (ip or "")[:60]))
    except Exception:
        pass


# ═══ الجلسات ═══
def new_session(username):
    tok = secrets.token_urlsafe(32)
    run("INSERT INTO sessions(token,username,created,expires) VALUES(?,?,?,?)", (tok, username, now(), now() + C.SESSION_TTL))
    return tok


def kill_sessions(username, except_token=None):
    if except_token:
        n = val("SELECT COUNT(*) FROM sessions WHERE username=? AND token<>?", (username, except_token), 0)
        run("DELETE FROM sessions WHERE username=? AND token<>?", (username, except_token))
        return n
    run("DELETE FROM sessions WHERE username=?", (username,))
    return 0


_touch = {}


def user_from_token(tok):
    if not tok or len(tok) > 200:
        return None
    row = q1("SELECT s.token AS _tok, s.expires AS _exp, u.* FROM sessions s JOIN users u ON u.username=s.username "
             "WHERE s.token=? AND s.expires>? AND u.active=1 AND u.banned=0", (tok, now()))
    if not row:
        return None
    # تمديد الجلسة تلقائياً للمستخدم النشط (مرة كل ساعة على الأكثر)
    if row["_exp"] - now() < C.SESSION_TTL - 3600 and _touch.get(tok, 0) < time.time() - 3600:
        _touch[tok] = time.time()
        run("UPDATE sessions SET expires=? WHERE token=?", (now() + C.SESSION_TTL, tok))
    return row


def is_owner(u):
    return bool(u) and u.get("role") == "owner"


def can_discord(u):
    return bool(u) and (u.get("role") == "owner" or u.get("can_discord") == 1)


def maintenance_blocks(u):
    return cfg("maintenance", "0") == "1" and not is_owner(u)
