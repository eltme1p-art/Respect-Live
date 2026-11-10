"""الإعدادات — نفس متغيرات البيئة السابقة بالضبط (لا شيء جديد إلزامي)."""
import os
import secrets
import hashlib
from dotenv import load_dotenv

load_dotenv()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
SESSION_SECRET = os.getenv("SESSION_SECRET", "") or secrets.token_hex(32)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
WATCH_CHANNELS = [c.strip() for c in os.getenv("DISCORD_WATCH_CHANNELS", "").split(",") if c.strip()]
ALLOWED_GUILDS = [g.strip() for g in os.getenv("DISCORD_ALLOWED_GUILDS", "").split(",") if g.strip()]
VAPID_PUBLIC = os.getenv("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE = os.getenv("VAPID_PRIVATE_KEY", "").strip()
VAPID_EMAIL = os.getenv("VAPID_EMAIL", "mailto:admin@example.com")
SITE_NAME = os.getenv("SITE_NAME", "Respect Live")
SITE_COLOR = os.getenv("SITE_COLOR", "#0b55ea")
DB_PATH = os.getenv("DB_PATH", "respect.db")
GROQ_ENV_KEY = os.getenv("GROQ_API_KEY", "").strip()
TWITTER_ENV_KEY = os.getenv("TWITTER_BEARER_TOKEN", "").strip()

PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
if not PUBLIC_URL and os.getenv("RAILWAY_PUBLIC_DOMAIN"):
    PUBLIC_URL = "https://" + os.getenv("RAILWAY_PUBLIC_DOMAIN").strip().rstrip("/")

# سرّ Webhook تيليجرام — مشتق تلقائياً (تيليجرام يرسله في كل طلب ونرفض أي طلب بدونه)
TG_WEBHOOK_SECRET = hashlib.sha256(("tgwh:" + SESSION_SECRET + ":" + TELEGRAM_TOKEN).encode()).hexdigest()[:48]

# ─── ثوابت ───
SESSION_TTL = 7 * 24 * 3600
COOKIE_NAME = "rl_sid"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
YT_HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9", "Cookie": "CONSENT=YES+cb; SOCS=CAI"}
MAX_PER_MIN_TG = 30
MAX_PER_MIN_CH = 15
BATCH_KICK = 30
BATCH_TT = 20
BATCH_YT = 30
BATCH_TW = 30
MAX_IMAGE_SIZE = 2 * 1024 * 1024
VERIFY_TTL = 600
LINK_CODE_TTL = 600
MEMBER_CHECK_TTL = 600
TG_LOG_KEEP = 25
TG_LOG_DAYS = 14

KIND_TABLE = {"kick": "kick_channels", "yt": "yt_channels", "tg": "tg_channels", "tw": "tw_channels", "tt": "tt_channels"}
KIND_IDCOL = {"kick": "slug", "yt": "channel_id", "tg": "chat_id", "tw": "username", "tt": "slug"}
KINDS = tuple(KIND_TABLE.keys())

THEMES = [
    {"id": "default", "n": "الافتراضي", "c1": "#05070c", "c2": "#0c111b", "ac": "#2f6bff"},
    {"id": "saudi", "n": "اليوم الوطني", "c1": "#03271a", "c2": "#0b5a33", "ac": "#3ddc84"},
    {"id": "founding", "n": "يوم التأسيس", "c1": "#24190a", "c2": "#0b3f2a", "ac": "#e6b85c"},
    {"id": "ramadan", "n": "رمضان", "c1": "#070f24", "c2": "#162c55", "ac": "#f5c04a"},
    {"id": "fitr", "n": "عيد الفطر", "c1": "#071f20", "c2": "#14514a", "ac": "#ffd166"},
    {"id": "adha", "n": "عيد الأضحى", "c1": "#1c1208", "c2": "#4a3217", "ac": "#f0b84d"},
]

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(BASE_DIR, "web")
