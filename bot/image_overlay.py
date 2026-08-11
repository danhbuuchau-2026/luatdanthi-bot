"""
IMAGE OVERLAY — Tạo ảnh text-overlay style cho Facebook
Style đã duyệt: nền navy tối + brand vàng + chữ trắng lớn + divider + CTA vàng
Output: JPEG bytes → upload R2 → URL cho Facebook
"""

import os
import io
import asyncio
import logging
import textwrap
import time
import random

import httpx
import boto3
from botocore.config import Config
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

R2_BASE   = os.getenv("R2_PUBLIC_URL", "https://pub-3b8b5e8b6601441596c0a40d7f1d2ea0.r2.dev")
R2_BUCKET = os.getenv("R2_BUCKET_NAME", "ldt-images")

# ── Màu nền theo service (cùng navy, khác đường viền) ─────────────────────────
BG_COLORS = {
    "ly_hon":   (18, 24, 42),    # Navy đậm
    "nuoi_con": (22, 28, 45),    # Navy xanh nhạt hơn
    "dat_dai":  (16, 26, 40),    # Navy xanh đất
    "hinh_su":  (20, 20, 28),    # Navy gần đen
}

GOLD  = (210, 172, 90)
WHITE = (255, 255, 255)

# Font có sẵn trên Render.com (Ubuntu) — hỗ trợ tiếng Việt đầy đủ
# Thử Noto Sans Bold (tải từ GitHub khi startup), fallback về DejaVu
FONT_NOTO_PATH  = "/tmp/NotoSans-Bold.ttf"
FONT_NOTO_COND  = "/tmp/NotoSans-Condensed-Bold.ttf"
FONT_NOTO_URL   = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Bold.ttf"
FONT_NOTO_C_URL = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Condensed-Bold.ttf"

# Fallback fonts có sẵn trên hệ thống
FONT_FALLBACKS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

_fonts_ready = False


# ── Font loader ───────────────────────────────────────────────────────────────
async def ensure_fonts():
    """Tải Noto Sans Bold từ GitHub lúc khởi động. Fallback về DejaVu nếu fail."""
    global _fonts_ready
    if _fonts_ready:
        return

    urls = [
        (FONT_NOTO_URL,   FONT_NOTO_PATH),
        (FONT_NOTO_C_URL, FONT_NOTO_COND),
    ]
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for url, path in urls:
                if not os.path.exists(path):
                    r = await client.get(url)
                    if r.status_code == 200:
                        with open(path, "wb") as f:
                            f.write(r.content)
                        logger.info("✅ Font downloaded: %s (%d bytes)", path, len(r.content))
    except Exception as e:
        logger.warning("Font download failed: %s — dùng fallback", e)

    _fonts_ready = True


def _get_font(size: int, condensed: bool = False) -> ImageFont.FreeTypeFont:
    """Trả về font tốt nhất có sẵn hỗ trợ tiếng Việt."""
    candidates = []
    if condensed:
        candidates = [FONT_NOTO_COND, FONT_NOTO_PATH] + FONT_FALLBACKS
    else:
        candidates = [FONT_NOTO_PATH] + FONT_FALLBACKS

    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ── Core: generate overlay image ──────────────────────────────────────────────
