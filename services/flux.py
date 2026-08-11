"""
Cloudflare Workers AI — FLUX image generation
"""
import os
import logging
import httpx

logger = logging.getLogger(__name__)

CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")
CF_API_TOKEN  = os.getenv("CF_API_TOKEN", "")
CF_FLUX_MODEL = os.getenv("CF_FLUX_MODEL", "@cf/black-forest-labs/flux-1-schnell")


async def generate_image_flux(prompt: str, width: int = 1024, height: int = 1024) -> bytes | None:
    """
    Gọi Cloudflare Workers AI FLUX để tạo ảnh.
    Trả về raw bytes (JPEG) hoặc None nếu lỗi.
    """
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        logger.error("Thiếu CF_ACCOUNT_ID hoặc CF_API_TOKEN")
        return None

    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_FLUX_MODEL}"

    payload = {
        "prompt": prompt,
        "num_steps": 4,
        "width": width,
        "height": height,
    }

    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            logger.error("FLUX API error %s: %s", response.status_code, response.text[:200])
            return None

        content_type = response.headers.get("content-type", "")
        if "image" in content_type:
            return response.content

        # Nếu trả về JSON với base64
        data = response.json()
        if data.get("success") and data.get("result", {}).get("image"):
            import base64
            return base64.b64decode(data["result"]["image"])

        logger.error("FLUX unexpected response: %s", str(data)[:200])
        return None

    except Exception as e:
        logger.error("FLUX exception: %s", e)
        return None
