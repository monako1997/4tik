import os
import json
import hashlib
import datetime
import subprocess
import tempfile
import threading
import requests

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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
        if row["device_hash"] == device_hash:
            return row
    return None

# ======================================================
# إعداد التطبيق
# ======================================================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # عدليها لاحقاً لدومينك فقط
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================================================
# المسارات
# ======================================================

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
    existing = find_key(db, key)
    if existing:
        raise HTTPException(400, "المفتاح مستخدم بالفعل")

    device_hash = hash_device(device_info)
    now = datetime.datetime.utcnow().isoformat()

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
        "valid": now < expires_on
    }

@app.post("/process")
async def process_video(file: UploadFile = File(...)):
    """معالجة فيديو باستخدام FFmpeg مع itsscale 2"""
    try:
        suffix = os.path.splitext(file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_in:
            tmp_in.write(await file.read())
            tmp_in_path = tmp_in.name

        tmp_out_path = tmp_in_path.replace(suffix, f"_out{suffix}")

        # هنا أمر ffmpeg مثل كودك القديم
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