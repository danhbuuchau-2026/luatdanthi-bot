"""
MASTER-v3: Viết bài → Facebook
Flow: Topics DB → SerpAPI → Claude (chọn topic) → Claude (viết bài) →
      Viral check → Chọn ảnh → Post Facebook → Ghi Sheets
"""
import os
import asyncio
import logging
import json
import re
from datetime import datetime
import httpx

from services.sheets import (
    get_topics, get_fb_insights, append_topics,
    pick_image, update_image_used,
    append_content, append_fb_insights,
)
from bot.image_overlay import generate_and_upload_overlay

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SERPAPI_KEY       = os.getenv("SERPAPI_KEY", "")
FB_PAGE_ID        = os.getenv("FB_PAGE_ID", "")
FB_ACCESS_TOKEN   = os.getenv("FB_ACCESS_TOKEN", "")
WEBSITE_BASE      = os.getenv("WEBSITE_BASE", "https://luatdanhthi.vn")

# ── Config theo service ───────────────────────────────────────────────────────
SERVICE_CFG = {
    "ly_hon": {
        "label":    "Ly Hôn",
        "hashtags": "#LuatDanhThi #LyHon #TuVanLyHon #LuatSuLyHon #ChiaTaiSan",
        "cta":      "Nhắn tin TƯ VẤN để Luật Danh Thị đồng hành cùng bạn.",
        "website":  f"{WEBSITE_BASE}/ly-hon",
        "serp_queries": [
            "ly hon don phuong 2025",
            "quyen nuoi con sau ly hon",
            "chia tai san ly hon khi co nha dat",
            'site:facebook.com "ly hôn"',
            "luat hon nhan gia dinh 2025",
        ],
    },
    "dat_dai": {
        "label":    "Đất Đai",
        "hashtags": "#LuatDanhThi #DatDai #TraanhChapDatDai #SoDo #LuatSuDatDai",
        "cta":      "Nhắn tin ĐẤT ĐAI để được bảo vệ quyền lợi ngay.",
        "website":  f"{WEBSITE_BASE}/dat-dai",
        "serp_queries": [
            "tranh chap dat dai hang xom 2025",
            "thu tuc cap so do nha dat",
            "dat thua ke khong co di chuc",
            'site:facebook.com "tranh chấp đất"',
            "lan chiem dat bi xu ly the nao",
        ],
    },
    "hinh_su": {
        "label":    "Hình Sự",
        "hashtags": "#LuatDanhThi #HinhSu #BaoChua #LuatSuHinhSu #KhangCao",
        "cta":      "Gọi HÌNH SỰ để được luật sư bảo vệ kịp thời.",
        "website":  f"{WEBSITE_BASE}/hinh-su",
        "serp_queries": [
            "luat su bao chua hinh su Viet Nam 2025",
            "bi tam giam quyen cua bi can",
            "an treo la gi dieu kien",
            'site:facebook.com "hình sự"',
            "to giac toi pham thu tuc 2025",
        ],
    },
}


# ── Claude API ────────────────────────────────────────────────────────────────
async def call_claude(system: str, user: str, max_tokens: int = 500) -> str:
    if not ANTHROPIC_API_KEY:
        raise ValueError("Thiếu ANTHROPIC_API_KEY")
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


# ── SerpAPI ───────────────────────────────────────────────────────────────────
async def fetch_serp(query: str) -> dict:
    if not SERPAPI_KEY:
        return {}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get("https://serpapi.com/search.json", params={
            "q": query, "api_key": SERPAPI_KEY,
            "hl": "vi", "gl": "vn", "num": 8, "engine": "google",
        })
    return r.json() if r.status_code == 200 else {}


