# Hướng dẫn Deploy lên Render.com (miễn phí)

## Google Sheets cần tạo các tab sau:
- `IMAGE_LIBRARY` — columns: ID, Category, Prompt, (trống), URL, UsedCount, LastUsed, Status
- `Topics` — columns: service, topic_keyword, topic_title, content_type, topic_score, created_at, post_id
- `Facebook_Insights` — columns: post_id, service, topic_keyword, topic_score, viral_score, likes, comments, shares, reach, performance_score, created_at
- `Content` — columns: post_id, service, topic_keyword, topic_title, topic_score, content_type, facebook_text, viral_score, image_id, fb_post_id, created_at, status
- `VideoContent` — columns: id, platform, topic, title, caption, script, audio_url, video_url, status, created_at, fb_post_id

---

## Bước 1 — Chuẩn bị Google Sheets Service Account

1. Vào [console.cloud.google.com](https://console.cloud.google.com)
2. Tạo project mới → Enable **Google Sheets API** + **Google Drive API**
3. IAM & Admin → Service Accounts → Tạo service account
4. Tạo key JSON → download file
5. **Share** Google Sheet của bạn với email service account (Editor)
6. Copy toàn bộ nội dung file JSON → dán vào biến `GOOGLE_SERVICE_ACCOUNT_JSON` trên Render

---

## Bước 2 — Upload code lên GitHub

```bash
cd luatdanthi-bot
git init
git add .
git commit -m "Initial deploy"
git remote add origin https://github.com/YOUR_USERNAME/luatdanthi-bot.git
git push -u origin main
```

---

## Bước 3 — Deploy trên Render.com

1. Đăng ký [render.com](https://render.com) (free)
2. New → **Web Service** → Connect GitHub repo
3. Settings:
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free
4. Điền Environment Variables (copy từ `.env.example`):

| Key | Giá trị |
|-----|---------|
| MASTER_BOT_TOKEN | Token bot viết bài |
| FACTORY_BOT_TOKEN | Token @luatdanhthi_images_bot |
| FB_PAGE_ID | Page ID Facebook |
| FB_ACCESS_TOKEN | Page Access Token |
| ANTHROPIC_API_KEY | sk-ant-... |
| SERPAPI_KEY | Key SerpAPI |
| CF_ACCOUNT_ID | Cloudflare Account ID |
| CF_API_TOKEN | Cloudflare API Token |
| R2_ENDPOINT_URL | https://xxx.r2.cloudflarestorage.com |
| R2_ACCESS_KEY_ID | R2 Access Key |
| R2_SECRET_ACCESS_KEY | R2 Secret Key |
| SPREADSHEET_ID | ID Google Sheet |
| GOOGLE_SERVICE_ACCOUNT_JSON | Nội dung JSON file (1 dòng) |
| ADMIN_CHAT_ID | Chat ID Telegram của bạn |

5. Click **Deploy** → Chờ ~3 phút

---

## Bước 4 — Sau khi deploy

App sẽ tự động đăng ký webhook Telegram khi khởi động.
Webhook URL sẽ là:
- Bot viết bài: `https://YOUR-APP.onrender.com/webhook/master/luatdanthi2024`
- Bot tạo ảnh: `https://YOUR-APP.onrender.com/webhook/factory/luatdanthi2024`

Dashboard: `https://YOUR-APP.onrender.com`

---

## Lưu ý Free Tier

- Render free **sleep sau 15 phút** không có request
- Khi nhắn Telegram, app sẽ wake up (mất ~30 giây lần đầu)
- Để luôn online: dùng **UptimeRobot** ping `/health` mỗi 10 phút (miễn phí)

---

## Lệnh Telegram

**Bot viết bài:**
```
viết bài ly hôn
viết bài đất đai
viết bài hình sự
```

**Bot tạo ảnh (@luatdanhthi_images_bot):**
```
/taoanh lyhon 50
/taoanh datdai 50
/taoanh hinhsu 50
```
