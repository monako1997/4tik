import os, uuid, shutil, subprocess, json, threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from math import ceil
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# ==============================================================================
# ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼ إعدادات المفاتيح (القائمة الكاملة) ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼
# ==============================================================================

INITIAL_KEYS = [
  { "key": "4TK-A7B1-C9D2-E3F4", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-G5H6-I7J8-K9L0", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-M1N2-O3P4-Q5R6", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-S7T8-U9V0-W1X2", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-Y3Z4-A5B6-C7D8", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-E9F0-G1H2-I3J4", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-K5L6-M7N8-O9P0", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-Q1R2-S3T4-U5V6", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-W7X8-Y9Z0-A1B2", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-C3D4-E5F6-G7H8", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-I9J0-K1L2-M3N4", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-O5P6-Q7R8-S9T0", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-U1V2-W3X4-Y5Z6", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-A7B8-C9D0-E1F2", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-G3H4-I5J6-K7L8", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-M9N0-O1P2-Q3R4", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-S5T6-U7V8-W9X0", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-Y1Z2-A3B4-C5D6", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-E7F8-G9H0-I1J2", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None },
  { "key": "4TK-K3L4-M5N6-O7P8", "duration_days": 30, "activated_on": None, "device_hash": "", "device_name": None, "last_used": None }
]

# ==============================================================================
# ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲ نهاية إعدادات المفاتيح ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
# ==============================================================================

BASE = Path(__file__).resolve().parent
WORK = BASE / "work"
WORK.mkdir(exist_ok=True)

DB_PATH = Path("/data/database.json")
DB_LOCK = threading.Lock()
MAX_SIZE = 100 * 1024 * 1024

def utcnow(): return datetime.now(timezone.utc)

