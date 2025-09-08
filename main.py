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
                # قد تكون None ليبدأ العد من أول استخدام
                row.setdefault("activated_on", None)
            return data
        if isinstance(data, dict) and "subs" in data:
            # تحويل شكل قديم dict -> list
            out = []
            for k, v in data["subs"].items():
                out.append({
                    "key": k,
                    "duration_days": v.get("duration_days", 30),
                    "activated_on": v.get("activated_on"),  # قد تكون None
                    "device_hash": v.get("device_hash", ""),
                    "device_name": v.get("device_name"),
                    "last_used": v.get("last_used")
                })
            return out
        return []

def save_db(data):
    """حفظ قاعدة البيانات في JSONBin: قائمة عناصر"""
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
    # غير مربوط: اربطه الآن واعتبر هذا أول استخدام -> فعل الاشتراك
    if not row.get("device_hash"):
        row["device_hash"] = dev_hash
        row["device_name"] = device_name
        if not row.get("activated_on"):
            row["activated_on"] = now_iso()  # يبدأ العد 30 يوم من الآن
        save_db(db)
        return True
    # مربوط: لو جهاز مختلف ارفض
    if dev_hash and row["device_hash"] != dev_hash:
        return False
    # مربوط بنفس الجهاز: لو لم يُفعّل بعد لأي سبب، فعّله الآن
    if not row.get("activated_on"):
        row["activated_on"] = now_iso()
        save_db(db)
    return True

def calc_expiry(activated_on_str: str | None, duration_days: int):
    """
    إن لم يكن مفعّلاً بعد (activated_on=None) نُرجع None للانتهاء.
    """
    if not activated_on_str:
        return None
    activated_on = datetime.datetime.fromisoformat(activated_on_str)
    return activated_on + datetime.timedelta(days=duration_days)

# ============================
# تهيئة مفاتيح أولية (مرة واحدة فقط)
# (activated_on=None كي يبدأ العد من أول استخدام)
# ============================
def init_keys():
    db = load_db()
    if db:  # لو فيه بيانات قديمة ما نضيف
        return
    keys = [
        {"key": "A1B2C3D4", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user1", "last_used": None},
        {"key": "E5F6G7H8", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user2", "last_used": None},
        {"key": "I9J0K1L2", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user3", "last_used": None},
        {"key": "M3N4O5P6", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user4", "last_used": None},
        {"key": "Q7R8S9T0", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user5", "last_used": None},
        {"key": "U1V2W3X4", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user6", "last_used": None},
        {"key": "Y5Z6A7B8", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user7", "last_used": None},
        {"key": "C9D0E1F2", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user8", "last_used": None},
        {"key": "G3H4I5J6", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user9", "last_used": None},
        {"key": "K7L8M9N0", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user10", "last_used": None},
        {"key": "O1P2Q3R4", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user11", "last_used": None},
        {"key": "S5T6U7V8", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user12", "last_used": None},
        {"key": "W9X0Y1Z2", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user13", "last_used": None},
        {"key": "A3B4C5D6", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user14", "last_used": None},
        {"key": "E7F8G9H0", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user15", "last_used": None},
        {"key": "I1J2K3L4", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user16", "last_used": None},
        {"key": "M5N6O7P8", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user17", "last_used": None},
        {"key": "Q9R0S1T2", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user18", "last_used": None},
        {"key": "U3V4W5X6", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user19", "last_used": None},
        {"key": "Y7Z8A9B0", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": "user20", "last_used": None}
    ]
    save_db(keys)
    print("✅ تم إدخال 20 مفتاح أولية (التفعيل عند أول استخدام) في JSONBin")

# نفّذ التهيئة عند بدء التشغيل
init_keys()

# ============================
# إعداد التطبيق
# ============================
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # خصّصيها لدومينك لاحقًا لو حبيتي
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
    device_info: str = Form(""),     # OPTIONAL: إن أردتِ ربطه فورًا
    device_name: str = Form(None)
):
    db = load_db()
    if find_key(db, key):
        raise HTTPException(400, "المفتاح موجود بالفعل")

    row = {
        "key": key,
        "duration_days": duration_days,
        "activated_on": None,              # لا نفعّل الآن — يبدأ عند أول استخدام
        "device_hash": "",                 # لا نربط الآن
        "device_name": device_name,
        "last_used": None
    }

    # لو ربط فوري مطلوب (اختياري)
    if device_info:
        row["device_hash"] = hash_device(device_info)
        row["activated_on"] = now_iso()

    db.append(row)
    save_db(db)
    return {"message": f"تمت إضافة الاشتراك {key}"}

@app.get("/check/{key}")
def check_subscription(key: str, request: Request):
    # يدعم إما query param (device_info) أو header X-DEVICE
    device = request.query_params.get("device_info") or request.headers.get("X-DEVICE") or ""
    device_name = request.headers.get("X-DEVICE-NAME") or None

    db = load_db()
    row = find_key(db, key)
    if not row:
        raise HTTPException(404, "المفتاح غير موجود")

    # اربط أول مرة أو ارفض إن كان جهاز مختلف، وفعّل إن لم يكن مفعّلاً
    if not ensure_bound_or_bind(db, row, device, device_name):
        raise HTTPException(403, "هذا المفتاح مربوط بجهاز آخر")

    # احسب الانتهاء (قد تكون None لو لسبب ما لم يُفعّل)
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
        "valid": (now < expires_on) if expires_on else True  # إذا فعّل للتو يعتبر صالح
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

    if not ensure_bound_or_bind(db, row, device, device_name):
        return JSONResponse({"error": "هذا المفتاح مربوط بجهاز آخر"}, status_code=403)

    expires_on = calc_expiry(row.get("activated_on"), row.get("duration_days", 30))
    now = datetime.datetime.utcnow()
    days_left = max(0, (expires_on - now).days) if expires_on else 30  # إن كان تفعّل الآن تقريبًا 30

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
    """معالجة فيديو مع قفل المفتاح على الجهاز + ffmpeg -itsscale 2"""
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

    # حدّث آخر استخدام
    row["last_used"] = now_iso()
    save_db(db)

    # تنفيذ المعالجة
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