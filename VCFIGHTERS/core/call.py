import asyncio
import subprocess
from typing import Optional

from pytgcalls import PyTgCalls
from pytgcalls.types import AudioQuality, MediaStream, VideoQuality

from VCFIGHTERS.database.mangodb import (
    get_ffmpeg_settings,
    get_pytgcalls_settings,
)
from VCFIGHTERS.logging import LOGGER

log = LOGGER("VCCall")


# ══════════════════════════════════════════════════════════════
#  FFMPEG — Pre-process audio file with filters → temp pipe
# ══════════════════════════════════════════════════════════════

async def build_ffmpeg_filter_str() -> str:
    cfg     = await get_ffmpeg_settings()
    filters = []

    vol = cfg.get("volume", 1.0)
    if vol != 1.0:
        filters.append(f"volume={vol}")

    if cfg.get("compressor", False):
        filters.append("acompressor=ratio=20:makeup=24")

    if cfg.get("limiter", False):
        filters.append("alimiter=limit=-0.5dB")

    bass = cfg.get("bass", 0)
    if bass:
        filters.append(f"bass=g={bass}")

    pitch = cfg.get("pitch", "normal")
    if pitch == "demon":
        filters.append("asetrate=44100*0.7,aresample=44100")
    elif pitch == "chipmunk":
        filters.append("asetrate=44100*1.6,aresample=44100")

    if cfg.get("echo", False):
        filters.append("aecho=0.8:0.9:1000:0.3")

    return ",".join(filters) if filters else ""


async def apply_ffmpeg_filters(input_path: str) -> str:
    """
    FFmpeg filters apply karke processed file return karta hai.
    Agar koi filter nahi → original file wapas.
    """
    filter_str = await build_ffmpeg_filter_str()
    if not filter_str:
        return input_path

    out_path = input_path.rsplit(".", 1)[0] + "_filtered.ogg"
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-af", filter_str,
        "-f", "ogg", out_path
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    if proc.returncode == 0:
        log.info(f"✅ FFmpeg processed: {filter_str}")
        return out_path
    else:
        log.warning("⚠️ FFmpeg failed — using original file")
        return input_path


# ══════════════════════════════════════════════════════════════
#  VCCall — PyTgCalls 2.1.1 compatible
# ══════════════════════════════════════════════════════════════

