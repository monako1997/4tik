import os
import json
import hashlib
import datetime
import subprocess
import tempfile
import threading
import requests
from pathlib import Path

# استيراد الأدوات اللازمة من FastAPI للحماية والتحقق
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

# ============================
# إعدادات JSONBin والمفتاح السري للمشرف
# ============================
JSONBIN_ID = os.environ.get("JSONBIN_ID")
JSONBIN_KEY = os.environ.get("JSONBIN_KEY")
JSONBIN_BASE = f"https://api.jsonbin.io/v3/b/{JSONBIN_ID}"

ADMIN_SECRET_KEY = os.environ.get("ADMIN_SECRET_KEY")
if not ADMIN_SECRET_KEY:
    raise ValueError("⛔️ خطأ فادح: متغير البيئة ADMIN_SECRET_KEY غير معين. لا يمكن تشغيل التطبيق بأمان.")

_jsonbin_session = requests.Session()
_jsonbin_session.headers.update({
    "X-Master-Key": JSONBIN_KEY,
    "Content-Type": "application/json; charset=utf-8"
})

DB_LOCK = threading.Lock()

# ============================
# دوال التخزين (بدون تغيير)
# ============================
def load_db():
    """تحميل قاعدة البيانات (قائمة المفاتيح) من JSONBin"""
    with DB_LOCK:
        r = _jsonbin_session.get(JSONBIN_BASE)
        if r.status_code == 404: return []
        try:
            r.raise_for_status()
            record = r.json().get("record", [])
            return record if isinstance(record, list) else []
        except Exception:
            return []

def save_db(data):
    """حفظ قاعدة البيانات (قائمة المفاتيح) في JSONBin"""
    with DB_LOCK:
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        r = _jsonbin_session.put(JSONBIN_BASE, data=payload)
        r.raise_for_status()

# ============================
# أدوات مساعدة (بدون تغيير)
# ============================
def now_iso(): return datetime.datetime.utcnow().isoformat()
def hash_device(device_info: str) -> str: return hashlib.sha256((device_info or "").encode()).hexdigest()
def find_key(db, key: str):
    for row in db:
        if row.get("key") == key: return row
    return None
def calc_expiry(activated_on_str: str | None, duration_days: int):
    if not activated_on_str: return None
    activated_on = datetime.datetime.fromisoformat(activated_on_str)
    return activated_on + datetime.timedelta(days=duration_days)
def ensure_bound_or_bind(db, row, device: str, device_name: str | None):
    dev_hash = hash_device(device) if device else ""
    if not row.get("device_hash"):
        row["device_hash"] = dev_hash
        row["device_name"] = device_name
        if not row.get("activated_on"): row["activated_on"] = now_iso()
        save_db(db)
        return True
    return row["device_hash"] == dev_hash

# ============================
# إعداد التطبيق (بدون تغيير)
# ============================
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ============================
# آلية التحقق من صلاحيات المشرف (Admin)
# ============================
async def verify_admin_key(admin_key: str = Header(..., alias="X-Admin-Key")):
    if admin_key != ADMIN_SECRET_KEY:
        raise HTTPException(status_code=403, detail="غير مصرح لك بالقيام بهذه العملية")

# ============================
# المسارات (Endpoints)
# ============================
# 🔒 مسار محمي للمشرف
@app.post("/subscribe", dependencies=[Depends(verify_admin_key)])
async def add_subscription(key: str = Form(...), duration_days: int = Form(30)):
    db = load_db()
    if find_key(db, key):
        raise HTTPException(400, "المفتاح موجود بالفعل")
    row = {"key": key, "duration_days": duration_days, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None}
    db.append(row)
    save_db(db)
    return {"message": f"تمت إضافة الاشتراك {key} بنجاح"}

# ✨✨✨ المسار المعدل الذي يحل المشكلة ✨✨✨
@app.get("/me")
async def me(request: Request):
    key = request.headers.get("X-KEY")
    device = request.headers.get("X-DEVICE") or ""
    device_name = request.headers.get("X-DEVICE-NAME") or None
    
    if not key:
        return JSONResponse({"error": "المفتاح مطلوب"}, status_code=401)
        
    db = load_db()
    row = find_key(db, key)
    
    if not row:
        return JSONResponse({"error": "لا يوجد اشتراك بهذا المفتاح"}, status_code=401)
    
    if not ensure_bound_or_bind(db, row, device, device_name):
        return JSONResponse({"error": "هذا المفتاح مربوط بجهاز آخر"}, status_code=403)
    
    expires_on = calc_expiry(row.get("activated_on"), row.get("duration_days", 30))
    now = datetime.datetime.utcnow()
    
    if expires_on and now >= expires_on:
        return JSONResponse({
            "error": "انتهت صلاحية اشتراكك",
            "key": row.get("key"),
            "valid": False,
            "expires_on": expires_on.isoformat() if expires_on else None,
            "days_left": 0
        }, status_code=403)
        
    days_left = max(0, (expires_on - now).days) if expires_on else row.get("duration_days", 30)
    
    row["last_used"] = now_iso()
    save_db(db)
    
    return {
        "key_masked": row["key"][:4] + "****",
        "device_name": row.get("device_name"),
        "activated_on": row.get("activated_on"),
        "expires_on": expires_on.isoformat() if expires_on else None,
        "days_left": days_left,
        "valid": True
    }

@app.post("/process")
async def process_video(request: Request):
    key = request.headers.get("X-KEY")
    device = request.headers.get("X-DEVICE") or ""
    if not key or not device:
        raise HTTPException(401, "المفتاح والجهاز مطلوبان")

    db = load_db()
    row = find_key(db, key)

    if not row:
        raise HTTPException(401, "المفتاح غير صحيح")

    if not ensure_bound_or_bind(db, row, device, None):
        raise HTTPException(403, "هذا المفتاح مربوط بجهاز آخر")

    expires_on = calc_expiry(row.get("activated_on"), row.get("duration_days", 30))
    now = datetime.datetime.utcnow()
    
    if not expires_on or now >= expires_on:
        raise HTTPException(403, "⛔ انتهت صلاحية هذا المفتاح")
        
    row["last_used"] = now_iso()
    save_db(db)
    
    return {"message": "تم التحقق بنجاح، وجاري معالجة الفيديو..."}

