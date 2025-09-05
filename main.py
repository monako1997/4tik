import os, uuid, shutil, subprocess, json, threading
from datetime import datetime, timezone
from pathlib import Path
from math import ceil
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

# نوقف عرض وثائق API
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

BASE = Path(__file__).resolve().parent
WORK = BASE / "work"
WORK.mkdir(exist_ok=True)

DB_PATH = BASE / "keys.json"
DB_LOCK = threading.Lock()

MAX_SIZE = 100 * 1024 * 1024  # 100MB

# ========= أدوات مساعدة =========
def utcnow():
    return datetime.now(timezone.utc)

def load_db():
    if not DB_PATH.exists():
        DB_PATH.write_text("[]", encoding="utf-8")
    try:
        return json.loads(DB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_db(data):
    with DB_LOCK:
        DB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def find_key(data, k):
    for row in data:
        if row.get("key") == k:
            return row
    return None

def run_silent(cmd: list[str]) -> bool:
    try:
        p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=False)
        return p.returncode == 0
    except Exception:
        return False

def check_and_bind_device(client_key: str, device_hash: str):
    """
    يتحقق من المفتاح وتاريخ الانتهاء، ويربط أول جهاز يستخدم المفتاح.
    """
    data = load_db()
    row = find_key(data, client_key)
    if not row:
        return False, "المفتاح غير موجود"

    exp = row.get("expires")
    try:
        exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
    except Exception:
        return False, "صيغة تاريخ غير صالحة"

    if utcnow() > exp_dt:
        return False, "انتهت صلاحية الاشتراك"

    bind = row.get("device_hash") or ""
    if not bind:
        # أول استعمال: اربط بالجهاز الحالي
        row["device_hash"] = device_hash
        row["last_used"] = utcnow().isoformat()
        save_db(data)
        return True, "تم ربط المفتاح بهذا الجهاز"
    else:
        if bind != device_hash:
            return False, "هذا المفتاح مربوط بجهاز آخر"
        row["last_used"] = utcnow().isoformat()
        save_db(data)
        return True, "مسموح"

def mask_key(k: str) -> str:
    if not k: return ""
    if len(k) <= 8: return k
    return k[:4] + "*"*(len(k)-8) + k[-4:]

# ========= المسارات =========

@app.get("/", response_class=HTMLResponse)
def home():
    html_path = BASE / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>index.html غير موجود</h1>", status_code=500)
    return html_path.read_text(encoding="utf-8")

@app.post("/check")
async def check(request: Request):
    client_key = request.headers.get("X-KEY", "")
    device_hash = request.headers.get("X-DEVICE", "")
    if not client_key or not device_hash:
        return JSONResponse({"ok": False, "msg": "المعلومات ناقصة"}, status_code=400)

    ok, msg = check_and_bind_device(client_key, device_hash)
    code = 200 if ok else 401
    return JSONResponse({"ok": ok, "msg": msg}, status_code=code)

@app.post("/process")
async def process(request: Request, file: UploadFile = File(...)):
    # تحقّق المفتاح + الجهاز
    client_key = request.headers.get("X-KEY", "")
    device_hash = request.headers.get("X-DEVICE", "")
    if not client_key or not device_hash:
        return JSONResponse({"error": "مطلوب المفتاح والجهاز"}, status_code=400)

    ok, msg = check_and_bind_device(client_key, device_hash)
    if not ok:
        return JSONResponse({"error": msg}, status_code=401)

    # حدّ الحجم
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        return JSONResponse({"error": "الملف أكبر من 100MB"}, status_code=400)
    await file.seek(0)

    # معالجة
    uid = uuid.uuid4().hex
    in_path  = WORK / f"in_{uid}.mp4"
    out_path = WORK / f"out_{uid}.mp4"

    try:
        with open(in_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        ok = run_silent([
            "ffmpeg","-y",
            "-itsscale","2",
            "-i", str(in_path),
            "-c:v","copy",
            "-c:a","copy",
            "-movflags","+faststart",
            str(out_path)
        ])
        if not ok or not out_path.exists():
            return JSONResponse({"error": "تعذر إتمام المعالجة"}, status_code=500)

        headers = {"Content-Disposition": 'attachment; filename="output.mp4"'}
        return FileResponse(str(out_path), media_type="video/mp4", headers=headers)
    finally:
        try: os.remove(in_path)
        except: pass

@app.get("/me")
async def me(request: Request):
    client_key = request.headers.get("X-KEY", "")
    device_hash = request.headers.get("X-DEVICE", "")

    data = load_db()
    row = find_key(data, client_key)
    if not row:
        return JSONResponse({"error": "المفتاح غير موجود"}, status_code=404)

    # تحقق انتهاء
    exp = row.get("expires")
    try:
        exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
    except Exception:
        return JSONResponse({"error": "صيغة تاريخ غير صالحة"}, status_code=500)

    now = utcnow()
    seconds_left = (exp_dt - now).total_seconds()
    days_left = max(0, ceil(seconds_left / 86400))

    # حالة الربط بدون تعديل قاعدة البيانات
    bound_hash = row.get("device_hash") or ""
    bound = bool(bound_hash)
    bound_to_this_device = (bound_hash == device_hash) if device_hash else False

    return JSONResponse({
        "key_masked": mask_key(client_key),
        "expires": exp,
        "days_left": days_left,
        "bound": bound,
        "bound_to_this_device": bound_to_this_device,
        "last_used": row.get("last_used")
    }, status_code=200)