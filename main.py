import os
import json
import hashlib
import datetime
import subprocess
import tempfile
import threading
import requests
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

# ============================
# إعدادات JSONBin (من Environment)
# ============================
JSONBIN_ID = os.environ.get("JSONBIN_ID")
JSONBIN_KEY = os.environ.get("JSONBIN_KEY")
JSONBIN_BASE = f"https://api.jsonbin.io/v3/b/{JSONBIN_ID}"

_jsonbin_session = requests.Session()
_jsonbin_session.headers.update({
    "X-Master-Key": JSONBIN_KEY,
    "Content-Type": "application/json"
})

DB_LOCK = threading.Lock()

# ============================
# دوال التخزين على JSONBin
# ============================
def load_db():
    """تحميل قاعدة البيانات من JSONBin: قائمة عناصر"""
    with DB_LOCK:
        r = _jsonbin_session.get(JSONBIN_BASE)
        if r.status_code == 404:
            return []
        try:
            r.raise_for_status()
        except:
            return []
        body = r.json()
        data = body.get("record")
        if isinstance(data, list):
            # تطبيع الحقول
            for row in data:
                row.setdefault("device_name", None)
                row.setdefault("last_used", None)
                row.setdefault("device_hash", "")
                row.setdefault("activated_on", None)
            return data
        if isinstance(data, dict) and "subs" in data:
            out = []
            for k, v in data["subs"].items():
                out.append({
                    "key": k,
                    "duration_days": v.get("duration_days", 30),
                    "activated_on": v.get("activated_on"),
                    "device_hash": v.get("device_hash", ""),
                    "device_name": v.get("device_name"),
                    "last_used": v.get("last_used")
                })
            return out
        return []

def save_db(data):
    """حفظ قاعدة البيانات في JSONBin: قائمة عناصر"""
    with DB_LOCK:
        # ✨✨ هذا هو السطر الذي تم تصحيحه ✨✨
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        r = _jsonbin_session.put(JSONBIN_BASE, data=payload)
        r.raise_for_status()

# ============================
# أدوات مساعدة
# ============================
def now_iso():
    return datetime.datetime.utcnow().isoformat()

def hash_device(device_info: str) -> str:
    return hashlib.sha256((device_info or "").encode()).hexdigest()

def find_key(db, key: str):
    for row in db:
        if row.get("key") == key:
            return row
    return None

def find_by_device(db, device_hash: str):
    for row in db:
        if row.get("device_hash") == device_hash:
            return row
    return None

def ensure_bound_or_bind(db, row, device: str, device_name: str | None):
    """
    يربط المفتاح بالجهاز لأول استخدام،
    وإن لم يكن مفعّلاً بعد (activated_on=None) يعيّنه الآن.
    يرفض إن كان جهاز مختلف لاحقًا.
    """
    dev_hash = hash_device(device) if device else ""
    if not row.get("device_hash"):
        row["device_hash"] = dev_hash
        row["device_name"] = device_name
        if not row.get("activated_on"):
            row["activated_on"] = now_iso()
        save_db(db)
        return True
    if dev_hash and row["device_hash"] != dev_hash:
        return False
    if not row.get("activated_on"):
        row["activated_on"] = now_iso()
        save_db(db)
    return True

def calc_expiry(activated_on_str: str | None, duration_days: int):
    if not activated_on_str:
        return None
    activated_on = datetime.datetime.fromisoformat(activated_on_str)
    return activated_on + datetime.timedelta(days=duration_days)

