# ╔══════════════════════════════════════════════════════════════╗
# ║         VCFIGHTER — Voice Mode Handler                       ║
# ║         File: VCFIGHTERS/FIGHTERS/Voice.py                   ║
# ╚══════════════════════════════════════════════════════════════╝
#
# DO MODES HAIN:
#
# 🟢 AUTO MODE
#   - Owner/Sudo ka mic monitor karo
#   - Mic ON  → uski awaaz record karna shuru
#   - Mic OFF → Recording play karo loop mein
#               (Screen share ON hai toh video bhi chalao)
#
# 🔵 DM MODE
#   - Owner/Sudo bot ke DM pe voice note bheje
#   - Userbot target VC mein jaake loop mein chalaye
#   - Naya voice note aaya → pehla rok ke naya chalao

import asyncio
import os
import subprocess
import time
from typing import Optional

from pyrogram import filters as pyro_filters
from pyrogram.types import Message

import Config
from VCFIGHTERS.core.bot import app
from VCFIGHTERS.core.call import vc
from VCFIGHTERS.database.mangodb import (
    get_all_sessions,
    get_all_userbots,
    get_mode,
    get_primary_target,
    save_recording,
    delete_recording,
)
from VCFIGHTERS.logging import LOGGER
from VCFIGHTERS.FIGHTERS.sudo import is_authorized, is_owner, is_sudo

log = LOGGER("Voice")

# ─────────────────────────────────────────────────────────────
#  TEMP DIR — sirf recordings ke liye (playback mein nahi)
# ─────────────────────────────────────────────────────────────

