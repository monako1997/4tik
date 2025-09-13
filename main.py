import os
import json
import hashlib
import datetime
import subprocess
import tempfile
import threading
import requests
from pathlib import Path
from datetime import timedelta, timezone

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

# ======================================================
# إعدادات JSONBin
# ======================================================
JSONBIN_ID = os.environ.get("JSONBIN_ID")
JSONBIN_KEY = os.environ.get("JSONBIN_KEY")
JSONBIN_BASE = f"https://api.jsonbin.io/v3/b/{JSONBIN_ID}"

_jsonbin_session = requests.Session()
_jsonbin_session.headers.update({
    "X-Master-Key": JSONBIN_KEY,
    "Content-Type": "application/json"
})

DB_LOCK = threading.Lock()

def load_db():
    """تحميل قاعدة البيانات من JSONBin"""
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
            for row in data:
                if "device_name" not in row:
                    row["device_name"] = None
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
    """حفظ قاعدة البيانات في JSONBin"""
    with DB_LOCK:
        payload = json.dumps(data, ensure_ascii=False)
        r = _jsonbin_session.put(JSONBIN_BASE, data=payload)
        r.raise_for_status()

# ======================================================
# أدوات مساعدة
# ======================================================
def hash_device(device_info: str) -> str:
    return hashlib.sha256(device_info.encode()).hexdigest()

def find_key(db, key: str):
    for row in db:
        if row["key"] == key:
            return row
    return None

def find_by_device(db, device_hash: str):
    for row in db:
        if row.get("device_hash") == device_hash:
            return row
    return None

