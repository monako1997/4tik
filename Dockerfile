FROM python:3.11-slim

# تثبيت ffmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# مكان العمل
WORKDIR /app

# تثبيت المتطلبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي الملفات (index.html, main.py, manifest.json, sw.js, icons…)
COPY . .

# إنشاء مجلد التخزين الدائم للمفاتيح
RUN mkdir -p /data

# المنفذ
EXPOSE 8000

# تشغيل السيرفر
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
