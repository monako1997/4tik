import os
import uuid
import shutil
import subprocess
import json
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

BASE = Path(__file__).resolve().parent
WORK = BASE / "work"
LOG_FILE = BASE / "ip_log.json"
WORK.mkdir(exist_ok=True)

MAX_SIZE = 100 * 1024 * 1024
WAIT_DURATION = timedelta(hours=24)

def read_ip_log():
    if not LOG_FILE.exists():
        return {}
    with open(LOG_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def write_ip_log(data):
    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=4)

@app.get("/", response_class=HTMLResponse)
def home():
    html_path = BASE / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>index.html غير موجود</h1>", status_code=500)
    return html_path.read_text(encoding="utf-8")

# --- بداية التعديل المهم ---
def run_ffmpeg_and_log(cmd: list[str]) -> (bool, str):
    """
    تشغيل ffmpeg مع تسجيل أي أخطاء تحدث بدلاً من إخفائها.
    ترجع (نجاح؟, رسالة الخطأ)
    """
    try:
        # استخدام capture_output=True لالتقاط المخرجات
        p = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
        if p.returncode != 0:
            # إذا فشل ffmpeg، قم بتسجيل الخطأ
            error_message = p.stderr.strip()
            print(f"--- FFMPEG ERROR ---\n{error_message}\n--------------------")
            return (False, error_message)
        return (True, "") # نجح الأمر
    except Exception as e:
        print(f"--- PYTHON SUBPROCESS ERROR ---\n{e}\n--------------------")
        return (False, str(e))
# --- نهاية التعديل المهم ---


@app.post("/process")
async def process(request: Request, file: UploadFile = File(...)):
    client_ip = request.client.host
    ip_log = read_ip_log()

    if client_ip in ip_log:
        last_upload_time = datetime.fromisoformat(ip_log[client_ip])
        if datetime.now() < last_upload_time + WAIT_DURATION:
            remaining_time = (last_upload_time + WAIT_DURATION) - datetime.now()
            hours, remainder = divmod(remaining_time.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            error_message = f"لقد استنفدت حدك اليومي. يرجى المحاولة مرة أخرى بعد {hours} ساعة و {minutes} دقيقة."
            raise HTTPException(status_code=429, detail=error_message)

    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="⚠️ الملف أكبر من 100MB")
    await file.seek(0)

    uid = uuid.uuid4().hex
    in_path  = WORK / f"in_{uid}.mp4"
    out_path = WORK / f"out_{uid}.mp4"

    try:
        with open(in_path, "wb", buffering=0) as f:
            await file.seek(0)
            shutil.copyfileobj(file.file, f)

        # استخدام الدالة الجديدة بدلاً من القديمة
        ok, ffmpeg_error = run_ffmpeg_and_log([
            "ffmpeg", "-y",
            "-itsscale", "2",
            "-i", str(in_path),
            "-c:v", "copy",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(out_path)
        ])

        if not ok or not out_path.exists():
            # الآن سنعرف سبب المشكلة
            raise HTTPException(status_code=500, detail="فشلت معالجة الفيديو. تحقق من سجلات الخادم للمزيد من التفاصيل.")

        ip_log[client_ip] = datetime.now().isoformat()
        write_ip_log(ip_log)

        headers = {"Content-Disposition": 'attachment; filename="4tik.mp4"'}
        return FileResponse(out_path, media_type="video/mp4", headers=headers, background=os.remove(out_path))

    finally:
        if in_path.exists():
            os.remove(in_path)