def load_db():
    with DB_LOCK:
        if not DB_PATH.exists():
            DB_PATH.write_text(json.dumps(INITIAL_KEYS, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            data = json.loads(DB_PATH.read_text(encoding="utf-8"))
            for row in data:
                if "device_name" not in row:
                    row["device_name"] = None
            return data
        except Exception:
            return INITIAL_KEYS

def save_db(data):
    with DB_LOCK:
        DB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def find_key(data, k):
    for row in data:
        if row.get("key") == k: return row
    return None

def find_by_device(data, device_hash):
    for row in data:
        if (row.get("device_hash") or "") == device_hash: return row
    return None

def run_silent(cmd: list[str]) -> bool:
    try:
        p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=False)
        return p.returncode == 0
    except Exception: return False

def mask_key(k: str) -> str:
    if not k: return ""
    if len(k) <= 8: return k
    return k[:4] + "*"*(len(k)-8) + k[-4:]

def parse_exp(exp: str): return datetime.fromisoformat(exp.replace("Z", "+00:00"))

def validate_row(row):
    activated_on = row.get("activated_on")
    if not activated_on: return True, "صالح للتفعيل"
    try:
        activated_dt = parse_exp(activated_on)
        duration = timedelta(days=row.get("duration_days", 30))
        expires_dt = activated_dt + duration
        if utcnow() > expires_dt: return False, "انتهت صلاحية الاشتراك"
        return True, None
    except Exception: return False, "صيغة تاريخ التفعيل غير صالحة"

def bind_if_needed(row, device_hash, device_name, data):
    bound_hash = row.get("device_hash") or ""
    if not bound_hash:
        row["device_hash"] = device_hash
        row["device_name"] = device_name
        if not row.get("activated_on"):
            row["activated_on"] = utcnow().isoformat()
        row["last_used"] = utcnow().isoformat()
        save_db(data)
        return True, "تم تفعيل الاشتراك وربط المفتاح بهذا الجهاز"
    else:
        if bound_hash != device_hash: return False, "هذا المفتاح مربوط بجهاز آخر"
        row["last_used"] = utcnow().isoformat()
        save_db(data)
        return True, "مسموح"

def authorize(client_key: str, device_hash: str, device_name: str):
    if not device_hash: return False, "بصمة الجهاز مطلوبة", None
    data = load_db()
    if client_key:
        row = find_key(data, client_key)
        if not row: return False, "المفتاح غير موجود", None
        ok, msg = validate_row(row)
        if not ok: return False, msg, None
        ok, msg = bind_if_needed(row, device_hash, device_name, data)
        return ok, msg, row
    else:
        row = find_by_device(data, device_hash)
        if not row: return False, "المفتاح مطلوب لأول ربط", None
        ok, msg = validate_row(row)
        if not ok: return False, msg, None
        row["last_used"] = utcnow().isoformat()
        save_db(data)
        return True, "معروف بهذا الجهاز", row

@app.get("/", response_class=HTMLResponse)
def home():
    html_path = BASE / "index.html"
    return html_path.read_text(encoding="utf-8")

@app.post("/check")
async def check(request: Request):
    client_key = request.headers.get("X-KEY", "")
    device_hash = request.headers.get("X-DEVICE", "")
    device_name = request.headers.get("X-DEVICE-NAME", "Unknown")
    ok, msg, _row = authorize(client_key, device_hash, device_name)
    code = 200 if ok else 401
    return JSONResponse({"ok": ok, "msg": msg}, status_code=code)

@app.post("/process")
async def process(request: Request, file: UploadFile = File(...)):
    client_key = request.headers.get("X-KEY", "")
    device_hash = request.headers.get("X-DEVICE", "")
    device_name = request.headers.get("X-DEVICE-NAME", "Unknown")
    ok, msg, row = authorize(client_key, device_hash, device_name)
    if not ok: return JSONResponse({"error": msg}, status_code=401)
    
    contents = await file.read()
    if len(contents) > MAX_SIZE: return JSONResponse({"error": f"الملف أكبر من {int(MAX_SIZE/1024/1024)}MB"}, status_code=400)
    await file.seek(0)

    uid = uuid.uuid4().hex
    in_path  = WORK / f"in_{uid}.mp4"; out_path = WORK / f"out_{uid}.mp4"
    try:
        with open(in_path, "wb") as f: shutil.copyfileobj(file.file, f)
        ok = run_silent(["ffmpeg","-y","-itsscale","2","-i", str(in_path),"-c:v","copy","-c:a","copy","-movflags","+faststart",str(out_path)])
        if not ok or not out_path.exists(): return JSONResponse({"error": "تعذر إتمام المعالجة"}, status_code=500)
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
    row = None
    if client_key: row = find_key(data, client_key)
    if (row is None) and device_hash: row = find_by_device(data, device_hash)
    if not row: return JSONResponse({"error": "لا يوجد اشتراك مرتبط"}, status_code=404)

    activated_on = row.get("activated_on")
    expires_str = "لم يتم التفعيل بعد"
    days_left = row.get("duration_days", 30)

    if activated_on:
        try:
            activated_dt = parse_exp(activated_on)
            duration = timedelta(days=row.get("duration_days", 30))
            expires_dt = activated_dt + duration
            expires_str = expires_dt.strftime("%Y-%m-%d")
            seconds_left = (expires_dt - utcnow()).total_seconds()
            days_left = max(0, ceil(seconds_left / 86400))
        except: expires_str = "خطأ في صيغة التاريخ"
    
    bound_hash = row.get("device_hash") or ""
    bound = bool(bound_hash)
    bound_to_this_device = (bound_hash == device_hash) if device_hash else False
    key_mask = mask_key(row.get("key", "")) if client_key else ("***" if bound else "—")

    return JSONResponse({
        "key_masked": key_mask,
        "expires": expires_str,
        "days_left": days_left,
        "bound": bound,
        "bound_to_this_device": bound_to_this_device,
        "device_name": row.get("device_name", "غير معروف"),
        "last_used": row.get("last_used")
    }, status_code=200)
