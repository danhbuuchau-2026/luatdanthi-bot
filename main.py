"""
Luật Danh Thị — Bot Server
Thay thế n8n: IMAGE-FACTORY + MASTER-v3 + Dashboard
Deploy: Render.com (free)
"""
import os
import json
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Bot tokens ──────────────────────────────────────────────────────────────
MASTER_BOT_TOKEN   = os.getenv("MASTER_BOT_TOKEN", "")   # Bot chính (viết bài)
FACTORY_BOT_TOKEN  = os.getenv("FACTORY_BOT_TOKEN", "")  # @luatdanhthi_images_bot
WEBHOOK_SECRET     = os.getenv("WEBHOOK_SECRET", "luatdanthi2024")

# ── App setup ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tải font tiếng Việt (Noto Sans Bold) khi khởi động
    from bot.image_overlay import ensure_fonts
    await ensure_fonts()

    # Đăng ký webhook khi khởi động
    base_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if base_url and MASTER_BOT_TOKEN:
        await register_webhook(MASTER_BOT_TOKEN,  f"{base_url}/webhook/master/{WEBHOOK_SECRET}")
        await register_webhook(FACTORY_BOT_TOKEN, f"{base_url}/webhook/factory/{WEBHOOK_SECRET}")
        logger.info("Webhooks registered: %s", base_url)
    yield

app = FastAPI(title="Luật Danh Thị Bot", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

async def register_webhook(token: str, url: str):
    if not token:
        return
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={"url": url, "allowed_updates": ["message"]}
        )
        logger.info("setWebhook %s → %s", url[:60], r.json().get("description", ""))


# ── Telegram helper ──────────────────────────────────────────────────────────
async def tg_send(token: str, chat_id, text: str, parse_mode="HTML"):
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        )


# ── Webhook endpoints ─────────────────────────────────────────────────────────
@app.post("/webhook/master/{secret}")
async def webhook_master(secret: str, request: Request, bg: BackgroundTasks):
    if secret != WEBHOOK_SECRET:
        raise HTTPException(403)
    body = await request.json()
    msg  = body.get("message", {})
    text = (msg.get("text") or "").strip()
    chat_id = msg.get("chat", {}).get("id") or msg.get("from", {}).get("id")
    if text and chat_id:
        bg.add_task(handle_master, text, str(chat_id))
    return {"ok": True}


@app.post("/webhook/factory/{secret}")
async def webhook_factory(secret: str, request: Request, bg: BackgroundTasks):
    if secret != WEBHOOK_SECRET:
        raise HTTPException(403)
    body = await request.json()
    msg  = body.get("message", {})
    text = (msg.get("text") or "").strip()
    chat_id = msg.get("chat", {}).get("id") or msg.get("from", {}).get("id")
    if text and chat_id:
        bg.add_task(handle_factory, text, str(chat_id))
    return {"ok": True}


# ── Command routers ───────────────────────────────────────────────────────────
async def handle_factory(text: str, chat_id: str):
    """Xử lý lệnh /taoanh cho IMAGE-FACTORY bot"""
    from bot.image_factory import run_image_factory
    t = text.lower()
    if not (t.startswith("/taoanh") or t.startswith("taoanh")):
        return  # im lặng, không reply
    await run_image_factory(text, chat_id, FACTORY_BOT_TOKEN)


async def handle_master(text: str, chat_id: str):
    """Xử lý lệnh viết bài và video cho MASTER-v3 bot"""
    from bot.master_v3 import run_master_v3
    from bot.video_content import run_taobai, run_r2, run_dang

    t = text.lower().strip()

    # ── Video commands ────────────────────────────────────────────────────────
    if t.startswith("taobai ") or t.startswith("/taobai "):
        await run_taobai(text, chat_id, MASTER_BOT_TOKEN)
        return

    if t.startswith("/r2 "):
        await run_r2(text, chat_id, MASTER_BOT_TOKEN)
        return

    if t.startswith("/dang "):
        await run_dang(text, chat_id, MASTER_BOT_TOKEN)
        return

    # ── Facebook post commands ────────────────────────────────────────────────
    key = None
    if "ly hon" in t or "ly hôn" in t or "lyhon" in t:
        key = "ly_hon"
    elif "dat dai" in t or "đất đai" in t or "datdai" in t:
        key = "dat_dai"
    elif "hinh su" in t or "hình sự" in t or "hinhsu" in t:
        key = "hinh_su"

    if key:
        await run_master_v3(key, chat_id, MASTER_BOT_TOKEN)
        return

    # ── Help ──────────────────────────────────────────────────────────────────
    await tg_send(MASTER_BOT_TOKEN, chat_id,
        "❓ <b>Lệnh hợp lệ:</b>\n\n"
        "📘 <b>Đăng bài Facebook (ảnh):</b>\n"
        "• <code>viết bài ly hôn</code>\n"
        "• <code>viết bài đất đai</code>\n"
        "• <code>viết bài hình sự</code>\n\n"
        "🎬 <b>Tạo nội dung video:</b>\n"
        "• <code>taobai lyhonfb</code> — Facebook\n"
        "• <code>taobai lyhontk</code> — TikTok\n"
        "• <code>taobai lyhonytb</code> — YouTube\n"
        "• <code>taobai datdaifb</code> / <code>hinhsufb</code> ...\n\n"
        "🔗 <b>Sau khi có video:</b>\n"
        "• <code>/r2 &lt;ID&gt; &lt;url&gt;</code> — Lưu link video\n"
        "• <code>/dang &lt;ID&gt;</code> — Đăng lên mạng xã hội")


# ── Dashboard API ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/api/stats")
async def api_stats():
    """Stats cho dashboard"""
    try:
        from services.sheets import get_image_library_stats, get_recent_posts, get_all_video_content
        stats   = await get_image_library_stats()
        posts   = await get_recent_posts(limit=10)
        videos  = await get_all_video_content()
        return {"ok": True, "stats": stats, "recent_posts": posts, "videos": videos}
    except Exception as e:
        logger.error("api_stats error: %s", e)
        return {"ok": False, "error": str(e)}


@app.post("/api/post-now")
async def api_post_now(request: Request, bg: BackgroundTasks):
    """Trigger đăng bài từ dashboard"""
    body = await request.json()
    service = body.get("service", "ly_hon")
    chat_id = body.get("chat_id", os.getenv("ADMIN_CHAT_ID", ""))
    bg.add_task(handle_master, f"viết bài {service.replace('_',' ')}", str(chat_id))
    return {"ok": True, "message": f"Đang xử lý {service}..."}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "luatdanthi-bot"}
