import os, subprocess, psycopg2, psycopg2.extras
from datetime import datetime, timedelta
from tempfile import NamedTemporaryFile

from fastapi import FastAPI, UploadFile, Header
from fastapi.responses import (
    JSONResponse, PlainTextResponse, StreamingResponse, FileResponse
)
from fastapi.middleware.cors import CORSMiddleware

# ========= إعداد اتصال قاعدة البيانات عبر DATABASE_URL =========
# مثال القيمة في Koyeb:
# postgresql://postgres.<PROJECT_REF>:PASSWORD@aws-1-eu-central-1.pooler.supabase.com:6543/postgres
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("ENV DATABASE_URL غير مُعرّف")

def db_connect():
    # sslmode=require ضمنيًا في pooler، ويمكن إضافته إن رغبت: + "?sslmode=require"
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)

conn = db_connect()
conn.autocommit = True

def db_cursor():
    """يعيد cursor صالحًا، ويُعيد الاتصال تلقائياً إذا انقطع."""
    global conn
    try:
        return conn.cursor()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        conn = db_connect()
        conn.autocommit = True
        return conn.cursor()

# إنشاء الجداول إن لم تكن موجودة
with db_cursor() as cur:
    cur.execute("""
    CREATE TABLE IF NOT EXISTS keys (
        key TEXT PRIMARY KEY
    );""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS binds (
        key TEXT,
        device TEXT,
        start TIMESTAMP,
        expires TIMESTAMP,
        last_used TIMESTAMP
    );""")

# =================== إعداد التطبيق ===================
app = FastAPI(title="4Tik Pro API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

def now(): return datetime.utcnow()
def fmt(dt: datetime) -> str: return dt.strftime("%Y-%m-%d %H:%M:%S")

# =================== دوال قاعدة البيانات ===================
def key_exists(k: str) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM keys WHERE key=%s LIMIT 1;", (k,))
        return cur.fetchone() is not None

def get_bind_by_key(k: str):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM binds WHERE key=%s LIMIT 1;", (k,))
        return cur.fetchone()

def get_bind_by_device(d: str):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM binds WHERE device=%s LIMIT 1;", (d,))
        return cur.fetchone()

def create_bind(k: str, d: str):
    start = now()
    exp = start + timedelta(days=30)
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO binds (key, device, start, expires, last_used) VALUES (%s,%s,%s,%s,%s);",
            (k, d, start, exp, start)
        )
    return {"expires": fmt(exp)}

def update_last_used(k: str):
    with db_cursor() as cur:
        cur.execute("UPDATE binds SET last_used=%s WHERE key=%s;", (now(), k))

# =================== حارس التحقق ===================
def auth_guard(x_key: str | None, x_device: str | None):
    if not x_device:
        return (False, "missing-device", None)

    # لو بدون مفتاح: حاول التعرّف عبر الجهاز فقط
    if not x_key:
        b = get_bind_by_device(x_device)
        if not b:
            return (False, "missing-key", None)
        if now() > b["expires"]:
            return (False, "expired", None)
        update_last_used(b["key"])
        return (True, b["key"], {"expires": fmt(b["expires"])})

    # يوجد مفتاح
    if not key_exists(x_key):
        return (False, "invalid-key", None)

    b = get_bind_by_key(x_key)

    # أول استخدام → اربط المفتاح بالجهاز وابدأ 30 يوم
    if not b:
        meta = create_bind(x_key, x_device)
        return (True, x_key, meta)

    # المفتاح مربوط بجهاز آخر
    if b["device"] != x_device:
        return (False, "bound-to-other-device", None)

    # التحقق من انتهاء الاشتراك
    if now() > b["expires"]:
        return (False, "expired", None)

    update_last_used(x_key)
    return (True, x_key, {"expires": fmt(b["expires"])})

# =================== المسارات ===================
@app.get("/check")
def check(x_device: str | None = Header(None)):
    if not x_device:
        return JSONResponse({"ok": False, "error": "missing-device"}, status_code=400)

    b = get_bind_by_device(x_device)
    if not b:
        return JSONResponse({"ok": False, "error": "unknown-device"}, status_code=404)
    if now() > b["expires"]:
        return JSONResponse({"ok": False, "error": "expired"}, status_code=401)
    update_last_used(b["key"])
    return {"ok": True}

@app.get("/me")
def me(x_key: str | None = Header(None), x_device: str | None = Header(None)):
    ok, code, meta = auth_guard(x_key, x_device)
    if not ok:
        msgs = {
            "missing-key": "🔑 المفتاح مفقود",
            "missing-device": "📱 الجهاز مفقود",
            "invalid-key": "❌ مفتاح غير صحيح",
            "expired": "⏰ انتهى الاشتراك",
            "bound-to-other-device": "⚠️ المفتاح مربوط بجهاز آخر"
        }
        return JSONResponse({"error": msgs.get(code, "غير مصرح")}, status_code=401)

    b = get_bind_by_key(code)
    bound_to_this = (b is not None and b["device"] == x_device)
    expires_str = meta["expires"]
    exp_dt = datetime.strptime(expires_str, "%Y-%m-%d %H:%M:%S")
    # تقريب للأعلى حتى يظهر 30 يومًا في أول يوم
    days_left = max(0, int((exp_dt - now()).total_seconds() / 86400 + 0.9999))

    return {
        "key_masked": code[:4] + "****",
        "expires": expires_str,
        "days_left": days_left,
        "bound": b is not None,
        "bound_to_this_device": bound_to_this,
        "last_used": fmt(b["last_used"]) if b and b["last_used"] else None
    }

@app.post("/process")
async def process(file: UploadFile, x_key: str | None = Header(None), x_device: str | None = Header(None)):
    ok, code, meta = auth_guard(x_key, x_device)
    if not ok:
        msgs = {
            "missing-key": "🔑 المفتاح مفقود",
            "missing-device": "📱 الجهاز مفقود",
            "invalid-key": "❌ مفتاح غير صحيح",
            "expired": "⏰ انتهى الاشتراك",
            "bound-to-other-device": "⚠️ المفتاح مربوط بجهاز آخر"
        }
        return PlainTextResponse(msgs.get(code, "غير مصرح"), status_code=401)

    # حد الحجم 100MB
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        return PlainTextResponse("🚫 الحجم أكبر من 100MB", status_code=400)

    # معالجة FFmpeg (عدّل الفلاتر حسب حاجتك)
    with NamedTemporaryFile(delete=False, suffix=".mp4") as src:
        src.write(content)
        src_path = src.name
    out_path = src_path.replace(".mp4", "_out.mp4")

    cmd = ["ffmpeg", "-y", "-i", src_path, "-c:v", "copy", "-c:a", "copy", out_path]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        try:
            os.remove(src_path)
        except Exception:
            pass
        return PlainTextResponse("⚠️ فشل FFmpeg", status_code=500)

    def stream_file():
        with open(out_path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk
        try:
            os.remove(src_path)
            os.remove(out_path)
        except Exception:
            pass

    headers = {"Content-Disposition": 'attachment; filename="output.mp4"'}
    return StreamingResponse(stream_file(), media_type="video/mp4", headers=headers)

# خدمة الواجهة
@app.get("/")
def root():
    return FileResponse("index.html")