def make_overlay_image(
    hook_text: str,
    service: str = "ly_hon",
    brand: str = "Luật Danh Thị",
) -> bytes:
    """
    Tạo ảnh 1080x1080 style navy dark:
    - Nền màu navy tối
    - Brand name nhỏ màu vàng ở trên
    - Hook text lớn màu trắng căn giữa
    - Divider vàng + CTA vàng bên dưới
    Trả về JPEG bytes.
    """
    W, H = 1080, 1080
    bg_color = BG_COLORS.get(service, BG_COLORS["ly_hon"])

    # 1. Canvas nền
    canvas = Image.new("RGB", (W, H), bg_color)
    draw   = ImageDraw.Draw(canvas)

    # 2. Fonts
    font_brand = _get_font(34)
    font_hook  = _get_font(90, condensed=True)
    font_cta   = _get_font(36)

    # 3. Làm sạch hook text
    hook = hook_text.strip().split('\n')[0].strip()
    hook = hook.lstrip('🔥⚡💥❗❓👉📌⚠️✅•-–— ').strip()
    if len(hook) > 70:
        hook = hook[:67] + "..."

    # 4. Brand ở trên (vàng, căn giữa)
    brand_text = f"CÔNG TY {brand.upper()}"
    bb = draw.textbbox((0, 0), brand_text, font=font_brand)
    draw.text(((W - (bb[2] - bb[0])) // 2, 88), brand_text, font=font_brand, fill=GOLD)

    # 5. Hook text (trắng, chữ hoa, wrap 16 ký tự/dòng)
    wrapped = textwrap.wrap(hook.upper(), width=16)[:5]
    LINE_H  = 105
    total_h = len(wrapped) * LINE_H
    start_y = (H - total_h) // 2 - 30

    for i, line in enumerate(wrapped):
        bb = draw.textbbox((0, 0), line, font=font_hook)
        tw = bb[2] - bb[0]
        x  = (W - tw) // 2
        y  = start_y + i * LINE_H
        # Shadow nhẹ
        draw.text((x + 2, y + 2), line, font=font_hook, fill=(0, 0, 0))
        draw.text((x, y), line, font=font_hook, fill=WHITE)

    # 6. Divider vàng
    div_y = start_y + total_h + 32
    draw.rectangle([(W // 2 - 55, div_y), (W // 2 + 55, div_y + 4)], fill=GOLD)

    # 7. CTA text (vàng, căn giữa)
    cta = "Nhắn tin để được tư vấn miễn phí"
    bb  = draw.textbbox((0, 0), cta, font=font_cta)
    draw.text(((W - (bb[2] - bb[0])) // 2, div_y + 18), cta, font=font_cta, fill=GOLD)

    # 8. Viền mảnh vàng 4 cạnh (tuỳ chọn — tăng tính brand)
    border = 6
    draw.rectangle([border, border, W - border, H - border], outline=GOLD, width=2)

    # 9. Export JPEG
    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=93, optimize=True)
    return out.getvalue()


# ── R2 upload ─────────────────────────────────────────────────────────────────
def _get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("R2_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


async def upload_overlay_to_r2(img_bytes: bytes, service: str) -> str:
    """Upload ảnh overlay lên R2, trả về public URL."""
    ts   = int(time.time() * 1000)
    rand = random.randint(1000, 9999)
    folder_map = {
        "ly_hon":   "ly-hon",
        "nuoi_con": "ly-hon",
        "dat_dai":  "dat-dai",
        "hinh_su":  "hinh-su",
    }
    folder = folder_map.get(service, "general")
    key    = f"{folder}/overlay_{ts}_{rand}.jpg"

    loop   = asyncio.get_event_loop()
    client = _get_r2_client()

    def _upload():
        client.put_object(
            Bucket=R2_BUCKET,
            Key=key,
            Body=img_bytes,
            ContentType="image/jpeg",
        )

    await loop.run_in_executor(None, _upload)
    return f"{R2_BASE}/{key}"


# ── Public API ────────────────────────────────────────────────────────────────
async def generate_and_upload_overlay(
    hook_text: str,
    service:   str = "ly_hon",
    brand:     str = "Luật Danh Thị",
) -> str | None:
    """
    Full pipeline: generate overlay image → upload R2 → return public URL.
    Gọi ensure_fonts() một lần lúc startup để có font tốt nhất.
    """
    try:
        loop = asyncio.get_event_loop()
        img_bytes = await loop.run_in_executor(
            None, make_overlay_image, hook_text, service, brand
        )
        url = await upload_overlay_to_r2(img_bytes, service)
        logger.info("✅ Overlay image: %s", url)
        return url

    except Exception as e:
        logger.error("❌ generate_and_upload_overlay error: %s", e, exc_info=True)
        return None
