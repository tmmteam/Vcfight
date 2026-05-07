import asyncio
import importlib
import os
import glob
from pyrogram import idle
import Config
from VCFIGHTERS.logging import LOGGER
from VCFIGHTERS.database.mangodb import init_db, get_all_sessions

log = LOGGER("VCFIGHTER")

def validate_config():
    required = ["API_ID", "API_HASH", "BOT_TOKEN", "MONGO_URI", "OWNER_ID"]
    missing = [k for k in required if getattr(Config, k, None) is None]
    if missing:
        LOGGER("Config").error(f"Missing config values: {missing}")
        exit(1)
    LOGGER("Config").info("Config validation passed")

def load_handlers():
    LOGGER("Loader").info("Injecting Handlers into Bot...")
    # Seedha FIGHTERS folder ki saari files uthayega aur app mein jod dega
    for file in glob.glob("VCFIGHTERS/FIGHTERS/*.py"):
        name = os.path.basename(file)[:-3]
        if name != "__init__":
            try:
                importlib.import_module(f"VCFIGHTERS.FIGHTERS.{name}")
                LOGGER("Loader").info(f"✅ Handler Active: {name}")
            except Exception as e:
                LOGGER("Loader").error(f"❌ Failed to load {name}: {e}")

async def init():
    validate_config()
    LOGGER("DB").info("Connecting to MongoDB...")
    await init_db()
    
    from VCFIGHTERS.core.bot import app
    
    # ──> MAGIC HAPPENS HERE: Saare commands app mein chipak jayenge! <──
    load_handlers()
    
    LOGGER("Bot").info("Starting bot...")
    await app.start()
    LOGGER("Bot").info("Bot started successfully")
    
    LOGGER("Userbots").info("Starting userbots...")
    from VCFIGHTERS.core.userbot import userbot_manager
    try:
        sessions = await get_all_sessions()
        if sessions:
            await userbot_manager.start_all(sessions)
            LOGGER("Userbots").info(f"{len(sessions)} userbot(s) started")
        else:
            LOGGER("Userbots").warning("No userbots in DB.")
    except Exception as e:
        LOGGER("Userbots").error(f"Userbot error: {e}")
        
    LOGGER("PyTgCalls").info("Starting PyTgCalls...")
    from VCFIGHTERS.core.call import vc
    await vc.start()
    
    log.info("\n⚔️ VCFIGHTER IS NOW ACTIVE - Ready to Destroy VCs ⚔️\n")
    
    await idle()
    
    log.info("Shutting down...")
    try:
        await userbot_manager.stop_all()
        await vc.stop_all()
    except Exception: pass
    await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init())
    
