import asyncio
import importlib
import os

from pyrogram import idle

import Config
from VCFIGHTERS.logging import LOGGER
from VCFIGHTERS.database.mangodb import (
    init_db,
    get_all_sessions,
    get_sudo_users,
)

# ─── Global Sets ───────────────────────────────────────────
SUDO_USERS: set = set()

# ─── Auto Module Loader ─────────────────────────────────────
def load_modules():
    """FIGHTERS/ folder ke andar saare .py files auto-import karega"""
    fighters_path = os.path.join(
        os.path.dirname(__file__), "FIGHTERS"
    )
    modules = []
    for filename in os.listdir(fighters_path):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = filename[:-3]  # .py hata do
            modules.append(module_name)

    loaded = []
    failed = []
    for module in modules:
        try:
            importlib.import_module(f"VCFIGHTERS.FIGHTERS.{module}")
            loaded.append(module)
        except Exception as e:
            LOGGER("Loader").error(f"❌ Failed to load {module}: {e}")
            failed.append(module)

    LOGGER("Loader").info(
        f"✅ Loaded: {len(loaded)} modules | "
        f"❌ Failed: {len(failed)} modules"
    )
    if failed:
        LOGGER("Loader").warning(f"Failed modules: {failed}")


# ─── Sudo Loader ────────────────────────────────────────────
async def load_sudo():
    """MongoDB se sudo users load karo RAM mein"""
    try:
        sudo_list = await get_sudo_users()
        for user_id in sudo_list:
            SUDO_USERS.add(user_id)
        LOGGER("Sudo").info(f"✅ {len(SUDO_USERS)} Sudo users loaded")
    except Exception as e:
        LOGGER("Sudo").error(f"❌ Sudo load failed: {e}")


# ─── Userbot Loader ─────────────────────────────────────────
async def load_userbots():
    """MongoDB se saare string sessions load karke userbots start karo"""
    from VCFIGHTERS.core.userbot import start_all_userbots
    try:
        sessions = await get_all_sessions()
        if not sessions:
            LOGGER("Userbots").warning(
                "⚠️ No userbots found in DB. "
                "Use /config → USERBOTs to add sessions."
            )
            return

        await start_all_userbots(sessions)
        LOGGER("Userbots").info(f"✅ {len(sessions)} Userbot(s) started")
    except Exception as e:
        LOGGER("Userbots").error(f"❌ Userbot load failed: {e}")


# ─── Validation ─────────────────────────────────────────────
def validate_config():
    """Config.py mein zaroori values check karo"""
    required = {
        "API_ID": getattr(Config, "API_ID", None),
        "API_HASH": getattr(Config, "API_HASH", None),
        "BOT_TOKEN": getattr(Config, "BOT_TOKEN", None),
        "MONGO_URI": getattr(Config, "MONGO_URI", None),
        "OWNER_ID": getattr(Config, "OWNER_ID", None),
    }

    missing = [key for key, val in required.items() if not val]

    if missing:
        LOGGER("Config").error(
            f"❌ Missing required config values: {missing}\n"
            f"Please fill Config.py properly."
        )
        exit(1)

    LOGGER("Config").info("✅ Config validation passed")


# ─── Main Init ──────────────────────────────────────────────
async def init():
    # 1. Config check
    validate_config()

    # 2. MongoDB connect
    LOGGER("DB").info("🔌 Connecting to MongoDB...")
    await init_db()
    LOGGER("DB").info("✅ MongoDB connected")

    # 3. Sudo users load
    await load_sudo()

    # 4. Auto module loader
    LOGGER("Loader").info("📦 Loading all FIGHTERS modules...")
    load_modules()

    # 5. Main bot start
    from VCFIGHTERS.core.bot import app
    LOGGER("Bot").info("🤖 Starting main bot...")
    await app.start()
    LOGGER("Bot").info("✅ Main bot started")

    # 6. Userbots start
    LOGGER("Userbots").info("👥 Starting userbots from DB...")
    await load_userbots()

    # 7. PyTgCalls start
    LOGGER("PyTgCalls").info("📡 Starting PyTgCalls...")
    from VCFIGHTERS.core.call import vc
    await vc.start()
    LOGGER("PyTgCalls").info("✅ PyTgCalls ready")

    # 8. Startup banner
    LOGGER("VCFIGHTER").info(
        "\n╔══════════════════════════════════╗"
        "\n║  ⚔️  VCFIGHTER IS NOW ACTIVE  ⚔️  ║"
        "\n║     🔥 Ready to Destroy VCs 🔥    ║"
        "\n╚══════════════════════════════════╝"
    )

    # 9. Idle — bot chalta rahe
    await idle()

    # 10. Graceful shutdown
    LOGGER("VCFIGHTER").info("🛑 Shutting down VCFIGHTER...")
    await app.stop()
    LOGGER("VCFIGHTER").info("✅ Bot stopped cleanly")


# ─── Entry Point ────────────────────────────────────────────
if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(init())
