import os, json, threading, subprocess, uuid
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# ================= إعداد المجلدات =================
BASE = Path(__file__).resolve().parent

# مجلد التخزين الدائم (للمفاتيح)
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ملف المفاتيح داخل التخزين الدائم
DB_PATH = DATA_DIR / "keys.json"
DB_LOCK = threading.Lock()

# مجلد عمل مؤقت للفيديوهات
WORK = BASE / "work"
WORK.mkdir(exist_ok=True)

# لو فيه نسخة قديمة من keys.json بجانب الكود → انسخها أول مرة
LEGACY_DB = BASE / "keys.json"
if (not DB_PATH.exists()) and LEGACY_DB.exists():
    try:
        DB_PATH.write_text(LEGACY_DB.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        pass

# ================= أدوات قراءة/حفظ المفاتيح =================
def load_db():
    if not DB_PATH.exists():
        DB_PATH.write_text("[]", encoding="utf-8")
    try:
        return json.loads(DB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_db(data):
    with DB_LOCK:
        tmp = DB_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(DB_PATH)

def utcnow():
    return datetime.now(timezone.utc)

# ================= FastAPI =================
app = FastAPI()

# تقديم الملفات الثابتة (index.html, manifest.json, icons…)
app.mount("/", StaticFiles(directory=BASE, html=True), name="static")

# ================= التحقق من المفتاح =================
def verify_key(key: str, device: str):
    db = load_db()
    for row in db:
        if row["key"] == key:
            exp = datetime.fromisoformat(row["expires"].replace("Z", "+00:00"))
            if utcnow() > exp:
                return False, "انتهت صلاحية الاشتراك"
            if not row.get("device_hash"):
                row["device_hash"] = device
                row["last_used"] = utcnow().isoformat()
                save_db(db)
                return True, "تم الربط بنجاح"
            if row["device_hash"] != device:
                return False, "المفتاح مربوط بجهاز آخر"
            row["last_used"] = utcnow().isoformat()
            save_db(db)
            return True, "صالح"
    return False, "مفتاح غير صحيح"

# ================= المسارات =================
@app.post("/process")
async def process(request: Request, file: UploadFile):
    key = request.headers.get("X-KEY")
    device = request.headers.get("X-DEVICE")

    if not device:
        return JSONResponse({"error": "بصمة الجهاز مفقودة"}, status_code=400)

    if key:
        ok, msg = verify_key(key, device)
        if not ok:
            return JSONResponse({"error": msg}, status_code=401)
    else:
        # في حال الجهاز معروف مسبقاً
        db = load_db()
        found = False
        for row in db:
            if row.get("device_hash") == device:
                found = True
                row["last_used"] = utcnow().isoformat()
                save_db(db)
        if not found:
            return JSONResponse({"error": "المفتاح مطلوب"}, status_code=401)

    # تحقق من الحجم (100 MB كحد أقصى)
    size = 0
    tmp_in = WORK / f"in-{uuid.uuid4().hex}.mp4"
    with tmp_in.open("wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk: break
            size += len(chunk)
            if size > 100 * 1024 * 1024:
                f.close()
                tmp_in.unlink(missing_ok=True)
                return JSONResponse({"error": "الملف يتجاوز 100MB"}, status_code=400)
            f.write(chunk)

    tmp_out = WORK / f"out-{uuid.uuid4().hex}.mp4"

    # تطبيق ffmpeg
    cmd = ["ffmpeg", "-y", "-itsscale", "2", "-i", str(tmp_in),
           "-c:v", "copy", "-c:a", "copy", str(tmp_out)]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        return JSONResponse({"error": "فشل المعالجة"}, status_code=500)
    finally:
        tmp_in.unlink(missing_ok=True)

    return FileResponse(tmp_out, filename="output.mp4")

@app.post("/check")
async def check(request: Request):
    device = request.headers.get("X-DEVICE")
    if not device:
        return JSONResponse({"error": "X-DEVICE مفقود"}, status_code=400)
    db = load_db()
    for row in db:
        if row.get("device_hash") == device:
            return {"ok": True}
    return JSONResponse({"error": "غير معروف"}, status_code=404)

@app.get("/me")
async def me(request: Request):
    key = request.headers.get("X-KEY")
    device = request.headers.get("X-DEVICE")
    db = load_db()
    for row in db:
        if (key and row["key"] == key) or (not key and row.get("device_hash") == device):
            exp = datetime.fromisoformat(row["expires"].replace("Z", "+00:00"))
            days_left = (exp - utcnow()).days
            return {
                "key_masked": row["key"][:4] + "****" + row["key"][-4:],
                "expires": row["expires"],
                "days_left": days_left,
                "bound": bool(row.get("device_hash")),
                "bound_to_this_device": row.get("device_hash") == device,
                "last_used": row.get("last_used")
            }
    return JSONResponse({"error": "غير موجود"}, status_code=404)