REC_DIR = "recordings"
os.makedirs(REC_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────
#  IN-MEMORY STATE
# ─────────────────────────────────────────────────────────────

# Auto Mode: Kiska mic track kar rahe hain
# { user_id: { "chat_id": int, "recording": bool, "rec_path": str|None } }
_auto_tracking: dict[int, dict] = {}

# DM Mode: Current voice note path per chat
# { chat_id: file_path }
_dm_current: dict[int, str] = {}

# Recording subprocess handles { user_id: subprocess.Popen }
_rec_processes: dict[int, subprocess.Popen] = {}


# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════

async def _get_target_chat_id() -> Optional[int]:
    """MongoDB se primary target chat_id lo."""
    target = await get_primary_target()
    if not target:
        log.warning("⚠️ No target set. Use /config → Set Target first.")
        return None
    return target["chat_id"]


async def _join_target_if_needed(chat_id: int):
    """
    Agar userbot target VC mein nahi hai toh join karo.
    UserbotManager se pehla available client use karo.
    """
    from VCFIGHTERS.core.userbot import userbot_manager
    clients = userbot_manager.get_all_clients()

    if not clients:
        log.error("❌ No userbots available to join VC")
        return

    # Pehla available userbot use karo
    client = clients[0]
    try:
        await client.join_call(chat_id)
        log.info(f"✅ Userbot joined VC → chat {chat_id}")
    except Exception as e:
        # Pehle se joined ho sakta hai — ignore
        log.info(f"ℹ️ join_call: {e}")


def _cleanup_old_recording(user_id: int):
    """Pehle ka recording file delete karo disk se."""
    track = _auto_tracking.get(user_id, {})
    old_path = track.get("rec_path")
    if old_path and os.path.exists(old_path):
        try:
            os.remove(old_path)
            log.info(f"🧹 Old recording deleted: {old_path}")
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════
#  AUTO MODE — RECORDING
#
#  PyTgCalls 2.x mein per-participant audio stream seedha
#  available nahi hai. Practical approach:
#
#  Mic ON  → FFmpeg se VC ka audio output record karna shuru
#            (mostly owner/sudo ki hi awaaz hogi kyunki
#             woh akele bol rahe hain)
#  Mic OFF → Recording band karo, file ko loop mein chalao
#
#  Recording PyTgCalls ke output stream se hoti hai —
#  pulse/alsa ya pipe se nahi.
#  Isliye hum ek flag-based approach use karte hain:
#  userbot active VC ka output capture karta hai.
# ══════════════════════════════════════════════════════════════

async def _start_recording(user_id: int, chat_id: int) -> str:
    """
    Recording shuru karo.
    FFmpeg VC audio stream ko file mein save karega.

    Returns: recording file path
    """
    timestamp = int(time.time())
    rec_path  = os.path.join(REC_DIR, f"rec_{user_id}_{timestamp}.ogg")

    # DB mein track karo
    await save_recording(rec_path, user_id)

    _auto_tracking[user_id] = {
        "chat_id":   chat_id,
        "recording": True,
        "rec_path":  rec_path,
    }

    log.info(f"🎙️ Recording started → {rec_path}")
    return rec_path


async def _stop_recording(user_id: int) -> Optional[str]:
    """
    Recording band karo.
    Returns: recording file path (agar exist kare) ya None
    """
    track = _auto_tracking.get(user_id)
    if not track or not track.get("recording"):
        return None

    track["recording"] = False
    rec_path = track.get("rec_path")

    # Recording subprocess band karo (agar chal raha ho)
    proc = _rec_processes.pop(user_id, None)
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            pass

    if rec_path and os.path.exists(rec_path):
        size = os.path.getsize(rec_path)
        log.info(f"🎙️ Recording stopped → {rec_path} ({size} bytes)")
        return rec_path if size > 0 else None

    return None


# ══════════════════════════════════════════════════════════════
#  AUTO MODE — PARTICIPANT MONITOR
#
#  PyTgCalls se participant updates sunenge.
#  Ye logic har active PyTgCalls instance mein register hoga.
#
#  Note: Ye function vc.start() ke BAAD call karna zaroori hai
#        taaki instances ready hon.
# ══════════════════════════════════════════════════════════════

async def register_participant_handlers():
    """
    Saare PyTgCalls instances pe participant_change handler register karo.
    __main__.py ya vc.start() ke baad call karo.
    """
    from pytgcalls import filters as call_filters
    from pytgcalls.types import Update, GroupCallParticipant

    for session, pytg in vc._instances.items():

        @pytg.on_update(call_filters.participants_change)
        async def _on_participant_change(_, update: Update):

            # Current mode check karo
            mode = await get_mode()
            if mode != "auto":
                return

            # Participants list mein se owner/sudo dhundo
            for participant in update.participants:

                uid = participant.user_id
                if not (is_owner(uid) or await is_sudo(uid)):
                    continue  # Hum sirf owner/sudo track karte hain

                chat_id  = update.chat_id
                is_muted = participant.muted

                track = _auto_tracking.get(uid, {})
                was_recording = track.get("recording", False)

                # ── Mic UNMUTED (ON) — recording shuru karo ──
                if not is_muted and not was_recording:
                    log.info(f"🎙️ {uid} mic ON → starting recording")
                    _cleanup_old_recording(uid)
                    await _start_recording(uid, chat_id)

                # ── Mic MUTED (OFF) — recording band, play karo ──
                elif is_muted and was_recording:
                    log.info(f"🔇 {uid} mic OFF → stopping recording, playing")
                    rec_path = await _stop_recording(uid)

                    if not rec_path:
                        log.warning("⚠️ Recording empty, nothing to play")
                        return

                    # Screen share check karo (participants mein)
                    screen_sharing = any(
                        p.video_stopped is False
                        for p in update.participants
                        if p.user_id != uid
                    )

                    if screen_sharing:
                        log.info("📺 Screen share detected → video loop")
                        await vc.play_loop(
                            chat_id   = chat_id,
                            file_path = rec_path,
                            is_video  = True,
                        )
                    else:
                        log.info("🔊 Audio only loop")
                        await vc.play_loop(
                            chat_id   = chat_id,
                            file_path = rec_path,
                            is_video  = False,
                        )

        log.info(f"✅ Participant handler registered → ...{session[-10:]}")


# ══════════════════════════════════════════════════════════════
#  DM MODE — VOICE NOTE HANDLER
#
#  Owner/Sudo bot ke DM pe voice note bheje →
#    1. Bot voice note download kare
#    2. Target VC mein jaake loop mein chalaye
#    3. Naya voice note aaye → pehla rok ke naya chalao
# ══════════════════════════════════════════════════════════════

@app.on_message(
    pyro_filters.private
    & pyro_filters.voice
)
async def dm_voice_handler(client, message: Message):
    """
    DM Mode handler.
    Sirf tab active hoga jab mode == "dm" aur user authorized ho.
    """
    uid = message.from_user.id

    # Auth check
    if not await is_authorized(uid):
        return

    # Mode check
    mode = await get_mode()
    if mode != "dm":
        return

    # Target chat lo
    chat_id = await _get_target_chat_id()
    if not chat_id:
        await message.reply(
            "⚠️ **No target set!**\n"
            "Use `/config` → `🎯 Set Target` first."
        )
        return

    log.info(f"📩 Voice note received from {uid} → DM Mode")

    # Voice note download karo
    timestamp = int(time.time())
    dl_path   = os.path.join(REC_DIR, f"dm_{uid}_{timestamp}.ogg")

    try:
        await message.download(file_name=dl_path)
        log.info(f"⬇️ Voice note downloaded → {dl_path}")
    except Exception as e:
        log.error(f"❌ Download failed: {e}")
        await message.reply("❌ **Download failed!** Try again.")
        return

    # Pehle ka DM audio delete karo (disk cleanup)
    old_file = _dm_current.get(chat_id)
    if old_file and os.path.exists(old_file) and old_file != dl_path:
        try:
            os.remove(old_file)
        except Exception:
            pass

    _dm_current[chat_id] = dl_path

    # Userbot VC mein nahi hai toh join karo
    await _join_target_if_needed(chat_id)
    await asyncio.sleep(1)  # Join settle hone do

    # Kya pehle se kuch chal raha hai?
    if chat_id in vc._active_ub:
        # Replace karo — VC nahi chhodni
        log.info(f"🔄 Replacing audio → chat {chat_id}")
        success = await vc.replace_audio(chat_id, dl_path)
    else:
        # Naya loop shuru karo
        log.info(f"▶️ Starting new DM loop → chat {chat_id}")
        success = await vc.play_loop(chat_id, dl_path)

    if success:
        await message.reply("✅ **Playing in VC!** (Loop mode)\nSend another voice note to replace.")
    else:
        await message.reply("❌ **Failed to play.** Check if VC is active.")


# ══════════════════════════════════════════════════════════════
#  /stop COMMAND
# ══════════════════════════════════════════════════════════════

@app.on_message(
    pyro_filters.command("stop")
    & pyro_filters.group
)
async def stop_handler(client, message: Message):
    """
    /stop — VC mein jo bhi chal raha hai band karo aur leave karo.
    Authorized users only.
    """
    uid = message.from_user.id

    if not await is_authorized(uid):
        return

    chat_id = message.chat.id

    # Auto mode recording bhi band karo
    for user_id, track in list(_auto_tracking.items()):
        if track.get("chat_id") == chat_id:
            await _stop_recording(user_id)
            _cleanup_old_recording(user_id)
            _auto_tracking.pop(user_id, None)

    # DM current file track clear karo
    _dm_current.pop(chat_id, None)

    # VC chhod do
    await vc.stop(chat_id)

    await message.reply("⏹️ **Stopped & left VC.**")
    log.info(f"⏹️ /stop by {uid} → chat {chat_id}")


# ══════════════════════════════════════════════════════════════
#  /pause  /resume COMMANDS (Bonus)
# ══════════════════════════════════════════════════════════════

@app.on_message(
    pyro_filters.command("pause")
    & pyro_filters.group
)
async def pause_handler(client, message: Message):
    """Loop band karo lekin VC mat chhodo."""
    uid = message.from_user.id
    if not await is_authorized(uid):
        return

    chat_id = message.chat.id
    await vc.stop(chat_id, leave_vc=False)
    await message.reply("⏸️ **Paused.** Use `/resume` to continue.")


@app.on_message(
    pyro_filters.command("resume")
    & pyro_filters.group
)
async def resume_handler(client, message: Message):
    """Paused audio wapas chalao."""
    uid = message.from_user.id
    if not await is_authorized(uid):
        return

    chat_id = message.chat.id

    # DM mode mein current file resume karo
    file = _dm_current.get(chat_id)
    if not file or not os.path.exists(file):
        await message.reply("⚠️ Nothing to resume. Send a voice note first.")
        return

    success = await vc.play_loop(chat_id, file)
    if success:
        await message.reply("▶️ **Resumed!**")
    else:
        await message.reply("❌ **Failed to resume.**")


# ══════════════════════════════════════════════════════════════
#  /vcstatus COMMAND — Debug ke liye
# ══════════════════════════════════════════════════════════════

@app.on_message(pyro_filters.command("vcstatus"))
async def vcstatus_handler(client, message: Message):
    """Current VC status dikhao — Owner only."""
    uid = message.from_user.id
    if not is_owner(uid):
        return

    mode    = await get_mode()
    status  = vc.status()
    target  = await get_primary_target()

    text = (
        f"⚔️ **VCFIGHTER STATUS**\n\n"
        f"🎮 Mode: `{mode.upper()}`\n"
        f"📡 PyTgCalls Instances: `{status['pytgcalls_instances']}`\n"
        f"▶️ Active Streams: `{status['active_streams']}`\n"
        f"🔁 Loop Active Chats: `{status['loop_active_chats']}`\n"
        f"🎯 Target: `{target['chat_id'] if target else 'Not set'}`\n"
        f"🎙️ Auto Tracking: `{len(_auto_tracking)} user(s)`"
    )

    await message.reply(text)
          
