"""المهام الدورية — مجدول خفيف خاص بنا (بدون APScheduler) مع مراقبة صحة كل مهمة."""
import asyncio
import html as htmllib
import time

from . import config as C
from . import state
from .db import q, run, tx, cfg, cfg_int, set_cfg, del_cfg_like, placeholders, now
from .services import sources as S
from .services.images import cache_remote_image, job_backfill_images
from .services.extras import fanout
from .services import telegram as tg


# ═══ كيك + تيك توك (بث مباشر) ═══
async def _live_job(kind, table, fetch, every, batch, conc, url_of, tpl_key, btn_key, btn_def, label, src):
    due = q("SELECT DISTINCT slug FROM " + table + " WHERE enabled=1 AND last_check<? ORDER BY last_check LIMIT ?", (now() - every, batch))
    slugs = [r["slug"] for r in due]
    if not slugs:
        return
    infos = {}
    sem = asyncio.Semaphore(conc)

    async def f(sl):
        async with sem:
            inf = await fetch(sl)  # طلب واحد لكل قناة مهما كان عدد من أضافها
            if inf:
                if inf.get("avatar"):
                    inf["avatar"] = await cache_remote_image(inf["avatar"])
                if inf.get("banner"):
                    inf["banner"] = await cache_remote_image(inf["banner"])
            infos[sl] = inf
    await asyncio.gather(*(f(sl) for sl in slugs), return_exceptions=True)
    rows = q("SELECT * FROM " + table + " WHERE enabled=1 AND slug IN (" + placeholders(len(slugs)) + ")", tuple(slugs))
    t = now()
    events = []
    with tx() as c:
        for r in rows:
            info = infos.get(r["slug"])
            if not info:
                c.execute("UPDATE " + table + " SET last_check=? WHERE id=?", (t, r["id"]))
                continue
            c.execute("UPDATE " + table + " SET name=?,avatar=?,banner=?,live=?,title=?,viewers=?,thumb=?,last_check=? WHERE id=?",
                      (info["name"] or r["name"], info["avatar"] or r["avatar"], info.get("banner") or r["banner"], 1 if info["live"] else 0,
                       info["title"], info["viewers"], info["thumb"], t, r["id"]))
            if info["live"] and not r["live"] and r["auto_send"]:
                events.append((r, info))

    async def notify(r, info):
        msg_text, msg_img = S.split_msg_img(r["msg"])
        url = url_of(r["slug"])
        text = (msg_text or cfg(tpl_key)).replace("{name}", info["name"]).replace("{title}", info["title"]).replace("{url}", url)
        btn = r["btn_text"] or cfg(btn_key, btn_def)
        image = msg_img or info.get("banner") or info["thumb"]
        await fanout(r["added_by"], kind=kind, title=info["name"] + " يبث الآن", body=info["title"] or label, text=text, image=image,
                     btn=btn, url=url, source=src, source_name=info["name"], push_tag=kind + ":" + str(r["id"]))
    await asyncio.gather(*(notify(r, i) for r, i in events), return_exceptions=True)


async def job_kick():
    await _live_job("kick", "kick_channels", S.kick_fetch, 90, C.BATCH_KICK, 8, lambda s: "https://kick.com/" + s,
                    "tpl_kick", "btn_kick", "شاهد البث", "بث مباشر", "kick")


async def job_tt():
    if cfg("tiktok_enabled", "1") != "1":
        return
    await _live_job("tt", "tt_channels", S.tt_fetch, 120, C.BATCH_TT, 4, lambda s: "https://www.tiktok.com/@" + s + "/live",
                    "tpl_tt", "btn_tt", "شاهد البث", "بث مباشر على تيك توك", "tt")


# ═══ يوتيوب ═══
async def job_yt():
    due = q("SELECT DISTINCT channel_id FROM yt_channels WHERE enabled=1 AND last_check<? ORDER BY last_check LIMIT ?", (now() - 300, C.BATCH_YT))
    cids = [r["channel_id"] for r in due]
    if not cids:
        return
    feeds = {}
    sem = asyncio.Semaphore(8)

    async def f(cid):
        async with sem:
            feeds[cid] = await S.yt_feed(cid)
    await asyncio.gather(*(f(c) for c in cids), return_exceptions=True)
    rows = q("SELECT * FROM yt_channels WHERE enabled=1 AND channel_id IN (" + placeholders(len(cids)) + ")", tuple(cids))
    t = now()
    new_vids = []
    with tx() as c:
        for r in rows:
            items = feeds.get(r["channel_id"])
            if not items:
                c.execute("UPDATE yt_channels SET last_check=? WHERE id=?", (t, r["id"]))
                continue
            latest = items[0]["id"]
            if r["last_video"] and latest != r["last_video"] and r["auto_send"]:
                fresh = []
                for it in items:
                    if it["id"] == r["last_video"]:
                        break
                    fresh.append(it)
                for v in reversed(fresh[:3]):
                    new_vids.append((r, v))
            c.execute("UPDATE yt_channels SET last_video=?,last_check=? WHERE id=?", (latest, t, r["id"]))

    async def notify(r, v):
        thumb = "https://i.ytimg.com/vi/" + v["id"] + "/maxresdefault.jpg"
        url = "https://youtube.com/watch?v=" + v["id"]
        msg_text, msg_img = S.split_msg_img(r["msg"])
        text = (msg_text or cfg("tpl_yt")).replace("{name}", r["name"]).replace("{title}", v["title"]).replace("{url}", url)
        btn = r["btn_text"] or cfg("btn_yt", "شاهد الفيديو")
        run("INSERT OR IGNORE INTO recent_videos(video_id,ch_name,title,thumb,url,ts,added_by) VALUES(?,?,?,?,?,?,?)",
            (v["id"], r["name"], v["title"], thumb, url, t, r["added_by"]))
        await fanout(r["added_by"], kind="yt", title="فيديو جديد من " + r["name"], body=v["title"], text=text, image=msg_img or thumb,
                     btn=btn, url=url, source="yt", source_name=r["name"], push_tag="yt:" + v["id"])
    await asyncio.gather(*(notify(r, v) for r, v in new_vids), return_exceptions=True)


