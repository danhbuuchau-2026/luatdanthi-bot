"""
VIDEO CONTENT: taobai + /r2 + /dang
Flow:
  taobai lyhonfb  → Claude viết kịch bản → Minimax TTS → gửi MP3 Telegram → ghi Sheets
  /r2 <id> <url>  → lưu link video R2 → đổi status "ready"
  /dang <id>      → post video lên Facebook → đổi status "posted"
"""
import os
import re
import asyncio
import logging
import time
from datetime import datetime
import httpx

from services.tts import generate_tts, send_audio_telegram
from services.sheets import (
    append_video_content, get_video_content,
    update_video_r2, update_video_posted,
)

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
FB_PAGE_ID        = os.getenv("FB_PAGE_ID", "")
FB_ACCESS_TOKEN   = os.getenv("FB_ACCESS_TOKEN", "")

# ── Parse taobai command ──────────────────────────────────────────────────────
TOPIC_MAP = {
    "lyhon":    "ly_hon",
    "datdai":   "dat_dai",
    "hinhsu":   "hinh_su",
    "hopd":     "hop_dong",
    "laodong":  "lao_dong",
    "tais":     "tai_san",
    "nuoicon":  "nuoi_con",
    "doanhnghiep": "doanh_nghiep",
}
TOPIC_LABEL = {
    "ly_hon":       "Ly Hôn",
    "dat_dai":      "Đất Đai",
    "hinh_su":      "Hình Sự",
    "hop_dong":     "Hợp Đồng",
    "lao_dong":     "Lao Động",
    "tai_san":      "Tài Sản",
    "nuoi_con":     "Nuôi Con",
    "doanh_nghiep": "Doanh Nghiệp",
}
PLATFORM_MAP = {"fb": "facebook", "tk": "tiktok", "ytb": "youtube"}
PLATFORM_LABEL = {"facebook": "Facebook", "tiktok": "TikTok", "youtube": "YouTube"}

def parse_taobai(text: str) -> dict | None:
    """Parse: taobai lyhonfb / taobai datdaitk / taobai hinhsuytb"""
    t = text.strip().lower()
    if not (t.startswith("taobai ") or t.startswith("/taobai ")):
        return None

    parts = t.split()
    if len(parts) < 2:
        return None

    combo = parts[1]  # e.g. "lyhonfb", "datdaitk"

    # Tách platform suffix
    platform = "facebook"
    topic_raw = combo
    for sfx, plat in PLATFORM_MAP.items():
        if combo.endswith(sfx):
            platform  = plat
            topic_raw = combo[: -len(sfx)]
            break

    # Map topic
    topic = None
    for k, v in TOPIC_MAP.items():
        if topic_raw.startswith(k):
            topic = v
            break
    if not topic:
        # Fallback fuzzy
        if "dat" in topic_raw:  topic = "dat_dai"
        elif "hinh" in topic_raw: topic = "hinh_su"
        else: topic = "ly_hon"

    return {"topic": topic, "platform": platform}


# ── Claude API ────────────────────────────────────────────────────────────────
async def call_claude(system: str, user: str, max_tokens: int = 1500) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
        )
    data = r.json()
    if not data.get("content"):
        raise ValueError(f"Claude error: {data}")
    return data["content"][0]["text"].strip()


# ── Write video content ───────────────────────────────────────────────────────
DURATION_MAP = {"facebook": "45-60 giây", "tiktok": "30-45 giây", "youtube": "60-90 giây"}

