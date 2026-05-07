# ╔══════════════════════════════════════════════════════════════╗
# ║         VCFIGHTER — Sudo System                              ║
# ║         File: VCFIGHTERS/Untils/sudo.py                      ║
# ╚══════════════════════════════════════════════════════════════╝

import time

from pyrogram import Client
from pyrogram import filters as pyro_filters
from pyrogram.types import Message

import Config
from VCFIGHTERS.logging import LOGGER
from VCFIGHTERS.database.mangodb import (
    add_sudo_user,
    get_sudo_users,
    remove_sudo_user,
)

log = LOGGER("Sudo")


# ─────────────────────────────────────────────
# AUTH HELPERS  (single source of truth)
# ─────────────────────────────────────────────

def is_owner(user_id: int) -> bool:
    """Check if user is the bot owner (from Config.py)."""
    return user_id == int(Config.OWNER_ID)


async def is_sudo(user_id: int) -> bool:
    """Check if user is in sudo list (from MongoDB)."""
    return user_id in await get_sudo_users()


async def is_authorized(user_id: int) -> bool:
    """Owner OR sudo."""
    return is_owner(user_id) or await is_sudo(user_id)


# ─────────────────────────────────────────────
# IMPORT BOT APP
# ─────────────────────────────────────────────

from VCFIGHTERS.core.bot import app  # noqa: E402


# ─────────────────────────────────────────────
# HELPER — resolve user from command
# ─────────────────────────────────────────────

async def _resolve_user(client: Client, message: Message) -> int | None:
    """
    Returns user_id from:
    - Reply to a message          → replied user's id
    - /cmd <user_id>              → int in args
    - /cmd <username>             → resolve via Telegram
    Returns None if not found.
    """
    # Reply to a message
    if message.reply_to_message:
        return message.reply_to_message.from_user.id

    # Argument provided
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        return None

    arg = parts[1].strip()

    # Numeric ID
    if arg.lstrip("-").isdigit():
        return int(arg)

    # Username
    try:
        user = await client.get_users(arg)
        return user.id
    except Exception:
        return None


# ══════════════════════════════════════════════
#  /addsudo
# ══════════════════════════════════════════════

@app.on_message(pyro_filters.command("addsudo") & pyro_filters.private)
async def cmd_addsudo(client: Client, message: Message):
    if not is_owner(message.from_user.id):
        await message.reply("⛔ **𝗢𝘄𝗻𝗲𝗿 𝗢𝗻𝗹𝘆**")
        return

    target_id = await _resolve_user(client, message)
    if not target_id:
        await message.reply(
            "❌ **Usage:**\n"
            "`/addsudo <user_id>` or reply to a message"
        )
        return

    if is_owner(target_id):
        await message.reply("👑 That's you — already the Owner.")
        return

    sudos = await get_sudo_users()
    if target_id in sudos:
        await message.reply(f"ℹ️ User `{target_id}` is already sudo.")
        return

    await add_sudo_user({
        "user_id":  target_id,
        "added_by": message.from_user.id,
        "added_at": int(time.time()),
    })

    log.info(f"Sudo added: {target_id} by {message.from_user.id}")

    try:
        user = await client.get_users(target_id)
        name = f"[{user.first_name}](tg://user?id={target_id})"
    except Exception:
        name = f"`{target_id}`"

    await message.reply(
        f"✅ **{name}** added to sudo list.\n"
        f"👑 𝗔𝗱𝗱𝗲𝗱 𝗯𝘆: {message.from_user.mention}"
    )


# ══════════════════════════════════════════════
#  /delsudo
# ══════════════════════════════════════════════

@app.on_message(pyro_filters.command("delsudo") & pyro_filters.private)
async def cmd_delsudo(client: Client, message: Message):
    if not is_owner(message.from_user.id):
        await message.reply("⛔ **𝗢𝘄𝗻𝗲𝗿 𝗢𝗻𝗹𝘆**")
        return

    target_id = await _resolve_user(client, message)
    if not target_id:
        await message.reply(
            "❌ **Usage:**\n"
            "`/delsudo <user_id>` or reply to a message"
        )
        return

    if is_owner(target_id):
        await message.reply("👑 Can't remove the Owner.")
        return

    sudos = await get_sudo_users()
    if target_id not in sudos:
        await message.reply(f"ℹ️ User `{target_id}` is not in sudo list.")
        return

    await remove_sudo_user(target_id)
    log.info(f"Sudo removed: {target_id} by {message.from_user.id}")

    try:
        user = await client.get_users(target_id)
        name = f"[{user.first_name}](tg://user?id={target_id})"
    except Exception:
        name = f"`{target_id}`"

    await message.reply(f"🗑️ **{name}** removed from sudo list.")


# ══════════════════════════════════════════════
#  /sudolist
# ══════════════════════════════════════════════

@app.on_message(pyro_filters.command("sudolist") & pyro_filters.private)
async def cmd_sudolist(client: Client, message: Message):
    if not is_owner(message.from_user.id):
        await message.reply("⛔ **𝗢𝘄𝗻𝗲𝗿 𝗢𝗻𝗹𝘆**")
        return

    sudos = await get_sudo_users()

    if not sudos:
        await message.reply("👥 **𝗦𝘂𝗱𝗼 𝗟𝗶𝘀𝘁**\n\n_(Empty — no sudo users added yet)_")
        return

    lines = [f"👑 **𝗦𝗨𝗗𝗢 𝗟𝗜𝗦𝗧** ({len(sudos)} users)\n"]
    for i, uid in enumerate(sudos, 1):
        try:
            user = await client.get_users(uid)
            name = user.first_name
            uname = f"@{user.username}" if user.username else "𝗻𝗼 𝘂𝘀𝗲𝗿𝗻𝗮𝗺𝗲"
            lines.append(f"{i}. [{name}](tg://user?id={uid}) | {uname} | `{uid}`")
        except Exception:
            lines.append(f"{i}. `{uid}` | _(𝗰𝗮𝗻𝗻𝗼𝘁 𝗿𝗲𝘀𝗼𝗹𝘃𝗲)_")

    await message.reply(
        "\n".join(lines),
        disable_web_page_preview=True,
  )
  
