"""طبقة HTTP خفيفة فوق Starlette: مسارات، صلاحيات، أخطاء موحّدة، وضغط JSON."""
import gzip
import json
import traceback

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import config as C
from .security import user_from_token, is_owner, can_discord


class ApiError(Exception):
    def __init__(self, status, msg, **extra):
        super().__init__(msg)
        self.status = status
        self.msg = msg
        self.extra = extra


def fail(status, msg, **extra):
    raise ApiError(status, msg, **extra)


def _dumps(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


class Json(Response):
    media_type = "application/json"

    def __init__(self, content, status_code=200, headers=None, request=None):
        body = _dumps(content)
        h = dict(headers or {})
        h.setdefault("cache-control", "no-store")
        if request is not None and len(body) > 1400 and "gzip" in (request.headers.get("accept-encoding") or ""):
            body = gzip.compress(body, 5)
            h["content-encoding"] = "gzip"
            h["vary"] = "Accept-Encoding"
        super().__init__(body, status_code=status_code, headers=h, media_type=self.media_type)


class Req:
    """غلاف للطلب: المستخدم، المعاملات، الجسم"""
    __slots__ = ("r", "user", "_json")

    def __init__(self, r: Request, user):
        self.r = r
        self.user = user
        self._json = None

    @property
    def ip(self):
        xf = self.r.headers.get("x-forwarded-for", "")
        if xf:
            return xf.split(",")[0].strip()[:60]
        return (self.r.client.host if self.r.client else "")[:60]

    @property
    def username(self):
        return self.user["username"] if self.user else ""

    @property
    def owner(self):
        return is_owner(self.user)

    @property
    def query(self):
        return self.r.query_params

    @property
    def cookie(self):
        return self.r.cookies.get(C.COOKIE_NAME) or ""

    def p(self, name):
        return self.r.path_params.get(name)

    async def json(self):
        if self._json is None:
            try:
                d = await self.r.json()
                self._json = d if isinstance(d, dict) else {}
            except Exception:
                self._json = {}
        return self._json

    async def form(self):
        return await self.r.form()

    @property
    def secure(self):
        proto = self.r.headers.get("x-forwarded-proto", "") or self.r.url.scheme
        return proto == "https"


def current_user(request: Request):
    return user_from_token(request.cookies.get(C.COOKIE_NAME))


routes = []


def api(path, methods=("GET",), auth=None):
    """auth: None | 'user' | 'owner' | 'discord' | 'optional'"""
    if isinstance(methods, str):
        methods = (methods,)

    def deco(fn):
        async def endpoint(request: Request):
            try:
                u = current_user(request) if auth else None
                if auth in ("user", "owner", "discord") and not u:
                    return Json({"error": "غير مسجل", "auth": False}, 401)
                if auth == "owner" and not is_owner(u):
                    return Json({"error": "غير مصرح"}, 403)
                if auth == "discord" and not can_discord(u):
                    return Json({"error": "غير مصرح — تحتاج وصول الديسكورد"}, 403)
                res = await fn(Req(request, u))
                if isinstance(res, Response):
                    return res
                return Json(res if res is not None else {"ok": True}, request=request)
            except ApiError as e:
                body = {"error": e.msg}
                body.update(e.extra)
                return Json(body, e.status)
            except Exception as e:
                print("[API] " + request.method + " " + request.url.path + " → " + repr(e))
                traceback.print_exc()
                return Json({"error": "خطأ داخلي في الخادم"}, 500)

        endpoint.__name__ = fn.__name__
        routes.append(Route(path, endpoint, methods=list(methods)))
        return fn

    return deco


def ids_list(v, limit=50):
    out = []
    for x in (v or []):
        s = str(x).strip()
        if s.lstrip("-").isdigit():
            out.append(int(s))
    return out[:limit]


def truthy(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def opt_int(v, lo=0, hi=9999):
    if v in ("", None):
        return None
    try:
        return max(lo, min(hi, int(float(v))))
    except Exception:
        return None