# ═══ X / تويتر ═══
async def job_tw():
    if not S.tw_available() or state.TW["pause_until"] > time.time():
        return
    interval = max(60, cfg_int("tw_interval", 300))
    cap = cfg_int("tw_daily_cap", 500)
    day = time.strftime("%Y%m%d", time.gmtime())
    used = cfg_int("tw_reads_" + day, 0)
    if cap and used >= cap:
        return
    due = q("SELECT DISTINCT lower(username) u FROM tw_channels WHERE enabled=1 AND auto_send=1 AND last_check<? ORDER BY last_check LIMIT ?", (now() - interval, C.BATCH_TW))
    unames = [r["u"] for r in due]
    if not unames:
        return
    rows = q("SELECT * FROM tw_channels WHERE enabled=1 AND auto_send=1 AND lower(username) IN (" + placeholders(len(unames)) + ")", tuple(unames))
    groups = {}
    for r in rows:
        groups.setdefault(r["username"].lower(), []).append(r)
    results = {}
    sem = asyncio.Semaphore(4)

    async def f(un, rs):
        async with sem:
            uid = next((x["user_id"] for x in rs if x["user_id"]), "")
            if not uid:
                info, err, st = await S.tw_resolve(rs[0]["username"])
                if not info:
                    results[un] = (None, err)
                    return
                uid = info["user_id"]
                run("UPDATE tw_channels SET user_id=? WHERE lower(username)=?", (uid, un))
                run("UPDATE tw_channels SET name=?, avatar=? WHERE lower(username)=? AND (name='' OR avatar='')", (info["name"], info["avatar"], un))
            lasts = [x["last_tweet"] for x in rs]
            since = str(min(int(x) for x in lasts)) if all(x and x.isdigit() for x in lasts) else ""
            fl = [S.parse_tw_filters(x["filters"]) for x in rs]
            excl = []
            if all(x["skip_retweets"] for x in fl):
                excl.append("retweets")
            if all(x["skip_replies"] for x in fl):
                excl.append("replies")
            results[un] = await S.tw_timeline(uid, since, excl, 10 if since else 5)
    await asyncio.gather(*(f(un, rs) for un, rs in groups.items()), return_exceptions=True)
    reads = sum(len(v[0]) for v in results.values() if v and v[0] is not None)
    if reads:
        set_cfg("tw_reads_" + day, used + reads)
    t = now()
    events = []
    with tx() as c:
        for r in rows:
            res = results.get(r["username"].lower())
            if not res or not res[0]:
                c.execute("UPDATE tw_channels SET last_check=? WHERE id=?", (t, r["id"]))
                continue
            tweets = res[0]
            newest = max(tweets, key=lambda x: int(x["id"]))["id"]
            if r["last_tweet"] and r["last_tweet"].isdigit():
                fresh = [x for x in tweets if int(x["id"]) > int(r["last_tweet"])]
                flt = S.parse_tw_filters(r["filters"])
                for tw_ in sorted(fresh, key=lambda x: int(x["id"]))[-3:]:
                    if S.tw_pass_filters(tw_, flt):
                        events.append((r, tw_))
                keep = newest if int(newest) > int(r["last_tweet"]) else r["last_tweet"]
            else:
                keep = newest  # أول فحص: نسجّل آخر تغريدة بدون إرسال القديم
            c.execute("UPDATE tw_channels SET last_tweet=?, last_check=? WHERE id=?", (keep, t, r["id"]))

    async def notify(r, tw_):
        name = r["name"] or r["username"]
        url = "https://x.com/" + r["username"] + "/status/" + tw_["id"]
        msg_text, msg_img = S.split_msg_img(r["msg"])
        tpl = msg_text or cfg("tpl_tw", "<b>{name}</b>\n\n{text}")
        text = (tpl.replace("{name}", htmllib.escape(name, quote=False)).replace("{username}", r["username"])
                .replace("{text}", htmllib.escape(tw_["text"][:3500], quote=False)).replace("{url}", url))
        image = msg_img or (tw_["images"][0] if tw_["images"] else "")
        await fanout(r["added_by"], kind="tw", title=name + " — تغريدة جديدة", body=tw_["text"][:400], text=text, image=image,
                     btn=r["btn_text"] or cfg("btn_tw", "عرض التغريدة"), url=url, source="tw", source_name=name, push_tag="tw:" + tw_["id"])
    await asyncio.gather(*(notify(r, x) for r, x in events), return_exceptions=True)


