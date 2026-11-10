"""ديسكورد: الرومات المربوطة والاشتراكات."""
import json

from .. import config as C
from .. import state
from ..db import q, q1, run, tx, cfg, now
from ..http import api, fail, ids_list
from ..services import discord_bridge as dcb


def _bot_payload(owner):
    return {"bot_ready": dcb.is_ready(), "auto_discovery": not bool(C.WATCH_CHANNELS), "watching": dcb.watching(),
            "bot_info": state.DC["bot"] if owner else {}, "bot_name_custom": cfg("bot_name_custom", "Respect Live") if owner else "",
            "bot_invite_url": cfg("bot_invite_url", "") if owner else "", "self_bot_mode": state.DC["self_bot"] if owner else False}


@api("/api/discord/channels", auth="discord")
async def dc_channels(req):
    return {"channels": state.DC["channels"], "guilds": state.DC["guilds"], **_bot_payload(req.owner)}


@api("/api/discord/refresh", "POST", auth="discord")
async def dc_refresh(req):
    dcb.refresh_cache()
    return {"ok": True, "channels": len(state.DC["channels"]), "guilds": len(state.DC["guilds"]), "bot_ready": dcb.is_ready()}


@api("/api/discord/bots", auth="discord")
async def dc_bots(req):
    return {"rows": q("SELECT id,name,avatar,last_seen,seen_count FROM discord_bots ORDER BY last_seen DESC LIMIT 200")}


@api("/api/discord/feeds", auth="discord")
async def dc_feeds(req):
    owner = req.owner
    rows = q("SELECT * FROM discord_feeds ORDER BY id DESC") if owner else q("SELECT * FROM discord_feeds WHERE enabled=1 ORDER BY id DESC")
    subs = q("SELECT feed_id, tg_channel_id, username FROM feed_subs") if owner else q("SELECT feed_id, tg_channel_id, username FROM feed_subs WHERE username=?", (req.username,))
    my, counts = {}, {}
    for s in subs:
        counts[s["feed_id"]] = counts.get(s["feed_id"], 0) + 1
        if s["username"] == req.username or owner:
            my.setdefault(s["feed_id"], []).append(s["tg_channel_id"])
    if owner:
        tgs = q("SELECT id,name,username,avatar,enabled,added_by FROM tg_channels WHERE enabled=1 AND added_by=? ORDER BY id DESC", (req.username,))
    else:
        tgs = q("SELECT id,name,username,avatar,enabled FROM tg_channels WHERE added_by=? AND enabled=1 ORDER BY id DESC", (req.username,))
    mine_only = {}
    for s in subs:
        if s["username"] == req.username:
            mine_only.setdefault(s["feed_id"], []).append(s["tg_channel_id"])
    for r in rows:
        r["my_subs"] = mine_only.get(r["id"], [])
        r["subs_count"] = counts.get(r["id"], 0)
    return {"rows": rows, "known_channels": state.DC["channels"], "guilds": state.DC["guilds"], "is_owner": owner, "my_tgs": tgs, **_bot_payload(owner)}


@api("/api/discord/feeds", "POST", auth="owner")
async def dc_add_feed(req):
    b = await req.json()
    ch = str(b.get("channel_id") or "").strip()
    if not ch.isdigit():
        fail(400, "channel_id يجب أن يكون رقماً")
    if ch not in state.DC["channels"] and (not C.WATCH_CHANNELS or ch not in C.WATCH_CHANNELS):
        fail(400, "الروم غير موجود في كاش البوت — اضغط تحديث")
    if q1("SELECT 1 x FROM discord_feeds WHERE channel_id=?", (ch,)):
        fail(409, "الروم مضاف مسبقاً")
    kw = b.get("keyword_rules") or []
    run("INSERT INTO discord_feeds(channel_id,channel_name,guild_id,template,btn_text,source_type,target_tg_ids,enabled,use_original,ignore_bots,keyword_rules,fixed_image,room_url,use_ai,ai_prompt,display_name,added_by,created) VALUES(?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?,?)",
        (ch, str(b.get("channel_name") or "")[:100] or (state.DC["channels"].get(ch, {}).get("name") or ch),
         str(b.get("guild_id") or state.DC["channels"].get(ch, {}).get("guild_id") or "")[:30],
         str(b.get("template") or "")[:2000], str(b.get("btn_text") or "عرض الروم")[:60], str(b.get("source_type") or "generic")[:20], "[]",
         1 if b.get("use_original", True) else 0, json.dumps([str(x) for x in (b.get("ignore_bots") or [])][:50]),
         json.dumps(kw if isinstance(kw, list) else []), str(b.get("fixed_image") or "")[:500], str(b.get("room_url") or "")[:500],
         1 if b.get("use_ai") else 0, str(b.get("ai_prompt") or "")[:2000], str(b.get("display_name") or "")[:100], req.username, now()))
    return {"ok": True}


@api("/api/discord/feeds/{fid:int}", "PATCH", auth="owner")
async def dc_patch_feed(req):
    fid = req.p("fid")
    if not q1("SELECT 1 x FROM discord_feeds WHERE id=?", (fid,)):
        fail(404, "غير موجود")
    b = await req.json()
    sets, vals = [], []
    for f in ("template", "btn_text", "fixed_image", "room_url", "ai_prompt", "display_name", "source_type"):
        if f in b:
            sets.append(f + "=?"); vals.append(str(b[f])[:100 if f in ("display_name", "source_type") else 2000])
    for f in ("enabled", "use_original", "use_ai"):
        if f in b:
            sets.append(f + "=?"); vals.append(1 if b[f] else 0)
    if "ignore_bots" in b:
        sets.append("ignore_bots=?"); vals.append(json.dumps([str(x) for x in (b["ignore_bots"] or [])][:50]))
    if "keyword_rules" in b:
        kw = b["keyword_rules"] or []
        sets.append("keyword_rules=?"); vals.append(json.dumps(kw if isinstance(kw, list) else []))
    if sets:
        vals.append(fid)
        run("UPDATE discord_feeds SET " + ", ".join(sets) + " WHERE id=?", vals)
    return {"ok": True}


@api("/api/discord/feeds/{fid:int}", "DELETE", auth="owner")
async def dc_del_feed(req):
    with tx() as c:
        c.execute("DELETE FROM feed_subs WHERE feed_id=?", (req.p("fid"),))
        c.execute("DELETE FROM discord_feeds WHERE id=?", (req.p("fid"),))
    return {"ok": True}


@api("/api/discord/feeds/{fid:int}/subscribe", "POST", auth="discord")
async def dc_feed_sub(req):
    fid = req.p("fid")
    if not q1("SELECT 1 x FROM discord_feeds WHERE id=?", (fid,)):
        fail(404, "غير موجود")
    want = ids_list((await req.json()).get("tg_channel_ids"), 50)
    mine = {r["id"] for r in q("SELECT id FROM tg_channels WHERE added_by=?", (req.username,))}
    with tx() as c:
        c.execute("DELETE FROM feed_subs WHERE feed_id=? AND username=?", (fid, req.username))
        for tid in want:
            if tid in mine:
                c.execute("INSERT OR IGNORE INTO feed_subs(feed_id, tg_channel_id, username, enabled, created) VALUES(?,?,?,1,?)", (fid, tid, req.username, now()))
    return {"ok": True}