# ============================
# تهيئة مفاتيح أولية (مرة واحدة فقط)
# ============================
def init_keys():
    db = load_db()
    if db:
        return
    keys = [
        {"key": "A1B2C3D4", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user1", "last_used": None},
        {"key": "E5F6G7H8", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user2", "last_used": None},
        {"key": "I9J0K1L2", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user3", "last_used": None},
        {"key": "M3N4O5P6", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user4", "last_used": None},
        {"key": "Q7R8S9T0", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user5", "last_used": None},
    ]
    save_db(keys)
    print("✅ تم إدخال مفاتيح أولية في JSONBin")

init_keys()

# ============================
# إعداد التطبيق
# ============================
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
BASE_DIR = Path(__file__).resolve().parent

# ============================
# المسارات
# ============================
@app.get("/", response_class=HTMLResponse)
def home():
    index_path = BASE_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h3>index.html غير موجود</h3>", status_code=404)
    return index_path.read_text(encoding="utf-8")

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/debug-subs")
def debug_subs():
    db = load_db()
    return {"count": len(db), "subs": db[:5]}

@app.post("/subscribe")
def add_subscription(
    key: str = Form(...),
    duration_days: int = Form(30),
    device_info: str = Form(""),
    device_name: str = Form(None)
):
    db = load_db()
    if find_key(db, key):
        raise HTTPException(400, "المفتاح موجود بالفعل")

    row = {
        "key": key,
        "duration_days": duration_days,
        "activated_on": None,
        "device_hash": "",
        "device_name": device_name,
        "last_used": None
    }

    if device_info:
        row["device_hash"] = hash_device(device_info)
        row["activated_on"] = now_iso()

    db.append(row)
    save_db(db)
    return {"message": f"تمت إضافة الاشتراك {key}"}

@app.get("/check/{key}")
def check_subscription(key: str, request: Request):
    device = request.query_params.get("device_info") or request.headers.get("X-DEVICE") or ""
    device_name = request.headers.get("X-DEVICE-NAME") or None

    db = load_db()
    row = find_key(db, key)
    if not row:
        raise HTTPException(404, "المفتاح غير موجود")

    if not ensure_bound_or_bind(db, row, device, device_name):
        raise HTTPException(403, "هذا المفتاح مربوط بجهاز آخر")

    expires_on = calc_expiry(row.get("activated_on"), row.get("duration_days", 30))
    now = datetime.datetime.utcnow()
    days_left = max(0, (expires_on - now).days) if expires_on else 0

    row["last_used"] = now_iso()
    save_db(db)

    return {
        "key": row["key"],
        "device_name": row.get("device_name"),
        "activated_on": row.get("activated_on"),
        "expires_on": expires_on.isoformat() if expires_on else None,
        "days_left": days_left,
        "valid": (now < expires_on) if expires_on else True
    }

# --- ✨✨ المسار التشخيصي الجديد ✨✨ ---
@app.get("/debug-key/{key}")
def debug_key_info(key: str):
    db = load_db()
    row = find_key(db, key)
    
    if not row:
        return {"error": "لم يتم العثور على المفتاح في قاعدة البيانات."}

    # --- معلومات من وجهة نظر الخادم ---
    server_now_utc = datetime.datetime.utcnow()
    activated_on_str = row.get("activated_on")
    duration_days = row.get("duration_days", 30)
    
    expires_on = None
    is_expired = None
    
    if activated_on_str:
        try:
            activated_on_dt = datetime.datetime.fromisoformat(activated_on_str)
            expires_on = activated_on_dt + datetime.timedelta(days=duration_days)
            is_expired = server_now_utc >= expires_on
        except (ValueError, TypeError):
            # This handles cases where activated_on might be in a wrong format
            expires_on = "خطأ في الحساب"
            is_expired = "خطأ في الحساب"
    
    return {
        "1_server_time": {
            "current_utc_time": server_now_utc.isoformat(),
            "comment": "هذا هو الوقت الحالي على الخادم. قارنه بالوقت الفعلي."
        },
        "2_key_data_from_db": {
            "key": row.get("key"),
            "activated_on": activated_on_str,
            "duration_days": duration_days,
            "comment": "هذه هي البيانات التي يقرأها الخادم من قاعدة البيانات."
        },
        "3_expiry_calculation": {
            "expires_on_utc": expires_on.isoformat() if isinstance(expires_on, datetime.datetime) else str(expires_on),
            "is_expired_according_to_server": is_expired,
            "comment": "بناءً على ما سبق، هل يعتقد الخادم أن المفتاح منتهي الصلاحية؟"
        }
    }

@app.get("/me")
def me(request: Request):
    key = request.headers.get("X-KEY")
    device = request.headers.get("X-DEVICE") or ""
    device_name = request.headers.get("X-DEVICE-NAME") or None

    db = load_db()
    row = None
    if key:
        row = find_key(db, key)
    elif device:
        row = find_by_device(db, hash_device(device))

    if not row:
        return JSONResponse({"error": "لا يوجد اشتراك"}, status_code=401)

    if not ensure_bound_or_bind(db, row, device, device_name):
        return JSONResponse({"error": "هذا المفتاح مربوط بجهاز آخر"}, status_code=403)

    expires_on = calc_expiry(row.get("activated_on"), row.get("duration_days", 30))
    now = datetime.datetime.utcnow()

    # التحقق من انتهاء الصلاحية هنا أيضاً لمنع الدخول للتطبيق بمفتاح منته
    if expires_on and now >= expires_on:
        return JSONResponse({"error": "انتهت صلاحية اشتراكك"}, status_code=403)

    days_left = max(0, (expires_on - now).days) if expires_on else 30

    row["last_used"] = now_iso()
    save_db(db)

    dev_hash = hash_device(device) if device else ""
    bound_to_this = (row.get("device_hash") == dev_hash) if dev_hash else False

    return {
        "key_masked": row["key"][:4] + "****" + row["key"][-4:] if len(row["key"]) >= 8 else row["key"],
        "activated_on": row.get("activated_on"),
        "expires": expires_on.isoformat() if expires_on else None,
        "days_left": days_left,
        "bound": True,
        "bound_to_this_device": bound_to_this,
        "device_name": row.get("device_name"),
        "last_used": row.get("last_used")
    }

@app.post("/process")
async def process_video(request: Request, file: UploadFile = File(...)):
    MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB in bytes
    content_length = request.headers.get("content-length")

    if not content_length:
        raise HTTPException(status_code=411, detail="خطأ: لم يتم تحديد حجم الملف في الطلب.")
    
    file_size = int(content_length)

    if file_size > MAX_FILE_SIZE:
        file_size_mb = file_size / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"الملف أكبر من الحجم المسموح به. حجم الملف: {file_size_mb:.2f} MB، الحد الأقصى: 200 MB."
        )

    key = request.headers.get("X-KEY")
    device = request.headers.get("X-DEVICE") or ""
    device_name = request.headers.get("X-DEVICE-NAME") or None
    if not key or not device:
        raise HTTPException(401, "المفتاح والجهاز مطلوبان")

    db = load_db()
    row = find_key(db, key)
    if not row:
        raise HTTPException(401, "المفتاح غير صحيح")

    if not ensure_bound_or_bind(db, row, device, device_name):
        raise HTTPException(403, "هذا المفتاح مربوط بجهاز آخر")

    expires_on = calc_expiry(row.get("activated_on"), row.get("duration_days", 30))
    now = datetime.datetime.utcnow()
    if not expires_on or now >= expires_on:
        raise HTTPException(403, "⛔ انتهت صلاحية هذا المفتاح")

    row["last_used"] = now_iso()
    save_db(db)

    try:
        suffix = os.path.splitext(file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_in:
            contents = await file.read()
            tmp_in.write(contents)
            tmp_in_path = tmp_in.name

        tmp_out_path = tmp_in_path.replace(suffix, f"_out{suffix}")

        cmd = [
            "ffmpeg", "-itsscale", "2",
            "-i", tmp_in_path,
            "-c:v", "copy", "-c:a", "copy",
            tmp_out_path
        ]
        subprocess.run(cmd, check=True)

        return FileResponse(tmp_out_path, filename=f"processed{suffix}")

    except Exception as e:
        raise HTTPException(500, f"خطأ في المعالجة: {str(e)}")
