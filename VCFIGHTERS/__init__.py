from VCFIGHTERS.logging import LOGGER

LOGGER("VCFIGHTER").info(
    "\n╔═════════════════════════╗"
    "\n║   🔥 VCFIGHTER LOADING  ║"
    "\n╚═════════════════════════╝"
)

from VCFIGHTERS.core.bot import VCBot          # Main Pyrogram bot client
from VCFIGHTERS.core.userbot import UserbotManager  # Userbot manager
from VCFIGHTERS.core.call import VCCall        # PyTgCalls handler

# DB initialize
from VCFIGHTERS.database.mangodb import init_db

# Bot aur userbot instances
app = VCBot()
userbot_manager = UserbotManager()
vc = VCCall()

__version__ = "1.0.0"