async def write_video_content(topic: str, platform: str) -> dict:
    label   = TOPIC_LABEL.get(topic, topic)
    plat_lbl = PLATFORM_LABEL.get(platform, platform)
    duration = DURATION_MAP.get(platform, "45-60 giây")

    cta_map = {
        "ly_hon":   "Nhắn TƯ VẤN để được Luật Danh Thị hỗ trợ ngay.",
        "dat_dai":  "Nhắn ĐẤT ĐAI để bảo vệ quyền lợi của bạn.",
        "hinh_su":  "Gọi ngay HÌNH SỰ để có luật sư đồng hành.",
        "hop_dong": "Nhắn HỢP ĐỒNG để được tư vấn miễn phí.",
        "lao_dong": "Nhắn LAO ĐỘNG để được hỗ trợ pháp lý.",
        "tai_san":  "Nhắn TÀI SẢN để bảo vệ quyền lợi của bạn.",
        "nuoi_con": "Nhắn NUÔI CON để được tư vấn ngay.",
        "doanh_nghiep": "Nhắn DOANH NGHIỆP để được tư vấn pháp lý.",
    }
    hashtag_map = {
        "ly_hon":   "#LuatDanhThi #LyHon #TuVanLyHon #LuatSuLyHon",
        "dat_dai":  "#LuatDanhThi #DatDai #TraanhChap #LuatSuDatDai",
        "hinh_su":  "#LuatDanhThi #HinhSu #BaoChua #LuatSuHinhSu",
        "hop_dong": "#LuatDanhThi #HopDong #TuVanPhapLy",
        "lao_dong": "#LuatDanhThi #LaoDong #BaoVeNguoiLaoDong",
        "tai_san":  "#LuatDanhThi #TaiSan #PhapLyTaiSan",
        "nuoi_con": "#LuatDanhThi #NuoiCon #QuyenNuoiCon",
        "doanh_nghiep": "#LuatDanhThi #DoanhNghiep #TuVanDN",
    }

    system = f"""Bạn là Content Creator của Công ty Luật Danh Thị.
Viết nội dung video {plat_lbl} về chủ đề {label}.

YÊU CẦU KỊCH BẢN ({duration}):
- Giọng kể chuyện tự nhiên, như đang nói chuyện
- Câu ngắn, dễ phát âm, không đọc khó
- Mở đầu bằng câu hook gây chú ý ngay 3 giây đầu
- Kể tình huống thực tế, đồng cảm với người xem
- Không cam kết chắc thắng
- Kết thúc bằng CTA: {cta_map.get(topic, 'Liên hệ Luật Danh Thị ngay.')}

OUTPUT FORMAT — CHỈ 4 PHẦN NÀY:
TITLE: (tiêu đề video, max 60 ký tự)
CAPTION: (mô tả đăng kèm video, 150-200 ký tự + hashtag)
HASHTAGS: {hashtag_map.get(topic, '#LuatDanhThi')}
SCRIPT_START
(kịch bản đọc TTS, {duration}, không có dấu chấm xuống dòng liên tục, tự nhiên)
SCRIPT_END"""

    raw = await call_claude(system, f"Viết video {plat_lbl} về {label}. Chọn 1 tình huống thực tế hấp dẫn.")

    def get(key):
        m = re.search(rf"{key}[\s]*[:\s][\s]*([^\n\r]+)", raw, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    m_script = re.search(r"SCRIPT_START\s*(.*?)\s*SCRIPT_END", raw, re.DOTALL)
    script = m_script.group(1).strip() if m_script else raw

    title   = get("TITLE")
    caption = get("CAPTION")
    tags    = get("HASHTAGS")

    # Nếu caption chưa có hashtag, thêm vào
    full_caption = caption + ("\n" + tags if tags and tags not in caption else "")

    return {
        "title":   title or f"Luật Danh Thị — {label}",
        "caption": full_caption,
        "script":  script,
    }


# ── Generate unique ID ────────────────────────────────────────────────────────
def make_video_id(topic: str, platform: str) -> str:
    prefix_map = {
        "ly_hon": "LH", "dat_dai": "DD", "hinh_su": "HS",
        "hop_dong": "HD", "lao_dong": "LD", "tai_san": "TS",
        "nuoi_con": "NC", "doanh_nghiep": "DN",
    }
    plat_map = {"facebook": "FB", "tiktok": "TK", "youtube": "YTB"}
    p   = prefix_map.get(topic, "LDT")
    plt = plat_map.get(platform, "FB")
    ts  = str(int(time.time()))[-6:]
    return f"{p}{plt}{ts}"


# ── Telegram helpers ──────────────────────────────────────────────────────────
async def tg_send(token: str, chat_id, text: str, parse_mode="HTML"):
    async with httpx.AsyncClient(timeout=20) as c:
        await c.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
        )


# ── MAIN: taobai handler ──────────────────────────────────────────────────────
async def run_taobai(text: str, chat_id: str, bot_token: str):
    parsed = parse_taobai(text)
    if not parsed:
        return

    topic    = parsed["topic"]
    platform = parsed["platform"]
    label    = TOPIC_LABEL.get(topic, topic)
    plat_lbl = PLATFORM_LABEL.get(platform, platform)
    vid_id   = make_video_id(topic, platform)

    await tg_send(bot_token, chat_id,
        f"⏳ <b>Đang tạo nội dung {plat_lbl} — {label}</b>\n\n"
        f"🆔 ID: <code>{vid_id}</code>\n"
        "✍️ Claude đang viết kịch bản...\n🎙️ Sau đó tạo audio (~60s)")

    try:
        # 1. Viết nội dung
        content = await write_video_content(topic, platform)

        # 2. Gửi text preview
        preview = (
            f"✅ <b>Đã viết xong!</b>\n\n"
            f"🆔 <code>{vid_id}</code>\n"
            f"📌 <b>{content['title']}</b>\n"
            f"📱 {plat_lbl}\n\n"
            f"<b>Caption:</b>\n{content['caption'][:400]}\n\n"
            f"<b>Kịch bản ({len(content['script'])} ký tự):</b>\n"
            f"{content['script'][:300]}...\n\n"
            "🎙️ Đang tạo audio MP3..."
        )
        await tg_send(bot_token, chat_id, preview)

        # 3. TTS audio
        audio_bytes = await generate_tts(content["script"])

        if audio_bytes:
            filename = f"{vid_id}.mp3"
            caption  = f"🎙️ Audio: {content['title']}\n🆔 {vid_id}"
            await send_audio_telegram(bot_token, chat_id, audio_bytes, filename, caption)

            await tg_send(bot_token, chat_id,
                f"✅ <b>Hoàn thành!</b>\n\n"
                f"📋 <b>Bước tiếp theo:</b>\n"
                "1️⃣ Tải MP3 → dùng trong <b>HeyGen</b> tạo video\n"
                "2️⃣ Upload video lên R2\n"
                f"3️⃣ Nhắn: <code>/r2 {vid_id} https://r2_link.mp4</code>\n"
                f"4️⃣ Nhắn: <code>/dang {vid_id}</code> để đăng")
        else:
            # TTS thất bại → vẫn gửi kịch bản
            await tg_send(bot_token, chat_id,
                f"⚠️ Tạo audio lỗi, nhưng kịch bản đã xong.\n\n"
                f"<b>Kịch bản đầy đủ:</b>\n{content['script'][:2000]}\n\n"
                f"Copy và dùng TTS thủ công.")

        # 4. Ghi Sheets
        today = datetime.utcnow().strftime("%Y-%m-%d")
        await append_video_content({
            "id":        vid_id,
            "platform":  platform,
            "topic":     topic,
            "title":     content["title"],
            "caption":   content["caption"],
            "script":    content["script"],
            "audio_url": "",
            "video_url": "",
            "status":    "waiting_video",
            "created_at": today,
            "fb_post_id": "",
        })

    except Exception as e:
        logger.error("run_taobai error: %s", e, exc_info=True)
        await tg_send(bot_token, chat_id, f"❌ Lỗi: <code>{str(e)[:300]}</code>")


