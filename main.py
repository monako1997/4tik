import os
import json
import hashlib
import datetime
import subprocess
import tempfile
import threading
import requests
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

# ============================
# إعدادات JSONBin
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
# دوال التخزين
# ============================
def load_db():
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
                row.setdefault("device_name", None)
                row.setdefault("last_used", None)
                row.setdefault("device_hash", "")
                row.setdefault("activated_on", None)
                row.setdefault("country", None)
            return data
        return []

def save_db(data):
    with DB_LOCK:
        payload = json.dumps(data, ensure_ascii=False)
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

def ensure_bound_or_bind(db, row, device: str, device_name: str | None):
    dev_hash = hash_device(device) if device else ""
    if not row.get("device_hash"):
        row["device_hash"] = dev_hash
        row["device_name"] = device_name
        save_db(db)
        return True
    if dev_hash and row["device_hash"] != dev_hash:
        return False
    return True

def calc_expiry(activated_on_str: str | None, duration_days: int):
    if not activated_on_str:
        return None
    activated_on = datetime.datetime.fromisoformat(activated_on_str)
    return activated_on + datetime.timedelta(days=duration_days)

def get_country_from_ip(ip: str) -> str | None:
    try:
        r = requests.get(f"https://ipapi.co/{ip}/country_name/", timeout=3)
        if r.status_code == 200:
            return r.text.strip()
    except:
        pass
    return None

# ============================
# تهيئة أولية
# ============================
def init_keys():
    db = load_db()
    if db:
        return
    keys = [
        {"key": "A1B2C3D4", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None, "country": None},
        {"key": "E5F6G7H8", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None, "country": None},
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

@app.get("/me")
def me(request: Request):
    key = request.headers.get("X-KEY")
    device = request.headers.get("X-DEVICE") or ""
    device_name = request.headers.get("X-DEVICE-NAME") or None

    if not key:
        raise HTTPException(401, "المفتاح مطلوب")

    db = load_db()
    row = find_key(db, key)
    if not row:
        raise HTTPException(401, "المفتاح غير صحيح")

    if not ensure_bound_or_bind(db, row, device, device_name):
        raise HTTPException(403, "هذا المفتاح مربوط بجهاز آخر")

    expires_on = calc_expiry(row.get("activated_on"), row.get("duration_days", 30))
    now = datetime.datetime.utcnow()
    days_left = max(0, (expires_on - now).days) if expires_on else 0

    return {
        "key": row["key"],
        "device_name": row.get("device_name"),
        "activated_on": row.get("activated_on"),
        "expires_on": expires_on.isoformat() if expires_on else None,
        "days_left": days_left,
        "valid": (now < expires_on) if expires_on else True,
        "country": row.get("country") or "—",
        "last_used": row.get("last_used"),
        "bound": True,
        "bound_to_this_device": True
    }

@app.post("/process")
async def process_video(request: Request, file: UploadFile = File(...)):
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

    # ✅ أول مرة يستخدم المفتاح
    if not row.get("activated_on"):
        row["activated_on"] = now_iso()
        client_ip = request.headers.get("X-Forwarded-For", request.client.host)
        row["country"] = get_country_from_ip(client_ip) or "—"

    row["last_used"] = now_iso()
    save_db(db)

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
        # 👇 عشان يطبع أي خطأ بدل ما يعلق
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(result.stderr)

        # 👇 إرجاع الملف بطريقة مضمونة
        return StreamingResponse(open(tmp_out_path, "rb"), media_type="video/mp4", headers={
            "Content-Disposition": f"attachment; filename=processed{suffix}"
        })

    except Exception as e:
        raise HTTPException(500, f"خطأ في المعالجة: {str(e)}")