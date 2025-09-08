FROM python:3.11-slim

# تثبيت ffmpeg (مطلوب لمعالجة الفيديو)
RUN apt-get update && apt-get install -y ffmpeg

# مجلد العمل
WORKDIR /app

# نسخ المتطلبات وتثبيتها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ كل الملفات
COPY . .

# تشغيل السيرفر على المنفذ 8080 (يعمل في Render & Railway)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