async def get_serp_summary(queries: list[str]) -> str:
    tasks   = [fetch_serp(q) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    organic   = []
    related   = []
    questions = []
    for idx, d in enumerate(results):
        if isinstance(d, Exception) or not d:
            continue
        lbl = f"[Q{idx+1}] "
        for r in (d.get("organic_results") or [])[:4]:
            organic.append(lbl + (r.get("title") or "") + " — " + (r.get("snippet") or "")[:120])
        for r in (d.get("related_searches") or [])[:3]:
            related.append(r.get("query") or "")
        for q in (d.get("related_questions") or [])[:2]:
            questions.append(q.get("question") or "")

    parts = [f"KẾT QUẢ TỪ {len(queries)} QUERIES:", ""]
    parts += organic[:25]
    if related:
        parts.append("LIÊN QUAN:\n" + " | ".join(list(dict.fromkeys(related))[:10]))
    if questions:
        parts.append("NGƯỜI DÙNG HỎI:\n" + "\n".join(list(dict.fromkeys(questions))[:8]))
    return "\n".join(parts)


# ── Topic selection ───────────────────────────────────────────────────────────
async def choose_topic(service: str, cfg: dict, serp_summary: str,
                        existing_topics: list, insights: list) -> dict:
    topic_list = "\n".join(
        f"{i+1}. [{t.get('topic_keyword','')}] {t.get('topic_title','')} (Score:{t.get('topic_score',0)})"
        for i, t in enumerate(existing_topics)
    ) or "(Chưa có topic nào)"

    has_learning = len(insights) >= 5
    learning_txt = ""
    if has_learning:
        sorted_ins = sorted(insights, key=lambda r: float(r.get("performance_score") or 0), reverse=True)
        top = sorted_ins[:10]
        bot = sorted_ins[-10:]
        learning_txt = (
            "BÀI HIỆU QUẢ CAO (học theo):\n" +
            "\n".join(f"{i+1}. [{r.get('performance_score')}pts] {r.get('topic_keyword')} VS:{r.get('viral_score')}" for i,r in enumerate(top)) +
            "\n\nBÀI HIỆU QUẢ THẤP (tránh):\n" +
            "\n".join(f"{i+1}. [{r.get('performance_score')}pts] {r.get('topic_keyword')} VS:{r.get('viral_score')}" for i,r in enumerate(bot))
        )

    system = "\n".join(filter(None, [
        f"Bạn là chuyên gia content pháp lý Việt Nam. Đề xuất 1 topic mới cho dịch vụ {cfg['label']}.",
        "THANG ĐIỂM (0-100): Search Demand 40% + Emotional Impact 30% + Conversion 20% + FB Discussion 10%",
        f"--- {len(existing_topics)} TOPICS ĐÃ DÙNG (KHÔNG LẶP LẠI) ---",
        topic_list,
        learning_txt,
        "OUTPUT — CHỈ 6 DÒNG NÀY:",
        "TOPIC_KEYWORD: (2-5 từ)",
        "TOPIC_TITLE: (câu hỏi hấp dẫn)",
        "TOPIC_SCORE: (0-100)",
        "SEARCH_REASON: (1 câu)",
        "CONTENT_TYPE: CASE hoặc TIPS hoặc QA hoặc LAW",
        "SCENE_DESCRIPTION: (English, max 12 words)",
        "TUYỆT ĐỐI KHÔNG dùng ## hay **. Bắt đầu NGAY bằng TOPIC_KEYWORD:",
    ]))

    raw = await call_claude(system, f"Dữ liệu:\n\n{serp_summary}\n\nChọn 1 topic tốt nhất cho {cfg['label']}.", max_tokens=300)

    def get(key):
        m = re.search(rf"{key}[\s]*[:\s][\s]*([^\n\r]+)", raw, re.IGNORECASE)
        return m.group(1).replace("*", "").replace("#", "").strip() if m else ""

    return {
        "topic_keyword": get("TOPIC_KEYWORD"),
        "topic_title":   get("TOPIC_TITLE"),
        "topic_score":   int(re.sub(r"\D", "", get("TOPIC_SCORE") or "75") or "75"),
        "search_reason": get("SEARCH_REASON"),
        "content_type":  (get("CONTENT_TYPE") or "CASE").split()[0].upper(),
        "scene_desc":    get("SCENE_DESCRIPTION"),
    }


# ── Content writing ───────────────────────────────────────────────────────────
async def write_content(service: str, cfg: dict, topic: dict, insights: list) -> dict:
    has_learning = len(insights) >= 5
    learning_txt = ""
    if has_learning:
        sorted_ins = sorted(insights, key=lambda r: float(r.get("performance_score") or 0), reverse=True)
        top = sorted_ins[:5]
        learning_txt = "BÀI VIRAL NHẤT:\n" + "\n".join(f"- {r.get('topic_keyword')} ({r.get('performance_score')}pts)" for r in top)

    system = "\n".join(filter(None, [
        f"Bạn là Social Media Manager Công ty Luật Danh Thị.",
        "Viết 1 bài Facebook: gần gũi, đồng cảm, kể chuyện thực tế, KHÔNG học thuật.",
        "Không cam kết chắc thắng. Không dùng em dash. Đoạn ngắn, dễ đọc mobile.",
        learning_txt,
        f"CTA: {cfg['cta']}",
        f"Hashtags: {cfg['hashtags']}",
        "Độ dài: 380-500 ký tự (không tính hashtag)",
        "",
        "OUTPUT FORMAT:",
        "TITLE: (tiêu đề)",
        "HOOK: (câu đầu, max 80 ký tự)",
        "KEY_POINTS: điểm1 | điểm2 | điểm3",
        "FACEBOOK_TEXT_START",
        "(nội dung + CTA + hashtags)",
        "FACEBOOK_TEXT_END",
    ]))

    user = (
        f"Dịch vụ: {cfg['label']}\n"
        f"Loại: {topic['content_type']}\n"
        f"Chủ đề: {topic['topic_title']}\n"
        f"Từ khóa: {topic['topic_keyword']}\n"
        f"Lý do viral: {topic['search_reason']}"
    )

    raw = await call_claude(system, user, max_tokens=1500)

    # Extract FACEBOOK_TEXT
    m = re.search(r"FACEBOOK_TEXT_START\s*(.*?)\s*FACEBOOK_TEXT_END", raw, re.DOTALL)
    fb_text = m.group(1).strip() if m else raw

    def get(key):
        match = re.search(rf"{key}[\s]*[:\s][\s]*([^\n\r]+)", raw, re.IGNORECASE)
        return match.group(1).replace("*", "").replace("#", "").strip() if match else ""

    # Viral check
    viral_score = await check_viral(fb_text, cfg["label"])

    # Nếu viral score thấp, viết lại
    if viral_score < 60:
        logger.info("Viral score %s < 60, rewriting...", viral_score)
        system2 = system + "\n\nViết lại bài này để tăng cảm xúc và tính viral hơn."
        raw2 = await call_claude(system2, user + f"\n\nBài cũ (viral={viral_score}):\n{fb_text}", max_tokens=1500)
        m2 = re.search(r"FACEBOOK_TEXT_START\s*(.*?)\s*FACEBOOK_TEXT_END", raw2, re.DOTALL)
        if m2:
            fb_text    = m2.group(1).strip()
            viral_score = await check_viral(fb_text, cfg["label"])

    return {
        "title":      get("TITLE"),
        "hook":       get("HOOK"),
        "key_points": get("KEY_POINTS"),
        "fb_text":    fb_text,
        "viral_score": viral_score,
    }


async def check_viral(fb_text: str, label: str) -> int:
    """Chấm điểm viral 0-100"""
    system = (
        "Bạn là chuyên gia viral marketing Facebook Việt Nam. "
        "Chấm viral score 0-100 cho bài đăng pháp lý. "
        "CHỈ trả về 1 số nguyên duy nhất, không giải thích."
    )
    user = f"Bài {label}:\n{fb_text}"
    raw = await call_claude(system, user, max_tokens=10)
    m = re.search(r"\d+", raw)
    return min(int(m.group(0)), 100) if m else 70


# ── Facebook posting ──────────────────────────────────────────────────────────
async def post_to_facebook(caption: str, image_url: str | None) -> str | None:
    """Post lên Facebook, trả về post_id"""
    if not FB_PAGE_ID or not FB_ACCESS_TOKEN:
        raise Exception("Thiếu FB_PAGE_ID hoặc FB_ACCESS_TOKEN trong Render env vars")

    params = {
        "caption":      caption,
        "published":    "true",
        "access_token": FB_ACCESS_TOKEN,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        if image_url:
            # Đăng kèm ảnh qua /photos
            photo_params = {
                "url":          image_url,
                "caption":      caption,
                "published":    "true",
                "access_token": FB_ACCESS_TOKEN,
            }
            r = await client.post(
                f"https://graph.facebook.com/v21.0/{FB_PAGE_ID}/photos",
                data=photo_params
            )
            data = r.json()
            if "error" in data:
                logger.warning("Photo post failed, fallback to feed: %s", data["error"])
                # Fallback: đăng text + link ảnh vào feed
                feed_params = {
                    "message":      caption + f"\n\n{image_url}",
                    "published":    "true",
                    "access_token": FB_ACCESS_TOKEN,
                }
                r = await client.post(
                    f"https://graph.facebook.com/v21.0/{FB_PAGE_ID}/feed",
                    data=feed_params
                )
                data = r.json()
        else:
            # Đăng text only
            feed_params = {
                "message":      caption,
                "published":    "true",
                "access_token": FB_ACCESS_TOKEN,
            }
            r = await client.post(
                f"https://graph.facebook.com/v21.0/{FB_PAGE_ID}/feed",
                data=feed_params
            )
            data = r.json()

    if "error" in data:
        err = data["error"]
        logger.error("FB post error: %s", err)
        raise Exception(f"Facebook API lỗi {err.get('code','?')}: {err.get('message', str(err))}")

    return data.get("post_id") or data.get("id")


# ── Telegram helper ───────────────────────────────────────────────────────────
async def tg_send(token: str, chat_id, text: str, parse_mode="HTML"):
    async with httpx.AsyncClient(timeout=20) as c:
        await c.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
        )


async def tg_send_photo(token: str, chat_id, photo_url: str, caption: str = ""):
    """Gửi ảnh về Telegram — dùng khi Facebook fail"""
    async with httpx.AsyncClient(timeout=30) as c:
        await c.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            json={
                "chat_id":  chat_id,
                "photo":    photo_url,
                "caption":  caption[:1024],  # Telegram giới hạn 1024 ký tự caption
            },
        )


