"""
Google Sheets helper — dùng service account JSON
"""
import os
import asyncio
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")

# Lazy import gspread (tránh import lỗi khi chưa cài)
_gc = None

def _get_client():
    global _gc
    if _gc is None:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        # Ưu tiên JSON string từ env (Render secret)
        sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if sa_json:
            info = json.loads(sa_json)
            creds = Credentials.from_service_account_info(info, scopes=scopes)
        else:
            # Fallback: file path
            sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
            creds = Credentials.from_service_account_file(sa_path, scopes=scopes)

        _gc = gspread.authorize(creds)
    return _gc


def _open_sheet(sheet_name: str):
    gc = _get_client()
    wb = gc.open_by_key(SPREADSHEET_ID)
    return wb.worksheet(sheet_name)


# ── IMAGE_LIBRARY ─────────────────────────────────────────────────────────────

async def append_image_library(row: dict):
    """Ghi 1 dòng mới vào sheet IMAGE_LIBRARY"""
    def _write():
        ws = _open_sheet("IMAGE_LIBRARY")
        ws.append_row([
            row.get("ID", ""),
            row.get("Category", ""),
            row.get("Prompt", ""),
            "",  # col D trống
            row.get("URL", ""),
            row.get("UsedCount", 0),
            row.get("LastUsed", ""),
            row.get("Status", "active"),
        ], value_input_option="USER_ENTERED")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _write)


async def get_image_library_all() -> list[dict]:
    """Lấy toàn bộ IMAGE_LIBRARY"""
    def _read():
        ws = _open_sheet("IMAGE_LIBRARY")
        return ws.get_all_records()

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _read)


async def get_image_library_stats() -> dict:
    """Stats tóm tắt cho dashboard"""
    rows = await get_image_library_all()
    total = len(rows)
    by_cat = {}
    for r in rows:
        cat = r.get("Category", "unknown")
        by_cat[cat] = by_cat.get(cat, 0) + 1

    return {
        "total": total,
        "by_category": by_cat,
        "ly_hon":  by_cat.get("ly_hon", 0),
        "dat_dai": by_cat.get("dat_dai", 0),
        "hinh_su": by_cat.get("hinh_su", 0),
    }


async def pick_image(category: str) -> dict | None:
    """Chọn ảnh ít dùng nhất từ IMAGE_LIBRARY"""
    rows = await get_image_library_all()
    filtered = [r for r in rows if r.get("Category") == category and r.get("ID") and r.get("Status", "active") == "active"]
    if not filtered:
        return None

    filtered.sort(key=lambda r: int(r.get("UsedCount") or 0))
    pool   = filtered[:min(5, len(filtered))]
    chosen = pool[__import__("random").randint(0, len(pool)-1)]

    folder_map = {"ly_hon": "ly-hon", "dat_dai": "dat-dai", "hinh_su": "hinh-su"}
    folder = folder_map.get(category, category.replace("_", "-"))
    r2_base = os.getenv("R2_PUBLIC_URL", "https://pub-3b8b5e8b6601441596c0a40d7f1d2ea0.r2.dev")
    image_url = f"{r2_base}/{folder}/{chosen['ID']}.jpg"

    return {
        "id":        chosen["ID"],
        "category":  category,
        "url":       image_url,
        "usedCount": int(chosen.get("UsedCount") or 0),
        "prompt":    chosen.get("Prompt", ""),
    }


async def update_image_used(img_id: str):
    """Tăng UsedCount sau khi đăng"""
    def _update():
        ws   = _open_sheet("IMAGE_LIBRARY")
        rows = ws.get_all_values()
        headers = rows[0] if rows else []
        try:
            id_col      = headers.index("ID") + 1
            used_col    = headers.index("UsedCount") + 1
            last_col    = headers.index("LastUsed") + 1
        except ValueError:
            return  # column không tìm thấy

        for i, row in enumerate(rows[1:], start=2):
            if len(row) >= id_col and row[id_col - 1] == img_id:
                current = int(row[used_col - 1] or 0) if len(row) >= used_col else 0
                ws.update_cell(i, used_col, current + 1)
                ws.update_cell(i, last_col, datetime.now().strftime("%Y-%m-%d %H:%M"))
                break

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _update)


# ── CONTENT SHEET ─────────────────────────────────────────────────────────────

async def append_content(row: dict):
    """Ghi bài viết vào sheet Content"""
    def _write():
        ws = _open_sheet("Content")
        ws.append_row([
            row.get("post_id", ""),
            row.get("service", ""),
            row.get("topic_keyword", ""),
            row.get("topic_title", ""),
            row.get("topic_score", 0),
            row.get("content_type", ""),
            row.get("facebook_text", ""),
            row.get("viral_score", 0),
            row.get("image_id", ""),
            row.get("fb_post_id", ""),
            row.get("created_at", ""),
            row.get("status", "posted"),
        ], value_input_option="USER_ENTERED")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _write)


