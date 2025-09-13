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
            [span_0](start_span)return [][span_0](end_span)
        try:
            r.raise_for_status()
        except:
            [span_1](start_span)return [][span_1](end_span)
        body = r.json()
        data = body.get("record")
        if isinstance(data, list):
            for row in data:
                [span_2](start_span)if "device_name" not in row:[span_2](end_span)
                    row["device_name"] = None
            return data
        if isinstance(data, dict) and "subs" in data:
            out = []
            for k, v in data["subs"].items():
                [span_3](start_span)out.append({[span_3](end_span)
                    "key": k,
                    "duration_days": v.get("duration_days", 30),
                    "activated_on": v.get("activated_on"),
                    "device_hash": v.get("device_hash", ""),
                    [span_4](start_span)"device_name": v.get("device_name"),[span_4](end_span)
                    "last_used": v.get("last_used")
                })
            return out
        [span_5](start_span)return [][span_5](end_span)

def save_db(data):
    """حفظ قاعدة البيانات في JSONBin"""
    with DB_LOCK:
        payload = json.dumps(data, ensure_ascii=False)
        [span_6](start_span)r = _jsonbin_session.put(JSONBIN_BASE, data=payload)[span_6](end_span)
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
            [span_7](start_span)return row[span_7](end_span)
    return None

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
    [span_8](start_span)index_path = BASE_DIR / "index.html"[span_8](end_span)
    if not index_path.exists():
        return HTMLResponse("<h3>index.html غير موجود</h3>", status_code=404)
    return index_path.read_text(encoding="utf-8")

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/subscribe")
def add_subscription(
    key: str = Form(...),
    duration_days: int = Form(30),
    device_info: str = Form("unknown"),
    device_name: str = Form(None)
):
    db = load_db()
    if find_key(db, key):
        [span_9](start_span)raise HTTPException(400, "المفتاح موجود بالفعل")[span_9](end_span)

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
    [span_10](start_span)db = load_db()[span_10](end_span)
    row = find_key(db, key)
    if not row:
        raise HTTPException(404, "المفتاح غير موجود")

    device_hash = hash_device(device_info)
    if row["device_hash"] and row["device_hash"] != device_hash:
        raise HTTPException(403, "هذا المفتاح مستخدم على جهاز آخر")

    activated_on = datetime.datetime.fromisoformat(row["activated_on"])
    now = datetime.datetime.utcnow()
    
    # --- بداية التعديل على منطق الوقت ---
    initial_expires = activated_on + datetime.timedelta(days=row["duration_days"])
    expires_on = initial_expires.replace(hour=23, minute=59, second=59, microsecond=999999)
    # --- نهاية التعديل ---

    row["last_used"] = now.isoformat()
    save_db(db)

    return {
        [span_11](start_span)"key": row["key"],[span_11](end_span)
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

    [span_12](start_span)db = load_db()[span_12](end_span)
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
        [span_13](start_span)save_db(db)[span_13](end_span)

    activated_on = datetime.datetime.fromisoformat(row["activated_on"])
    now          = datetime.datetime.utcnow()

    # --- بداية التعديل على منطق الوقت ---
    initial_expires = activated_on + datetime.timedelta(days=row["duration_days"])
    expires_on = initial_expires.replace(hour=23, minute=59, second=59, microsecond=999999)
    # --- نهاية التعديل ---
    
    days_left    = max(0, (expires_on - now).days)
    bound_to_this = (row.get("device_hash") == dev_hash) if dev_hash else False

    return {
        "key_masked": row["key"][:4] + "****" + row["key"][-4:] if len(row["key"]) >= 8 else row["key"],
        "expires": expires_on.isoformat(),
        "days_left": days_left,
        [span_14](start_span)"bound": True,[span_14](end_span)
        "bound_to_this_device": bound_to_this,
        "device_name": row.get("device_name"),
        "last_used": row.get("last_used")
    }

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
    [span_15](start_span)"""[span_15](end_span)
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
                [span_16](start_span)activated_dt = parse_exp(activated_on)[span_16](end_span)
                duration = timedelta(days=key_data.get("duration_days", 30))

                # --- بداية التعديل على منطق الوقت ---
                initial_expires = activated_dt + duration
                expires_dt = initial_expires.replace(hour=23, minute=59, second=59, microsecond=999999)
                # --- نهاية التعديل ---

                expires_str = expires_dt.strftime("%Y-%m-%d %H:%M")

                if utcnow() > expires_dt:
                    [span_17](start_span)status = "Expired" # English status[span_17](end_span)
                    days_left = 0
                else:
                    status = "Active" # English status
                    [span_18](start_span)days_left = (expires_dt - utcnow()).days[span_18](end_span)
            except Exception:
                status = "Invalid Date"

        key_info = {
            "key": key_data.get("key"),
            "status": status,
            [span_19](start_span)"device_name": key_data.get("device_name", "—"),[span_19](end_span)
            "expires_on": expires_str,
            "days_left": days_left
        }

        if status == "Active":
            active_keys.append(key_info)
        else:
            [span_20](start_span)inactive_keys.append(key_info)[span_20](end_span)
    
    active_keys.sort(key=lambda x: x['days_left'])
    
    return JSONResponse(content={
        "active_keys": active_keys,
        "inactive_keys": inactive_keys
    })