# ── /r2 handler ───────────────────────────────────────────────────────────────
async def run_r2(text: str, chat_id: str, bot_token: str):
    """
    /r2 <ID> <video_url>
    Lưu link video R2 vào Sheets
    """
    parts = text.strip().split(maxsplit=2)
    if len(parts) < 3:
        await tg_send(bot_token, chat_id,
            "❓ Sử dụng: <code>/r2 LHFB123456 https://link_video.mp4</code>")
        return

    vid_id = parts[1].upper()
    url    = parts[2]

    try:
        await update_video_r2(vid_id, url)
        await tg_send(bot_token, chat_id,
            f"✅ Đã lưu video!\n\n"
            f"🆔 <code>{vid_id}</code>\n"
            f"🎬 {url[:60]}...\n\n"
            f"Nhắn <code>/dang {vid_id}</code> để đăng lên mạng xã hội.")
    except Exception as e:
        await tg_send(bot_token, chat_id, f"❌ Lỗi lưu R2: <code>{str(e)[:200]}</code>")


# ── /dang handler ─────────────────────────────────────────────────────────────
async def run_dang(text: str, chat_id: str, bot_token: str):
    """
    /dang <ID>
    Đăng video lên Facebook (hoặc platform tương ứng)
    """
    parts = text.strip().split()
    if len(parts) < 2:
        await tg_send(bot_token, chat_id,
            "❓ Sử dụng: <code>/dang LHFB123456</code>")
        return

    vid_id = parts[1].upper()

    try:
        row = await get_video_content(vid_id)
        if not row:
            await tg_send(bot_token, chat_id, f"❌ Không tìm thấy ID: <code>{vid_id}</code>")
            return

        video_url = row.get("video_url", "")
        if not video_url:
            await tg_send(bot_token, chat_id,
                f"⚠️ Bài <code>{vid_id}</code> chưa có link video.\n"
                f"Nhắn: <code>/r2 {vid_id} https://link_video.mp4</code>")
            return

        caption  = row.get("caption", "")
        platform = row.get("platform", "facebook")

        await tg_send(bot_token, chat_id, f"⏳ Đang đăng lên {PLATFORM_LABEL.get(platform, platform)}...")

        fb_post_id = await post_video_facebook(caption, video_url)

        if fb_post_id:
            await update_video_posted(vid_id, fb_post_id)
            await tg_send(bot_token, chat_id,
                f"✅ <b>Đã đăng thành công!</b>\n\n"
                f"🆔 <code>{vid_id}</code>\n"
                f"📌 {row.get('title','')}\n"
                f"🔗 <a href='https://facebook.com/{fb_post_id}'>Xem bài đăng</a>")
        else:
            await tg_send(bot_token, chat_id,
                f"❌ Đăng thất bại. Kiểm tra FB_ACCESS_TOKEN.")

    except Exception as e:
        logger.error("run_dang error: %s", e, exc_info=True)
        await tg_send(bot_token, chat_id, f"❌ Lỗi: <code>{str(e)[:300]}</code>")


# ── Post video to Facebook ────────────────────────────────────────────────────
async def post_video_facebook(caption: str, video_url: str) -> str | None:
    if not FB_PAGE_ID or not FB_ACCESS_TOKEN:
        logger.error("Thiếu FB_PAGE_ID hoặc FB_ACCESS_TOKEN")
        return None

    # Dùng /feed với link video
    params = {
        "message":      caption,
        "link":         video_url,
        "published":    "true",
        "access_token": FB_ACCESS_TOKEN,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/feed",
            data=params
        )
    data = r.json()
    if "error" in data:
        logger.error("FB post error: %s", data["error"])
        return None
    return data.get("id")
