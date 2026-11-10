"""Respect Live v10 — نقطة تشغيل التطبيق."""
import asyncio
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import Route

from . import config as C
from . import db, jobs, state
from .http import routes
from .security import hash_pw, new_salt
from .services import telegram as tg
from .services import discord_bridge as dcb
from .services.extras import push_available, groq_available

# تسجيل المسارات (الاستيراد يكفي)
from .routes import auth, telegram, channels, content, discord, admin, pages  # noqa: F401


class SecurityHeaders:
    """رؤوس حماية لكل استجابة (ASGI خام = بدون أي تكلفة تُذكر)"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")

        async def _send(msg):
            if msg["type"] == "http.response.start":
                h = msg.setdefault("headers", [])
                names = {k.lower() for k, _ in h}
                add = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"strict-origin-when-cross-origin"),
                       (b"x-frame-options", b"SAMEORIGIN"), (b"permissions-policy", b"camera=(), microphone=(), geolocation=()")]
                if not path.startswith("/api/") and not path.startswith("/assets/"):
                    add.append((b"content-security-policy", (
                        "default-src 'self'; img-src * data: blob:; media-src * data: blob:; "
                        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; "
                        "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-src 'self' blob: data:; "
                        "worker-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'").encode()))
                if scope.get("scheme") == "https" or any(k.lower() == b"x-forwarded-proto" and v == b"https" for k, v in scope.get("headers", [])):
                    add.append((b"strict-transport-security", b"max-age=31536000"))
                for k, v in add:
                    if k not in names:
                        h.append((k, v))
            await send(msg)
        return await self.app(scope, receive, _send)


@asynccontextmanager
async def lifespan(app):
    db.init_db(hash_pw, new_salt)
    pages.load_assets()
    jobs.start()
    await dcb.start()
    if C.TELEGRAM_TOKEN:
        try:
            await tg.setup()
            await tg.tg_bot_id()
            if state.TG_BOT["username"]:
                print("[TG] Bot: https://t.me/" + state.TG_BOT["username"])
        except Exception as e:
            print("[TG] setup error: " + str(e))
    if push_available():
        print("[Push] Enabled")
    if groq_available():
        print("[Groq] Enabled")
    print("[RL] ✅ Respect Live v10 ready")
    yield
    jobs.stop()
    tg.stop()
    await dcb.stop()
    await state.close_http()


def create_app():
    all_routes = list(routes) + [Route("/{path:path}", pages.page_or_asset, methods=["GET", "HEAD"])]
    return SecurityHeaders(Starlette(routes=all_routes, lifespan=lifespan))


app = create_app()
