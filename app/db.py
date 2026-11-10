"""قاعدة البيانات — نفس الجداول السابقة (متوافقة 100% مع البيانات الموجودة) + كاش للإعدادات."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from . import config as C

_local = threading.local()


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(C.DB_PATH, timeout=15, check_same_thread=False, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=15000")
        c.execute("PRAGMA temp_store=MEMORY")
        c.execute("PRAGMA cache_size=-16000")
        _local.c = c
    return c


def q(sql, params=()):
    return [dict(r) for r in conn().execute(sql, params).fetchall()]


def q1(sql, params=()):
    r = conn().execute(sql, params).fetchone()
    return dict(r) if r else None


def val(sql, params=(), default=None):
    r = conn().execute(sql, params).fetchone()
    return r[0] if r else default


def run(sql, params=()):
    return conn().execute(sql, params)


def many(sql, seq):
    return conn().executemany(sql, seq)


@contextmanager
def tx():
    """معاملة ذرّية — لا تضع await بداخلها"""
    c = conn()
    if c.in_transaction:
        yield c
        return
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise


def placeholders(n):
    return ",".join("?" * n)


def now():
    return int(time.time())


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, display TEXT DEFAULT '', avatar TEXT DEFAULT '', pass_hash TEXT DEFAULT '', salt TEXT DEFAULT '', role TEXT DEFAULT 'user', active INTEGER DEFAULT 1, banned INTEGER DEFAULT 0, lim_kick INTEGER, lim_yt INTEGER, lim_tg INTEGER, can_discord INTEGER DEFAULT 0, created INTEGER, last_login INTEGER, linked_tg_id TEXT DEFAULT '', linked_tg_username TEXT DEFAULT '', linked_tg_name TEXT DEFAULT '', is_member INTEGER DEFAULT 0, member_checked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT NOT NULL, created INTEGER, expires INTEGER);
CREATE INDEX IF NOT EXISTS idx_sess_exp ON sessions(expires);
CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS default_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, identifier TEXT NOT NULL, name TEXT DEFAULT '', avatar TEXT DEFAULT '', enabled INTEGER DEFAULT 1, created INTEGER, UNIQUE(kind, identifier));
CREATE TABLE IF NOT EXISTS kick_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL, name TEXT DEFAULT '', avatar TEXT DEFAULT '', banner TEXT DEFAULT '', msg TEXT DEFAULT '', btn_text TEXT DEFAULT '', enabled INTEGER DEFAULT 1, auto_send INTEGER DEFAULT 1, live INTEGER DEFAULT 0, title TEXT DEFAULT '', viewers INTEGER DEFAULT 0, thumb TEXT DEFAULT '', last_check INTEGER DEFAULT 0, added_by TEXT NOT NULL, created INTEGER, UNIQUE(slug, added_by));
CREATE INDEX IF NOT EXISTS idx_kick_by ON kick_channels(added_by);
CREATE TABLE IF NOT EXISTS tt_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL, name TEXT DEFAULT '', avatar TEXT DEFAULT '', banner TEXT DEFAULT '', msg TEXT DEFAULT '', btn_text TEXT DEFAULT '', enabled INTEGER DEFAULT 1, auto_send INTEGER DEFAULT 1, live INTEGER DEFAULT 0, title TEXT DEFAULT '', viewers INTEGER DEFAULT 0, thumb TEXT DEFAULT '', last_check INTEGER DEFAULT 0, added_by TEXT NOT NULL, created INTEGER, UNIQUE(slug, added_by));
CREATE INDEX IF NOT EXISTS idx_tt_by ON tt_channels(added_by);
CREATE TABLE IF NOT EXISTS yt_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT NOT NULL, handle TEXT DEFAULT '', name TEXT DEFAULT '', avatar TEXT DEFAULT '', banner TEXT DEFAULT '', msg TEXT DEFAULT '', btn_text TEXT DEFAULT '', enabled INTEGER DEFAULT 1, auto_send INTEGER DEFAULT 1, last_video TEXT DEFAULT '', last_check INTEGER DEFAULT 0, added_by TEXT NOT NULL, created INTEGER, UNIQUE(channel_id, added_by));
CREATE INDEX IF NOT EXISTS idx_yt_by ON yt_channels(added_by);
CREATE TABLE IF NOT EXISTS tg_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, username TEXT DEFAULT '', name TEXT DEFAULT '', avatar TEXT DEFAULT '', banner TEXT DEFAULT '', enabled INTEGER DEFAULT 1, verified INTEGER DEFAULT 0, owner_tg_id TEXT DEFAULT '', owner_tg_username TEXT DEFAULT '', added_by TEXT NOT NULL, created INTEGER, UNIQUE(chat_id, added_by));
CREATE INDEX IF NOT EXISTS idx_tg_by ON tg_channels(added_by);
CREATE INDEX IF NOT EXISTS idx_tg_chat ON tg_channels(chat_id);
CREATE TABLE IF NOT EXISTS tg_known_channels (chat_id TEXT PRIMARY KEY, username TEXT DEFAULT '', name TEXT DEFAULT '', avatar TEXT DEFAULT '', type TEXT DEFAULT '', last_seen INTEGER);
CREATE INDEX IF NOT EXISTS idx_tkc_un ON tg_known_channels(username);
CREATE TABLE IF NOT EXISTS tg_verifications (id INTEGER PRIMARY KEY AUTOINCREMENT, site_username TEXT NOT NULL, tg_username TEXT NOT NULL DEFAULT '', tg_user_id TEXT DEFAULT '', tg_chat_id TEXT DEFAULT '', tg_chat_name TEXT DEFAULT '', tg_chat_avatar TEXT DEFAULT '', code TEXT DEFAULT '', status TEXT DEFAULT 'pending', tg_msg_id INTEGER DEFAULT 0, created INTEGER, expires INTEGER);
CREATE INDEX IF NOT EXISTS idx_tgv_status ON tg_verifications(status, expires);
CREATE TABLE IF NOT EXISTS tg_link_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, site_username TEXT NOT NULL, tg_user_id TEXT NOT NULL, tg_username TEXT DEFAULT '', tg_first_name TEXT DEFAULT '', code TEXT NOT NULL, status TEXT DEFAULT 'pending', created INTEGER, expires INTEGER);
CREATE INDEX IF NOT EXISTS idx_tlc_status ON tg_link_codes(status, expires);
CREATE TABLE IF NOT EXISTS feed_subs (id INTEGER PRIMARY KEY AUTOINCREMENT, feed_id INTEGER NOT NULL, tg_channel_id INTEGER NOT NULL, username TEXT NOT NULL, enabled INTEGER DEFAULT 1, created INTEGER, UNIQUE(feed_id, tg_channel_id));
CREATE INDEX IF NOT EXISTS idx_fs_feed ON feed_subs(feed_id, enabled);
CREATE TABLE IF NOT EXISTS discord_feeds (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT NOT NULL, channel_name TEXT DEFAULT '', guild_id TEXT DEFAULT '', template TEXT DEFAULT '', btn_text TEXT DEFAULT 'عرض الروم', source_type TEXT DEFAULT 'generic', target_tg_ids TEXT DEFAULT '', enabled INTEGER DEFAULT 1, use_original INTEGER DEFAULT 1, ignore_bots TEXT DEFAULT '', keyword_rules TEXT DEFAULT '', fixed_image TEXT DEFAULT '', room_url TEXT DEFAULT '', use_ai INTEGER DEFAULT 0, ai_prompt TEXT DEFAULT '', added_by TEXT NOT NULL, created INTEGER, UNIQUE(channel_id));
CREATE INDEX IF NOT EXISTS idx_df_ch ON discord_feeds(channel_id, enabled);
CREATE TABLE IF NOT EXISTS discord_seen (message_id TEXT PRIMARY KEY, ts INTEGER);
CREATE INDEX IF NOT EXISTS idx_ds_ts ON discord_seen(ts);
CREATE TABLE IF NOT EXISTS discord_bots (id TEXT PRIMARY KEY, name TEXT DEFAULT '', avatar TEXT DEFAULT '', first_seen INTEGER, last_seen INTEGER, seen_count INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS notifs (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, title TEXT DEFAULT '', body TEXT DEFAULT '', image TEXT DEFAULT '', btn_text TEXT DEFAULT '', btn_url TEXT DEFAULT '', kind TEXT DEFAULT 'admin', ts INTEGER, is_read INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_notifs ON notifs(username, ts);
CREATE TABLE IF NOT EXISTS recent_videos (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT NOT NULL, ch_name TEXT DEFAULT '', title TEXT DEFAULT '', thumb TEXT DEFAULT '', url TEXT DEFAULT '', ts INTEGER, added_by TEXT NOT NULL, UNIQUE(video_id, added_by));
CREATE TABLE IF NOT EXISTS suggestions (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, text TEXT NOT NULL, is_read INTEGER DEFAULT 0, ts INTEGER);
CREATE TABLE IF NOT EXISTS push_subs (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, endpoint TEXT UNIQUE NOT NULL, p256dh TEXT NOT NULL, auth TEXT NOT NULL, ts INTEGER);
CREATE TABLE IF NOT EXISTS images (id TEXT PRIMARY KEY, mime TEXT NOT NULL, data BLOB NOT NULL, size INTEGER NOT NULL, uploaded_by TEXT, created INTEGER);
CREATE TABLE IF NOT EXISTS rate_limits (k TEXT PRIMARY KEY, cnt INTEGER, ts INTEGER);
CREATE TABLE IF NOT EXISTS security_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, username TEXT, action TEXT, detail TEXT, ip TEXT);
CREATE TABLE IF NOT EXISTS news (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT DEFAULT '', image TEXT DEFAULT '', kind TEXT DEFAULT 'news', enabled INTEGER DEFAULT 1, created INTEGER);
CREATE TABLE IF NOT EXISTS news_read (username TEXT NOT NULL, news_id INTEGER NOT NULL, ts INTEGER, PRIMARY KEY(username, news_id));
CREATE TABLE IF NOT EXISTS tw_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, user_id TEXT DEFAULT '', name TEXT DEFAULT '', avatar TEXT DEFAULT '', banner TEXT DEFAULT '', msg TEXT DEFAULT '', btn_text TEXT DEFAULT '', filters TEXT DEFAULT '', enabled INTEGER DEFAULT 1, auto_send INTEGER DEFAULT 1, last_tweet TEXT DEFAULT '', last_check INTEGER DEFAULT 0, added_by TEXT NOT NULL, created INTEGER, UNIQUE(username, added_by));
CREATE INDEX IF NOT EXISTS idx_tw_by ON tw_channels(added_by);
CREATE TABLE IF NOT EXISTS tg_sent_log (id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER NOT NULL, chat_id TEXT DEFAULT '', source TEXT DEFAULT '', source_name TEXT DEFAULT '', text TEXT DEFAULT '', image TEXT DEFAULT '', url TEXT DEFAULT '', ok INTEGER DEFAULT 1, ts INTEGER);
CREATE INDEX IF NOT EXISTS idx_tsl ON tg_sent_log(tg_id, id);
CREATE TABLE IF NOT EXISTS tg_bot_users (tg_id TEXT PRIMARY KEY, username TEXT DEFAULT '', first_name TEXT DEFAULT '', last_seen INTEGER);
CREATE INDEX IF NOT EXISTS idx_tbu_un ON tg_bot_users(username);
CREATE TABLE IF NOT EXISTS img_cache (url TEXT PRIMARY KEY, img_id TEXT NOT NULL, ts INTEGER);
"""

