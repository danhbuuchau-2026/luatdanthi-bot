"""
Minimax TTS — Tạo audio giọng luật sư (MP3)
API: https://api.minimaxi.chat/v1/t2a_v2
"""
import os
import logging
import httpx

logger = logging.getLogger(__name__)

MINIMAX_API_KEY  = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_GROUP_ID = os.getenv("MINIMAX_GROUP_ID", "")

# Voice IDs Minimax (giọng nữ chuyên nghiệp tiếng Việt)
VOICE_ID = os.getenv("MINIMAX_VOICE_ID", "Vietnamese_WomanSpokenA")


async def generate_tts(text: str, voice_id: str | None = None) -> bytes | None:
    """
    Tạo file MP3 từ text dùng Minimax TTS.
    Trả về bytes MP3 hoặc None nếu lỗi.
    """
    if not MINIMAX_API_KEY:
        logger.error("Thiếu MINIMAX_API_KEY")
        return None

    vid = voice_id or VOICE_ID
    url = f"https://api.minimaxi.chat/v1/t2a_v2?GroupId={MINIMAX_GROUP_ID}"

    payload = {
        "model": "speech-01-turbo",
        "text": text,
        "stream": False,
        "voice_setting": {
            "voice_id": vid,
            "speed": 1.0,
            "vol": 1.0,
            "pitch": 0,
        },
        "audio_setting": {
            "sample_rate": 24000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
    }

    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, json=payload, headers=headers)

        if r.status_code != 200:
            logger.error("Minimax TTS error %s: %s", r.status_code, r.text[:300])
            return None

        data = r.json()

        # Minimax trả về audio dưới dạng hex string
        audio_hex = data.get("data", {}).get("audio", "")
        if audio_hex:
            return bytes.fromhex(audio_hex)

        logger.error("Minimax TTS: không có audio trong response: %s", str(data)[:300])
        return None

    except Exception as e:
        logger.error("TTS exception: %s", e)
        return None


async def send_audio_telegram(token: str, chat_id, audio_bytes: bytes, filename: str, caption: str = ""):
    """Gửi file MP3 lên Telegram"""
    import httpx
    url = f"https://api.telegram.org/bot{token}/sendAudio"
    files = {"audio": (filename, audio_bytes, "audio/mpeg")}
    data  = {"chat_id": chat_id, "caption": caption[:1000], "parse_mode": "HTML"}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, data=data, files=files)
    return r.json()