# ======================================================
# تهيئة مفاتيح أولية (20 مفتاح)
# ======================================================
def init_keys():
    db = load_db()
    if db:  # لو فيه بيانات قديمة ما نضيف
        return

    now = datetime.datetime.utcnow().isoformat()
    keys = [
        {"key": "A1B2C3D4", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user1", "last_used": None},
        {"key": "E5F6G7H8", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user2", "last_used": None},
        {"key": "I9J0K1L2", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user3", "last_used": None},
        {"key": "M3N4O5P6", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user4", "last_used": None},
        {"key": "Q7R8S9T0", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user5", "last_used": None},
        {"key": "U1V2W3X4", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user6", "last_used": None},
        {"key": "Y5Z6A7B8", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user7", "last_used": None},
        {"key": "C9D0E1F2", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user8", "last_used": None},
        {"key": "G3H4I5J6", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user9", "last_used": None},
        {"key": "K7L8M9N0", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user10", "last_used": None},
        {"key": "O1P2Q3R4", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user11", "last_used": None},
        {"key": "S5T6U7V8", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user12", "last_used": None},
        {"key": "W9X0Y1Z2", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user13", "last_used": None},
        {"key": "A3B4C5D6", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user14", "last_used": None},
        {"key": "E7F8G9H0", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user15", "last_used": None},
        {"key": "I1J2K3L4", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user16", "last_used": None},
        {"key": "M5N6O7P8", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user17", "last_used": None},
        {"key": "Q9R0S1T2", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user18", "last_used": None},
        {"key": "U3V4W5X6", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user19", "last_used": None},
        {"key": "Y7Z8A9B0", "duration_days": 30, "activated_on": now, "device_hash": "", "device_name": "user20", "last_used": None}
    ]
    save_db(keys)
    print("✅ تم إدخال 20 مفتاح أولية في JSONBin")

# استدعاء التهيئة
# init_keys() # You might want to comment this out after the first run

# ======================================================
# إعداد التطبيق
# ======================================================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent

# ======================================================
# المسارات
# ======================================================

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
    device_info: str = Form("unknown"),
    device_name: str = Form(None)
):
    db = load_db()
    if find_key(db, key):
        raise HTTPException(400, "المفتاح موجود بالفعل")

    now = datetime.datetime.utcnow().isoformat()
    device_hash = hash_device(device_info)

    db.append({
        "key": key,
        "duration_days": duration_days,
        "activated_on": now,
        "device_hash": device_hash,
        "device_name": device_name,
        "last_used": None
    })
    save_db(db)
    return {"message": f"تمت إضافة الاشتراك {key}"}

@app.get("/check/{key}")
def check_subscription(key: str, device_info: str = "unknown"):
    db = load_db()
    row = find_key(db, key)
    if not row:
        raise HTTPException(404, "المفتاح غير موجود")

    device_hash = hash_device(device_info)
    if row["device_hash"] and row["device_hash"] != device_hash:
        raise HTTPException(403, "هذا المفتاح مستخدم على جهاز آخر")

    activated_on = datetime.datetime.fromisoformat(row["activated_on"])
    expires_on = activated_on + datetime.timedelta(days=row["duration_days"])
    now = datetime.datetime.utcnow()

    row["last_used"] = now.isoformat()
    save_db(db)

    return {
        "key": row["key"],
        "device_name": row.get("device_name"),
        "activated_on": row["activated_on"],
        "expires_on": expires_on.isoformat(),
        "days_left": max(0, (expires_on - now).days),
        "valid": now < expires_on
    }

@app.get("/me")
def me(request: Request):
    key         = request.headers.get("X-KEY")
    device      = request.headers.get("X-DEVICE") or ""
    device_name = request.headers.get("X-DEVICE-NAME") or None

    db = load_db()
    row = None
    if key:
        row = find_key(db, key)
    elif device:
        row = find_by_device(db, hash_device(device))

    if not row:
        return JSONResponse({"error": "لا يوجد اشتراك"}, status_code=401)

    dev_hash = hash_device(device) if device else ""
    if not row.get("device_hash"):
        row["device_hash"] = dev_hash
        row["device_name"] = device_name
        save_db(db)

    activated_on = datetime.datetime.fromisoformat(row["activated_on"])
    expires_on   = activated_on + datetime.timedelta(days=row["duration_days"])
    now          = datetime.datetime.utcnow()
    days_left    = max(0, (expires_on - now).days)
    bound_to_this = (row.get("device_hash") == dev_hash) if dev_hash else False

    return {
        "key_masked": row["key"][:4] + "****" + row["key"][-4:] if len(row["key"]) >= 8 else row["key"],
        "expires": expires_on.isoformat(),
        "days_left": days_left,
        "bound": True,
        "bound_to_this_device": bound_to_this,
        "device_name": row.get("device_name"),
        "last_used": row.get("last_used")
    }

@app.post("/process")
async def process_video(file: UploadFile = File(...)):
    try:
        suffix = os.path.splitext(file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_in:
            tmp_in.write(await file.read())
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

# =================================================================
# <<< بداية الكود الجديد والمعدل
# =================================================================

def utcnow():
    """ترجع الوقت الحالي بتوقيت UTC مع معلومات المنطقة الزمنية"""
    return datetime.datetime.now(timezone.utc)

def parse_exp(timestamp_str):
    """تحويل التاريخ النصي إلى كائن datetime مع التعامل مع صيغ مختلفة"""
    if timestamp_str.endswith('Z'):
        timestamp_str = timestamp_str[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(timestamp_str)

@app.get("/admin/key_status")
async def get_key_status():
    """
    This admin page displays the status of all keys in the system,
    separated into active and inactive lists.
    """
    all_keys = load_db()
    active_keys = []
    inactive_keys = []

    for key_data in all_keys:
        status = "Not Activated" # English status
        expires_str = "N/A"
        days_left = None
        
        activated_on = key_data.get("activated_on")
        if activated_on:
            try:
                activated_dt = parse_exp(activated_on)
                duration = timedelta(days=key_data.get("duration_days", 30))
                expires_dt = activated_dt + duration
                expires_str = expires_dt.strftime("%Y-%m-%d %H:%M")

                if utcnow() > expires_dt:
                    status = "Expired" # English status
                    days_left = 0
                else:
                    status = "Active" # English status
                    # Calculate remaining days
                    days_left = (expires_dt - utcnow()).days
            except Exception:
                status = "Invalid Date"

        key_info = {
            "key": key_data.get("key"),
            "status": status,
            "device_name": key_data.get("device_name", "—"),
            "expires_on": expires_str,
            "days_left": days_left
        }

        # Separate keys into the correct list
        if status == "Active":
            active_keys.append(key_info)
        else:
            inactive_keys.append(key_info)
    
    # Sort active keys by the soonest to expire
    active_keys.sort(key=lambda x: x['days_left'])
    
    # Return a structured JSON object with two lists
    return JSONResponse(content={
        "active_keys": active_keys,
        "inactive_keys": inactive_keys
    })

# =================================================================
# <<< نهاية الكود
# =================================================================
