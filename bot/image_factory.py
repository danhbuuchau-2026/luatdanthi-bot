"""
IMAGE-FACTORY: /taoanh <category> <count>
Thay thế IMAGE-FACTORY n8n workflow
Flow: Parse lệnh → tạo prompt → CF FLUX → R2 → Google Sheets
"""
import os
import asyncio
import time
import random
import string
import logging
import httpx
import boto3
from botocore.config import Config
from services.sheets import append_image_library
from services.flux import generate_image_flux

logger = logging.getLogger(__name__)

R2_BASE    = os.getenv("R2_PUBLIC_URL", "https://pub-3b8b5e8b6601441596c0a40d7f1d2ea0.r2.dev")
R2_BUCKET  = os.getenv("R2_BUCKET_NAME", "ldt-images")

# Prompt templates theo category
PROMPTS = {
    "ly_hon": [
        "Professional Vietnamese female lawyer consulting a woman aged 30-40 in a modern law office, warm natural lighting, emotional but hopeful atmosphere, luxury interior, editorial photography, ultra realistic, high detail, shallow depth of field, no text, no watermark",
        "Vietnamese woman signing divorce papers with lawyer guidance in elegant law office, natural daylight, professional setting, hopeful expression, cinematic photography, no text",
        "Compassionate Vietnamese female lawyer listening to client in consultation room, soft office lighting, trust atmosphere, editorial style, ultra realistic, no text, no watermark",
        "Vietnamese woman walking out of courthouse with relieved expression, new beginning concept, morning sunlight, hopeful mood, documentary photography, ultra realistic, no text",
        "Two Vietnamese lawyers reviewing family law documents in premium office, professional teamwork, warm lighting, editorial photography, ultra realistic, no text, no watermark",
    ],
    "dat_dai": [
        "Vietnamese man aged 40-60 reviewing land ownership documents with professional lawyer in modern office, land dispute consultation, premium business environment, realistic paperwork, editorial photography, ultra realistic, high detail, no text, no watermark",
        "Vietnamese family reviewing land title documents with lawyer, property dispute resolution, modern law office, trust and professionalism, editorial photography, ultra realistic, no text",
        "Professional Vietnamese lawyer presenting land survey map to clients, detailed documents, modern office, editorial style, ultra realistic, no text, no watermark",
        "Vietnamese farmer and lawyer reviewing property boundaries on digital map, rural justice concept, professional setting, cinematic photography, no text, no watermark",
        "Vietnamese couple consulting with real estate lawyer about property inheritance, modern law office, natural lighting, editorial photography, ultra realistic, no text",
    ],
    "hinh_su": [
        "Vietnamese family consulting criminal defense lawyer in modern law office, urgent legal consultation, professional atmosphere, trust and reassurance, editorial photography, ultra realistic, high detail, no text, no watermark",
        "Vietnamese criminal defense lawyer reviewing case files in modern office, serious concentration, professional setting, dramatic lighting, editorial style, no text, no watermark",
        "Vietnamese lawyer presenting defense argument in modern courtroom, confidence and professionalism, cinematic photography, ultra realistic, no text, no watermark",
        "Vietnamese family receiving reassurance from experienced defense lawyer, relief and trust atmosphere, warm office lighting, editorial photography, no text, no watermark",
        "Vietnamese defense lawyer and client reviewing legal documents in private consultation room, confidential setting, professional atmosphere, ultra realistic, no text",
    ],
}

FOLDER_MAP  = {"ly_hon": "ly-hon", "dat_dai": "dat-dai", "hinh_su": "hinh-su"}
PREFIX_MAP  = {"ly_hon": "LH",     "dat_dai": "DD",       "hinh_su": "HS"}


def parse_command(text: str) -> dict | None:
    """Parse /taoanh <category> <count>"""
    parts = text.strip().split()
    if not parts:
        return None
    cmd = parts[0].lower().lstrip("/")
    if cmd != "taoanh":
        return None

    raw_cat = (parts[1] if len(parts) > 1 else "lyhon").lower()
    count   = min(int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 20, 100)

    if "dat" in raw_cat:
        category = "dat_dai"
    elif "hinh" in raw_cat:
        category = "hinh_su"
    else:
        category = "ly_hon"

    return {
        "category": category,
        "folder":   FOLDER_MAP[category],
        "prefix":   PREFIX_MAP[category],
        "count":    count,
    }


def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("R2_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


async def upload_to_r2(image_bytes: bytes, key: str) -> str:
    """Upload ảnh lên R2, trả về public URL"""
    loop = asyncio.get_event_loop()
    client = get_r2_client()

    def _upload():
        client.put_object(
            Bucket=R2_BUCKET,
            Key=key,
            Body=image_bytes,
            ContentType="image/jpeg",
        )

    await loop.run_in_executor(None, _upload)
    return f"{R2_BASE}/{key}"


async def tg_send(token: str, chat_id, text: str):
    async with httpx.AsyncClient(timeout=20) as c:
        await c.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        )


async def run_image_factory(text: str, chat_id: str, bot_token: str):
    """Main flow: parse → generate → upload → ghi Sheets"""
    parsed = parse_command(text)
    if not parsed:
        return

    category = parsed["category"]
    folder   = parsed["folder"]
    prefix   = parsed["prefix"]
    count    = parsed["count"]

    await tg_send(bot_token, chat_id,
        f"⏳ Đang tạo <b>{count} ảnh {category.replace('_',' ').upper()}</b>...\n"
        f"Ước tính {count * 8 // 60 + 1} phút. Chờ tôi nhé!")

    success = 0
    errors  = 0
    prompts = PROMPTS[category]

    for i in range(count):
        try:
            # Chọn prompt ngẫu nhiên
            prompt = prompts[i % len(prompts)]

            # Generate image via Cloudflare FLUX
            img_bytes = await generate_image_flux(prompt)
            if not img_bytes:
                errors += 1
                continue

            # Tạo unique ID
            ts = int(time.time() * 1000)
            serial = f"{i+1:04d}"
            img_id = f"{prefix}_{ts}_{serial}"
            key    = f"{folder}/{img_id}.jpg"

            # Upload R2
            public_url = await upload_to_r2(img_bytes, key)

            # Ghi Google Sheets
            await append_image_library({
                "ID":        img_id,
                "Category":  category,
                "Prompt":    prompt[:200],
                "URL":       public_url,
                "UsedCount": 0,
                "LastUsed":  "",
                "Status":    "active",
            })

            success += 1
            logger.info("✅ %s/%s — %s", i+1, count, img_id)

            # Delay 3s giữa các ảnh để tránh rate limit
            if i < count - 1:
                await asyncio.sleep(3)

        except Exception as e:
            errors += 1
            logger.error("❌ Image %s/%s error: %s", i+1, count, e)
            await asyncio.sleep(5)

    await tg_send(bot_token, chat_id,
        f"✅ <b>Hoàn thành!</b>\n\n"
        f"📁 Category: <code>{category}</code>\n"
        f"✅ Thành công: <b>{success}</b>\n"
        f"❌ Lỗi: <b>{errors}</b>\n\n"
        f"Tổng cộng {success} ảnh đã lưu vào thư viện.")
