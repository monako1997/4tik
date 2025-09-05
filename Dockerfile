# 1. استخدام صورة بايثون رسمية خفيفة كنقطة بداية
FROM python:3.11-slim

# 2. تحديث النظام وتثبيت FFmpeg (مهم جداً لمعالجة الفيديو)
# هذا الأمر ضروري لأن الكود الخاص بك يستدعي ffmpeg من النظام
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# 3. تحديد مجلد العمل داخل الحاوية (Container)
WORKDIR /app

# 4. نسخ ملف الاعتماديات أولاً للاستفادة من التخزين المؤقت (caching)
COPY requirements.txt .

# 5. هنا يتم تشغيل pip install تلقائيًا بواسطة المنصة
# يقوم بتثبيت كل المكتبات المذكورة في requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 6. نسخ جميع ملفات المشروع المتبقية إلى مجلد العمل
COPY . .

# 7. تحديد المنفذ (Port) الذي سيعمل عليه التطبيق داخل الحاوية
EXPOSE 8000

# 8. الأمر الذي سيتم تشغيله عند بدء تشغيل الحاوية
# نستخدم 0.0.0.0 للسماح بالاتصالات من خارج الحاوية
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