# ── MAIN flow ─────────────────────────────────────────────────────────────────
async def run_master_v3(service: str, chat_id: str, bot_token: str):
    cfg = SERVICE_CFG[service]
    now_vn = datetime.utcnow()  # Render UTC; VN = UTC+7
    today  = now_vn.strftime("%Y-%m-%d")
    post_id = f"LDT-{today.replace('-','')}-{service[:4].upper()}-{int(__import__('time').time())%10000}"
    content   = {}    # init sớm để error handler có thể dùng
    image_url = None  # ảnh overlay, dùng trong error handler

    await tg_send(bot_token, chat_id,
        f"⏳ <b>Đang xử lý {cfg['label']}...</b>\n\n"
        "🗂️ Topics DB → 🔍 SerpAPI → ⭐ Score → ✍️ Viết → 📊 Viral → 🖼️ Ảnh → 📱 Facebook\n\n"
        "Vui lòng chờ 2-4 phút.")

    try:
        # 1. Lấy existing topics (graceful — chạy được kể cả không có Sheets)
        try:
            existing = await get_topics(service)
        except Exception as e:
            logger.warning("get_topics failed (Sheets chưa cấu hình?): %s", e)
            existing = []

        # 2. SerpAPI
        serp_summary = await get_serp_summary(cfg["serp_queries"])

        # 3. FB Insights (graceful)
        try:
            insights = await get_fb_insights(service)
        except Exception as e:
            logger.warning("get_fb_insights failed: %s", e)
            insights = {}

        # 4. Chọn topic với Claude
        topic = await choose_topic(service, cfg, serp_summary, existing, insights)
        if not topic["topic_keyword"]:
            raise ValueError("Claude không trả về topic hợp lệ")

        await tg_send(bot_token, chat_id,
            f"✅ <b>Topic:</b> {topic['topic_title']}\n"
            f"📊 Score: {topic['topic_score']} | Loại: {topic['content_type']}\n\n"
            "✍️ Đang viết bài...")

        # 5. Lưu topic vào Sheets (graceful)
        try:
            await append_topics({**topic, "service": service, "created_at": today, "post_id": post_id})
        except Exception as e:
            logger.warning("append_topics failed: %s", e)

        # 6. Viết bài với Claude
        content = await write_content(service, cfg, topic, insights)

        await tg_send(bot_token, chat_id,
            f"📝 <b>Bài đã viết</b> (Viral: {content['viral_score']}/100)\n\n"
            f"🖼️ Đang tạo ảnh overlay và đăng Facebook...")

        # 7. Tạo ảnh text-overlay từ hook của bài viết
        hook_line = content.get("hook") or content["fb_text"].split('\n')[0]
        image_url = await generate_and_upload_overlay(hook_line, service)

        # Fallback: lấy từ thư viện nếu overlay fail
        img = None
        if not image_url:
            try:
                img = await pick_image(service)
                image_url = img["url"] if img else None
            except Exception as e:
                logger.warning("pick_image failed: %s", e)
                img = None

        # 8. Post Facebook
        fb_post_id = await post_to_facebook(content["fb_text"], image_url)

        if fb_post_id:
            if img:
                try:
                    await update_image_used(img["id"])
                except Exception as e:
                    logger.warning("update_image_used failed: %s", e)

            # 9. Ghi Content sheet (graceful)
            try:
                await append_content({
                    "post_id":       post_id,
                    "service":       service,
                    "topic_keyword": topic["topic_keyword"],
                    "topic_title":   topic["topic_title"],
                    "topic_score":   topic["topic_score"],
                    "content_type":  topic["content_type"],
                    "facebook_text": content["fb_text"],
                    "viral_score":   content["viral_score"],
                    "image_id":      img["id"] if img else "",
                    "fb_post_id":    fb_post_id,
                    "created_at":    today,
                    "status":        "posted",
                })
            except Exception as e:
                logger.warning("append_content failed: %s", e)

            # 10. Ghi FB Insights (graceful)
            try:
                await append_fb_insights({
                    "post_id":       post_id,
                    "service":       service,
                    "topic_keyword": topic["topic_keyword"],
                    "topic_score":   topic["topic_score"],
                    "viral_score":   content["viral_score"],
                    "created_at":    today,
                })
            except Exception as e:
                logger.warning("append_fb_insights failed: %s", e)

            img_status = "🖼️ overlay" if (image_url and not img) else ("🎨 thư viện" if img else "không có ảnh")
            await tg_send(bot_token, chat_id,
                f"✅ <b>Đã đăng thành công!</b>\n\n"
                f"📌 <b>{topic['topic_title']}</b>\n"
                f"📊 Topic Score: {topic['topic_score']} | Viral: {content['viral_score']}/100\n"
                f"🆔 Post ID: <code>{post_id}</code>\n"
                f"🖼️ Ảnh: {img_status}\n\n"
                f"🔗 <a href='https://facebook.com/{fb_post_id}'>Xem bài đăng</a>")
        else:
            await tg_send(bot_token, chat_id,
                "⚠️ Đã viết bài nhưng <b>lỗi đăng Facebook</b>.\n\n"
                f"Bài viết:\n{content['fb_text'][:500]}...")

    except Exception as e:
        logger.error("run_master_v3 error: %s", e, exc_info=True)
        err_msg   = str(e)
        fb_text   = content.get("fb_text", "") if content else ""
        # Nếu lỗi Facebook → gửi ảnh overlay + caption về Telegram để đăng thủ công
        if "Facebook API" in err_msg and fb_text:
            await tg_send(bot_token, chat_id,
                "⚠️ <b>Facebook chặn API — gửi ảnh + caption về đây để đăng thủ công:</b>")
            if image_url:
                # Gửi ảnh overlay kèm caption
                await tg_send_photo(bot_token, chat_id, image_url, fb_text[:900])
            else:
                # Không có ảnh → gửi text
                await tg_send(bot_token, chat_id, fb_text, parse_mode="")
        else:
            await tg_send(bot_token, chat_id,
                f"❌ <b>Lỗi xử lý:</b>\n<code>{err_msg[:300]}</code>\n\n"
                "Thử lại sau vài phút.")