# فهارس إضافية للأداء (آمنة على قاعدة بيانات موجودة)
EXTRA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_kick_slug ON kick_channels(slug, enabled, last_check);
CREATE INDEX IF NOT EXISTS idx_tt_slug ON tt_channels(slug, enabled, last_check);
CREATE INDEX IF NOT EXISTS idx_yt_cid ON yt_channels(channel_id, enabled, last_check);
CREATE INDEX IF NOT EXISTS idx_tw_user ON tw_channels(username);
CREATE INDEX IF NOT EXISTS idx_kick_live ON kick_channels(live, enabled);
CREATE INDEX IF NOT EXISTS idx_notifs_unread ON notifs(username, is_read);
CREATE INDEX IF NOT EXISTS idx_sess_user ON sessions(username);
CREATE INDEX IF NOT EXISTS idx_rv_by ON recent_videos(added_by, ts);
CREATE INDEX IF NOT EXISTS idx_fs_user ON feed_subs(username);
CREATE INDEX IF NOT EXISTS idx_seclog_user ON security_log(username, id);
CREATE INDEX IF NOT EXISTS idx_tsl_ts ON tg_sent_log(ts);
"""

COLUMN_MIGRATIONS = [
    ("users", "can_discord", "INTEGER DEFAULT 0"), ("users", "avatar", "TEXT DEFAULT ''"),
    ("users", "linked_tg_id", "TEXT DEFAULT ''"), ("users", "linked_tg_username", "TEXT DEFAULT ''"),
    ("users", "linked_tg_name", "TEXT DEFAULT ''"), ("users", "is_member", "INTEGER DEFAULT 0"),
    ("users", "member_checked", "INTEGER DEFAULT 0"),
    ("kick_channels", "btn_text", "TEXT DEFAULT ''"), ("kick_channels", "auto_send", "INTEGER DEFAULT 1"),
    ("yt_channels", "btn_text", "TEXT DEFAULT ''"), ("yt_channels", "auto_send", "INTEGER DEFAULT 1"),
    ("yt_channels", "banner", "TEXT DEFAULT ''"),
    ("tg_channels", "banner", "TEXT DEFAULT ''"), ("tg_channels", "verified", "INTEGER DEFAULT 0"),
    ("tg_channels", "owner_tg_id", "TEXT DEFAULT ''"), ("tg_channels", "owner_tg_username", "TEXT DEFAULT ''"),
    ("discord_feeds", "btn_text", "TEXT DEFAULT 'عرض الروم'"), ("discord_feeds", "target_tg_ids", "TEXT DEFAULT ''"),
    ("discord_feeds", "guild_id", "TEXT DEFAULT ''"), ("discord_feeds", "use_original", "INTEGER DEFAULT 1"),
    ("discord_feeds", "ignore_bots", "TEXT DEFAULT ''"), ("discord_feeds", "keyword_rules", "TEXT DEFAULT ''"),
    ("discord_feeds", "fixed_image", "TEXT DEFAULT ''"), ("discord_feeds", "room_url", "TEXT DEFAULT ''"),
    ("discord_feeds", "use_ai", "INTEGER DEFAULT 0"), ("discord_feeds", "ai_prompt", "TEXT DEFAULT ''"),
    ("users", "lim_tw", "INTEGER"), ("default_channels", "alias", "TEXT DEFAULT ''"),
    ("tg_verifications", "tg_chat_username", "TEXT DEFAULT ''"), ("users", "ui_mode", "TEXT DEFAULT ''"),
    ("discord_feeds", "display_name", "TEXT DEFAULT ''"), ("tg_link_codes", "token", "TEXT DEFAULT ''"),
    ("tg_known_channels", "photo_uid", "TEXT DEFAULT ''"),
]

DEFAULT_SETTINGS = {
    "site_name": C.SITE_NAME, "site_sub": "STREAM MONITOR",
    "hero_title": "مراقبة", "hero_accent": "القنوات.",
    "hero_text": "تابع قنواتك على كيك ويوتيوب وX وتيك توك وتيليجرام في مكان واحد.",
    "tpl_kick": "<b>{name}</b>\nبدأ بثاً مباشراً الآن\n\n<b>{title}</b>\n\n⚪🔴",
    "tpl_yt": "<b>{title}</b>\n\n\n⚪🔴",
    "tpl_discord": "<b>{author_no_at}</b>\n\n<b>{content}</b>",
    "tpl_twitter": "<b>{author_no_at}</b>\n\n<b>{content}</b>",
    "tpl_youtube_dc": "<b>{title}</b>\n\n<b>{author_no_at}</b>",
    "tpl_tg_verify": "🔐 <b>طلب توثيق قناة</b>\n\nالمستخدم <code>{site_user}</code> يحاول ربط قناة <b>{chat_name}</b>.\n\n<b>هل أنت من يحاول ذلك؟</b>",
    "tpl_tg_success": "✅ <b>تم الربط بنجاح</b>\n\nالقناة: <b>{chat_name}</b>\nالمستخدم: <code>{site_user}</code>\n\nيمكنك الآن إدارتها من الموقع.",
    "tpl_tg_link": "🔐 <b>ربط حساب</b>\n\nرمز التحقق الخاص بك:\n\n<code>{code}</code>\n\n<i>صالح لمدة 10 دقائق. لا تشاركه مع أحد.</i>",
    "btn_kick": "شاهد البث", "btn_yt": "شاهد الفيديو", "btn_tg": "عرض القناة", "btn_discord": "عرض الروم",
    "lim_kick": "10", "lim_yt": "5", "lim_tg": "3", "lim_tw": "3",
    "tpl_tw": "<b>{name}</b>\n\n{text}", "btn_tw": "عرض التغريدة",
    "default_lim_tw": "3", "bonus_lim_tw": "10", "tw_interval": "300", "tw_daily_cap": "500",
    "guest_mode": "1", "guest_blur": "14",
    "site_theme": "default", "site_logo": "",
    "site_c1": "#05070c", "site_c2": "#0c111b", "site_ac": C.SITE_COLOR,
    "maintenance": "0", "maintenance_text": "الموقع في صيانة مؤقتة — نرجع قريباً", "maintenance_title": "صيانة مؤقتة",
    "bot_invite_url": "", "bot_name_custom": "Respect Live", "bot_tg_link": "",
    "glass_transparency": "50", "glass_blur": "22", "glass_sat": "185", "glass_sheen": "100",
    "glass_rim": "100", "glass_shadow": "100", "glass_orbs": "55",
    "ui_mode_prompt": "1", "ui_default_mode": "full",
    "glass_corner": "100", "glass_radius": "100", "glass_unify_alpha": "0", "glass_unify_blur": "0",
    "fx_press_zoom": "0", "fx_page_transition": "1", "nav_labels": "1", "pwa_enhance": "1",
    "tiktok_enabled": "1", "feat_haptics": "0", "feat_install_prompt": "1",
    "tpl_tt": "<b>{name}</b>\nبدأ بثاً مباشراً على تيك توك\n\n<b>{title}</b>\n\n⚪🔴", "btn_tt": "شاهد البث",
    "default_lim_tt": "5", "bonus_lim_tt": "25", "lim_tt": "10",
    "login_anim_enabled": "0", "login_anim_code": "", "login_anim_secs": "3",
    "groq_api_key": "", "groq_model": "llama-3.3-70b-versatile",
    "registration_enabled": "1",
    "default_lim_kick": "10", "default_lim_yt": "5", "default_lim_tg": "1",
    "bonus_lim_kick": "50", "bonus_lim_yt": "25", "bonus_lim_tg": "5",
    "required_channel_id": "", "required_channel_url": "", "required_channel_name": "",
    "required_channel_msg": "🚀 للحصول على صلاحيات مضاعفة، انضم إلى قناتنا الرسمية عبر الرابط أدناه ثم اضغط تحقق.",
    "signup_welcome_title": "مرحباً بك!",
    "signup_welcome_text": "حسابك بصلاحيات محدودة (كيك 10، يوتيوب 5، تليجرام 1) وبدون وصول لصفحة الديسكورد. للترقية، اربط حسابك في تيليجرام وانضم للقناة الرسمية.",
    "announce_bar": "",
}

# ═══ كاش الإعدادات (كان كل cfg() يفتح اتصالاً جديداً — الآن من الذاكرة) ═══
_cfg = {}
_cfg_loaded = False


def _load_cfg():
    global _cfg_loaded
    _cfg.clear()
    for r in conn().execute("SELECT k, v FROM settings").fetchall():
        _cfg[r["k"]] = r["v"]
    _cfg_loaded = True


def cfg(k, d=""):
    if not _cfg_loaded:
        _load_cfg()
    v = _cfg.get(k)
    return d if v is None else v


def cfg_int(k, d=0):
    try:
        return int(float(str(cfg(k, str(d))).strip()))
    except Exception:
        return d


def cfg_on(k, d="0"):
    return cfg(k, d) == "1"


def set_cfg(k, v):
    v = "" if v is None else str(v)
    run("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
    _cfg[k] = v


def del_cfg_like(prefix_lt_key):
    run("DELETE FROM settings WHERE k LIKE 'tw_reads_%' AND k < ?", (prefix_lt_key,))
    _load_cfg()


def migrate_tg_channels_per_user():
    row = q1("SELECT sql FROM sqlite_master WHERE type='table' AND name='tg_channels'")
    if not row:
        return
    if "unique(chat_id, added_by)" in (row["sql"] or "").lower():
        return
    print("[DB] Migrating tg_channels to per-user unique...")
    c = conn()
    c.execute("PRAGMA foreign_keys=OFF")
    with tx():
        c.execute("ALTER TABLE tg_channels RENAME TO tg_channels_old")
        c.execute("CREATE TABLE tg_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, username TEXT DEFAULT '', name TEXT DEFAULT '', avatar TEXT DEFAULT '', banner TEXT DEFAULT '', enabled INTEGER DEFAULT 1, verified INTEGER DEFAULT 0, owner_tg_id TEXT DEFAULT '', owner_tg_username TEXT DEFAULT '', added_by TEXT NOT NULL, created INTEGER, UNIQUE(chat_id, added_by))")
        seen = set()
        for r in c.execute("SELECT * FROM tg_channels_old").fetchall():
            key = (r["chat_id"], r["added_by"])
            if key in seen:
                continue
            seen.add(key)
            c.execute("INSERT INTO tg_channels (id, chat_id, username, name, avatar, banner, enabled, verified, owner_tg_id, owner_tg_username, added_by, created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (r["id"], r["chat_id"], r["username"], r["name"], r["avatar"], r["banner"], r["enabled"], r["verified"], r["owner_tg_id"], r["owner_tg_username"], r["added_by"], r["created"]))
        c.execute("DROP TABLE tg_channels_old")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tg_by ON tg_channels(added_by)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tg_chat ON tg_channels(chat_id)")
    c.execute("PRAGMA foreign_keys=ON")
    print("[DB] ✅ tg_channels migration complete")


def init_db(hash_pw, new_salt):
    c = conn()
    c.executescript(SCHEMA)
    for tbl, col, typ in COLUMN_MIGRATIONS:
        try:
            cols = [r["name"] for r in c.execute("PRAGMA table_info(" + tbl + ")").fetchall()]
            if col not in cols:
                c.execute("ALTER TABLE " + tbl + " ADD COLUMN " + col + " " + typ)
        except Exception as e:
            print("[DB] column migration", tbl, col, e)
    try:
        migrate_tg_channels_per_user()
    except Exception as e:
        print("[DB] Migration error: " + str(e))
    try:
        c.executescript(EXTRA_INDEXES)
    except Exception as e:
        print("[DB] index error", e)

    salt = new_salt()
    h = hash_pw(C.ADMIN_PASSWORD, salt)
    with tx():
        if not c.execute("SELECT 1 FROM users WHERE username=?", (C.ADMIN_USERNAME,)).fetchone():
            c.execute("INSERT INTO users(username,display,pass_hash,salt,role,active,banned,can_discord,created) VALUES(?,?,?,?,'owner',1,0,1,?)",
                      (C.ADMIN_USERNAME, C.ADMIN_USERNAME, h, salt, now()))
        else:
            c.execute("UPDATE users SET pass_hash=?, salt=?, role='owner', active=1, banned=0, can_discord=1 WHERE username=?", (h, salt, C.ADMIN_USERNAME))
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings(k,v) VALUES(?,?)", (k, v))
    _load_cfg()

    if cfg("v7_bold_format") != "done":
        set_cfg("tpl_yt", "<b>{title}</b>\n\n\n⚪🔴")
        set_cfg("tpl_discord", "<b>{author_no_at}</b>\n\n<b>{content}</b>")
        set_cfg("v7_bold_format", "done")
    if cfg("tg_verify_migration") != "done":
        try:
            run("UPDATE tg_channels SET verified=1 WHERE verified=0")
        except Exception:
            pass
        set_cfg("tg_verify_migration", "done")
    if cfg("feed_subs_migration") != "done":
        try:
            with tx():
                for f in c.execute("SELECT id, added_by, target_tg_ids FROM discord_feeds").fetchall():
                    try:
                        for tid in json.loads(f["target_tg_ids"] or "[]"):
                            c.execute("INSERT OR IGNORE INTO feed_subs(feed_id, tg_channel_id, username, enabled, created) VALUES(?,?,?,1,?)", (f["id"], int(tid), f["added_by"], now()))
                    except Exception:
                        pass
        except Exception:
            pass
        set_cfg("feed_subs_migration", "done")
    # v10: التصميم الجديد يُظهر أسماء أزرار الشريط افتراضياً
    if cfg("v10_ui") != "done":
        set_cfg("nav_labels", "1")
        set_cfg("v10_ui", "done")
    print("[DB] Ready")


def backup_bytes() -> bytes:
    """نسخة احتياطية متسقة من قاعدة البيانات (sqlite backup API)"""
    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        dst = sqlite3.connect(path)
        with dst:
            conn().backup(dst)
        dst.close()
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except Exception:
            pass