class VCCall:

    def __init__(self):
        self._instances: dict[str, PyTgCalls] = {}
        self._loop_data: dict[int, tuple[str, bool]] = {}
        self._active_ub: dict[int, str] = {}
        log.info("⚙️ VCCall manager initialized")

    async def start(self):
        from VCFIGHTERS.core.userbot import userbot_manager

        sessions = userbot_manager.get_all_sessions()
        clients  = userbot_manager.get_all_clients()

        if not clients:
            log.warning("⚠️ No userbots found — PyTgCalls not started")
            return

        for session, client in zip(sessions, clients):
            await self._init_instance(session, client)

        log.info(f"✅ PyTgCalls started for {len(self._instances)} userbot(s)")

    async def _init_instance(self, session: str, client) -> PyTgCalls:
        if session in self._instances:
            return self._instances[session]

        pytg = PyTgCalls(client)

        # ── py-tgcalls 2.1.1 stream end handler ──
        @pytg.on_update()
        async def _on_stream_end(_, update):
            from pytgcalls.types import StreamEnded
            if not isinstance(update, StreamEnded): return
            chat_id   = update.chat_id
            loop_info = self._loop_data.get(chat_id)

            if not loop_info:
                log.info(f"⏹️ Stream ended (no loop) → chat {chat_id}")
                self._active_ub.pop(chat_id, None)
                return

            file_path, is_video = loop_info
            log.info(f"🔁 Looping again → chat {chat_id}")

            await self._do_play(
                pytg      = pytg,
                chat_id   = chat_id,
                session   = session,
                file_path = file_path,
                is_video  = is_video,
                loop      = True,
            )

        await pytg.start()
        self._instances[session] = pytg
        log.info(f"📡 PyTgCalls ready → ...{session[-10:]}")
        return pytg

    async def add_userbot(self, session: str, client):
        return await self._init_instance(session, client)

    def remove_userbot(self, session: str):
        self._instances.pop(session, None)

    async def _do_play(
        self,
        pytg:      PyTgCalls,
        chat_id:   int,
        session:   str,
        file_path: str,
        is_video:  bool = False,
        loop:      bool = False,
    ) -> bool:

        # FFmpeg filters apply karo
        processed = await apply_ffmpeg_filters(file_path)

        pytg_cfg      = await get_pytgcalls_settings()
        quality_str   = pytg_cfg.get("quality", "medium")
        audio_quality = AudioQuality.STUDIO

        try:
            if is_video:
                stream = MediaStream(
                    audio_path       = processed,
                    video_path       = "VCFIGHTERS/Assists/screen-20260507-153325.mp4",
                    audio_parameters = audio_quality,
                    video_parameters = VideoQuality.HD_720p,
                )
            else:
                stream = MediaStream(
                    media_path       = processed,
                    audio_parameters = audio_quality,
                )

            await pytg.play(chat_id, stream)
            self._active_ub[chat_id] = session

            mode_str = "🔁 loop" if loop else "▶️ once"
            log.info(f"{mode_str} | chat={chat_id} | file={processed}")
            return True

        except Exception as e:
            log.error(f"❌ Play failed → chat {chat_id}: {e}")
            return False

    async def play(self, chat_id: int, file_path: str,
                   session: Optional[str] = None, is_video: bool = False) -> bool:
        pytg, ses = self._resolve(session)
        if not pytg:
            return False
        self._loop_data.pop(chat_id, None)
        return await self._do_play(pytg, chat_id, ses, file_path, is_video, False)

    async def play_loop(self, chat_id: int, file_path: str,
                        session: Optional[str] = None, is_video: bool = False) -> bool:
        pytg, ses = self._resolve(session)
        if not pytg:
            return False
        self._loop_data[chat_id] = (file_path, is_video)
        return await self._do_play(pytg, chat_id, ses, file_path, is_video, True)

    async def replace_audio(self, chat_id: int, new_file: str,
                            session: Optional[str] = None) -> bool:
        log.info(f"🔄 Replacing audio → chat {chat_id}")
        self._loop_data.pop(chat_id, None)
        return await self.play_loop(chat_id, new_file, session)

    async def stop(self, chat_id: int, leave_vc: bool = True):
        self._loop_data.pop(chat_id, None)
        if leave_vc:
            session = self._active_ub.pop(chat_id, None)
            pytg    = self._get_instance(session)
            if pytg:
                try:
                    await pytg.leave_call(chat_id)
                    log.info(f"⏹️ Left VC → chat {chat_id}")
                except Exception as e:
                    log.warning(f"⚠️ leave_call error: {e}")
        else:
            self._active_ub.pop(chat_id, None)

    async def stop_all(self):
        for chat_id in list(self._active_ub.keys()):
            await self.stop(chat_id)
        log.info("🛑 All VC streams stopped")

    async def apply_filters_to_all(self) -> int:
        updated = 0
        for chat_id, (file_path, is_video) in list(self._loop_data.items()):
            session = self._active_ub.get(chat_id)
            if await self.play_loop(chat_id, file_path, session, is_video):
                updated += 1
        log.info(f"✅ Filters applied to {updated} stream(s)")
        return updated

    def status(self) -> dict:
        return {
            "pytgcalls_instances": len(self._instances),
            "active_streams":      len(self._active_ub),
            "loop_active_chats":   list(self._loop_data.keys()),
        }

    def _resolve(self, session: Optional[str]) -> tuple[Optional[PyTgCalls], str]:
        if not self._instances:
            log.error("❌ No PyTgCalls instances available")
            return None, ""
        if session and session in self._instances:
            return self._instances[session], session
        ses  = next(iter(self._instances))
        return self._instances[ses], ses

    def _get_instance(self, session: Optional[str]) -> Optional[PyTgCalls]:
        if not session:
            return None
        return self._instances.get(session)


vc = VCCall()