async def append_topics(row: dict):
    """Ghi topic vào sheet Topics"""
    def _write():
        ws = _open_sheet("Topics")
        ws.append_row([
            row.get("service", ""),
            row.get("topic_keyword", ""),
            row.get("topic_title", ""),
            row.get("content_type", ""),
            row.get("topic_score", 0),
            row.get("created_at", ""),
            row.get("post_id", ""),
        ], value_input_option="USER_ENTERED")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _write)


async def get_topics(service: str, limit: int = 200) -> list[dict]:
    """Lấy danh sách topics đã dùng"""
    def _read():
        ws = _open_sheet("Topics")
        return ws.get_all_records()

    loop = asyncio.get_event_loop()
    rows = await loop.run_in_executor(None, _read)
    filtered = [r for r in rows if r.get("service") == service]
    filtered.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    return filtered[:limit]


async def get_fb_insights(service: str) -> list[dict]:
    """Lấy dữ liệu Facebook Insights để AI học"""
    def _read():
        try:
            ws = _open_sheet("Facebook_Insights")
            return ws.get_all_records()
        except Exception:
            return []

    loop = asyncio.get_event_loop()
    rows = await loop.run_in_executor(None, _read)
    return [r for r in rows if r.get("service") == service]


async def append_fb_insights(row: dict):
    """Ghi FB Insights sau khi đăng"""
    def _write():
        try:
            ws = _open_sheet("Facebook_Insights")
            ws.append_row([
                row.get("post_id", ""),
                row.get("service", ""),
                row.get("topic_keyword", ""),
                row.get("topic_score", 0),
                row.get("viral_score", 0),
                0, 0, 0, 0, 0,  # likes, comments, shares, reach, performance_score
                row.get("created_at", ""),
            ], value_input_option="USER_ENTERED")
        except Exception as e:
            logger.error("append_fb_insights error: %s", e)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _write)


async def get_recent_posts(limit: int = 10) -> list[dict]:
    """Lấy bài viết gần nhất cho dashboard"""
    def _read():
        try:
            ws = _open_sheet("Content")
            rows = ws.get_all_records()
            return rows[-limit:][::-1]
        except Exception:
            return []

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _read)


# ── VIDEO CONTENT SHEET ───────────────────────────────────────────────────────

async def append_video_content(row: dict):
    """Ghi video content vào sheet VideoContent"""
    def _write():
        ws = _open_sheet("VideoContent")
        ws.append_row([
            row.get("id", ""),
            row.get("platform", ""),
            row.get("topic", ""),
            row.get("title", ""),
            row.get("caption", ""),
            row.get("script", ""),
            row.get("audio_url", ""),
            row.get("video_url", ""),
            row.get("status", "waiting_video"),
            row.get("created_at", ""),
            row.get("fb_post_id", ""),
        ], value_input_option="USER_ENTERED")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _write)


async def get_video_content(vid_id: str) -> dict | None:
    """Tìm 1 video theo ID"""
    def _read():
        ws   = _open_sheet("VideoContent")
        rows = ws.get_all_records()
        for r in rows:
            if str(r.get("id", "")).upper() == vid_id.upper():
                return r
        return None

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _read)


async def get_all_video_content() -> list[dict]:
    """Lấy toàn bộ VideoContent cho dashboard"""
    def _read():
        try:
            ws = _open_sheet("VideoContent")
            rows = ws.get_all_records()
            return rows[::-1]  # Mới nhất lên đầu
        except Exception:
            return []

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _read)


async def update_video_r2(vid_id: str, video_url: str):
    """Lưu link video R2 và đổi status → ready"""
    def _update():
        ws      = _open_sheet("VideoContent")
        rows    = ws.get_all_values()
        headers = rows[0] if rows else []
        try:
            id_col    = headers.index("id") + 1
            vid_col   = headers.index("video_url") + 1
            stat_col  = headers.index("status") + 1
        except ValueError:
            return
        for i, row in enumerate(rows[1:], start=2):
            if len(row) >= id_col and row[id_col-1].upper() == vid_id.upper():
                ws.update_cell(i, vid_col, video_url)
                ws.update_cell(i, stat_col, "ready")
                break

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _update)


async def update_video_posted(vid_id: str, fb_post_id: str):
    """Lưu fb_post_id và đổi status → posted"""
    def _update():
        ws      = _open_sheet("VideoContent")
        rows    = ws.get_all_values()
        headers = rows[0] if rows else []
        try:
            id_col   = headers.index("id") + 1
            fb_col   = headers.index("fb_post_id") + 1
            stat_col = headers.index("status") + 1
        except ValueError:
            return
        for i, row in enumerate(rows[1:], start=2):
            if len(row) >= id_col and row[id_col-1].upper() == vid_id.upper():
                ws.update_cell(i, fb_col, fb_post_id)
                ws.update_cell(i, stat_col, "posted")
                break

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _update)