# ═══ العضوية + التنظيف ═══
async def job_membership_check():
    req_ch = cfg("required_channel_id", "").strip()
    if not req_ch or not C.TELEGRAM_TOKEN:
        return
    rows = q("SELECT username, linked_tg_id FROM users WHERE linked_tg_id != '' AND member_checked < ? LIMIT 200", (now() - C.MEMBER_CHECK_TTL,))
    if not rows:
        return
    sem = asyncio.Semaphore(5)
    results = {}

    async def chk(r):
        async with sem:
            try:
                results[r["username"]] = await tg.tg_check_membership(r["linked_tg_id"], req_ch)
            except Exception:
                pass
    await asyncio.gather(*(chk(r) for r in rows), return_exceptions=True)
    with tx() as c:
        for un, ok in results.items():
            c.execute("UPDATE users SET is_member=?, member_checked=? WHERE username=?", (1 if ok else 0, now(), un))


async def job_cleanup():
    t = now()
    with tx() as c:
        c.execute("DELETE FROM discord_seen WHERE ts<?", (t - 7 * 86400,))
        c.execute("DELETE FROM sessions WHERE expires<?", (t,))
        c.execute("DELETE FROM rate_limits WHERE ts<?", (t - 3600,))
        c.execute("DELETE FROM security_log WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY id DESC) rn FROM security_log) WHERE rn > 5000)")
        c.execute("DELETE FROM recent_videos WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY added_by ORDER BY ts DESC) rn FROM recent_videos) WHERE rn>12)")
        c.execute("DELETE FROM notifs WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY username ORDER BY ts DESC) rn FROM notifs) WHERE rn>80)")
        c.execute("DELETE FROM suggestions WHERE ts<?", (t - 90 * 86400,))
        c.execute("DELETE FROM tg_verifications WHERE created<?", (t - 3600,))
        c.execute("DELETE FROM tg_link_codes WHERE created<?", (t - 3600,))
        c.execute("DELETE FROM tg_known_channels WHERE last_seen<?", (t - 30 * 86400,))
        c.execute("DELETE FROM tg_sent_log WHERE ts<?", (t - C.TG_LOG_DAYS * 86400,))
        # صور الكاش اليتيمة (لم تعد مستخدمة) — تخفف حجم قاعدة البيانات
    del_cfg_like("tw_reads_" + time.strftime("%Y%m%d", time.gmtime(time.time() - 3 * 86400)))
    try:
        run("PRAGMA wal_checkpoint(TRUNCATE)")
        run("PRAGMA optimize")
    except Exception:
        pass


# ═══ المجدول ═══
class Job:
    __slots__ = ("name", "fn", "every", "delay", "runs", "fails", "last_run", "last_ok", "last_ms", "last_error", "task")

    def __init__(self, name, fn, every, delay):
        self.name, self.fn, self.every, self.delay = name, fn, every, delay
        self.runs = self.fails = 0
        self.last_run = self.last_ok = 0
        self.last_ms = 0
        self.last_error = ""
        self.task = None

    def info(self):
        return {"name": self.name, "every": self.every, "runs": self.runs, "fails": self.fails, "last_run": self.last_run,
                "last_ok": self.last_ok, "last_ms": self.last_ms, "last_error": self.last_error}


JOBS = []


def add(name, fn, every, delay=5):
    JOBS.append(Job(name, fn, every, delay))


async def _loop(job: Job):
    await asyncio.sleep(job.delay)
    while True:
        t0 = time.time()
        job.last_run = int(t0)
        try:
            await asyncio.wait_for(job.fn(), timeout=max(60, job.every * 3))
            job.last_ok = int(time.time())
            job.last_error = ""
        except asyncio.CancelledError:
            return
        except Exception as e:
            job.fails += 1
            job.last_error = (type(e).__name__ + ": " + str(e))[:200]
            print("[Job " + job.name + "] " + job.last_error)
        job.runs += 1
        job.last_ms = int((time.time() - t0) * 1000)
        await asyncio.sleep(max(1, job.every - (time.time() - t0)))


def start():
    if not JOBS:
        add("kick", job_kick, 30, 4)          # كل 30ث نفحص المستحق (كل قناة تُفحص كل 90ث)
        add("tiktok", job_tt, 40, 8)
        add("youtube", job_yt, 60, 12)
        add("x", job_tw, 60, 16)
        add("membership", job_membership_check, 120, 30)
        add("images", job_backfill_images, 600, 20)
        add("cleanup", job_cleanup, 6 * 3600, 120)
    for j in JOBS:
        if not j.task or j.task.done():
            j.task = asyncio.create_task(_loop(j))


def stop():
    for j in JOBS:
        if j.task:
            j.task.cancel()


def status():
    return [j.info() for j in JOBS]
