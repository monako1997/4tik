# نستخدم نسخة خفيفة من بايثون
FROM python:3.11-slim

# تثبيت ffmpeg عشان معالجة الفيديو
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# مجلد العمل
WORKDIR /app

# نسخ requirements.txt وتثبيت المكتبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ بقية الملفات (main.py + index.html وغيره)
COPY . .

# تشغيل التطبيق مباشرة باستخدام Flask
CMD ["python", "main.py"]