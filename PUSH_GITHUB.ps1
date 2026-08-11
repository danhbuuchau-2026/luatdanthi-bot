# Script PowerShell: Push code lên GitHub
# Chạy trong PowerShell tại thư mục luatdanthi-bot

# Bước 1: Khởi tạo git
git init
git branch -M main

# Bước 2: Add tất cả file (trừ những file trong .gitignore)
git add .
git status

# Bước 3: Commit
git commit -m "Initial deploy: Luật Danh Thị Bot (FastAPI + IMAGE-FACTORY + MASTER-v3 + Video Content)"

# Bước 4: Kết nối GitHub repo (thay YOUR_USERNAME bằng username GitHub của bạn)
# Trước khi chạy dòng này: tạo repo "luatdanthi-bot" trên github.com (private)
git remote add origin https://github.com/YOUR_USERNAME/luatdanthi-bot.git

# Bước 5: Push
git push -u origin main

Write-Host "✅ Done! Giờ vào render.com để connect GitHub repo này."
