import os, json, subprocess
from datetime import datetime, timedelta
from fastapi import FastAPI, UploadFile, Header
from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from tempfile import NamedTemporaryFile

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# -------- الملفات --------
KEYS_FILE = "keys.json"
BINDS_FILE = "binds.json"

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def now_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

# -------- تحميل المفاتيح + الربط --------
keys = load_json(KEYS_FILE, {})   # يقرأ المفاتيح من keys.json
binds = load_json(BINDS_FILE, {}) # يُنشأ تلقائيًا إذا غير موجود

# -------- التحقق --------
def auth_guard(x_key: str | None, x_device: str | None):
    if not x_key:
        return (False, "missing-key", None)
    if not x_device:
        return (False, "missing-device", None)

    if x_key not in keys:
        return (False, "invalid-key", None)

    bound = binds.get(x_key)

    # أول استخدام → يبدأ العد 30 يوم
    if not bound:
        start = datetime.utcnow()
        exp = start + timedelta(days=30)
        binds[x_key] = {
            "device": x_device,
            "start": start.strftime("%Y-%m-%d %H:%M:%S"),
            "expires": exp.strftime("%Y-%m-%d %H:%M:%S"),
            "last_used": now_str()
        }
        save_json(BINDS_FILE, binds)
        return (True, x_key, {"expires": exp.strftime("%Y-%m-%d")})

    # لو مربوط بجهاز آخر
    if bound["device"] != x_device:
        return (False, "bound-to-other-device", None)

    # تحقق من الانتهاء
    exp_dt = datetime.strptime(bound["expires"], "%Y-%m-%d %H:%M:%S")
    if datetime.utcnow() > exp_dt:
        return (False, "expired", None)

    # مفتاح صالح
    bound["last_used"] = now_str()
    save_json(BINDS_FILE, binds)
    return (True, x_key, {"expires": bound["expires"]})

# -------- API --------
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

    b = binds.get(code, {})
    return {
        "key_masked": code[:4] + "****",
        "expires": meta["expires"],
        "bound": True,
        "bound_to_this_device": (b.get("device") == x_device),
        "last_used": b.get("last_used")
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

    # تحقق الحجم ≤ 100MB
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        return PlainTextResponse("🚫 الحجم أكبر من 100MB", status_code=400)

    with NamedTemporaryFile(delete=False, suffix=".mp4") as src:
        src.write(content)
        src_path = src.name
    out_path = src_path.replace(".mp4", "_out.mp4")

    # أمر FFmpeg (استعمل أمرك)
    cmd = ["ffmpeg", "-y", "-itsscale", "2", "-i", src_path, "-c:v", "copy", "-c:a", "copy", out_path]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        return PlainTextResponse("⚠️ فشل FFmpeg", status_code=500)

    def iterfile():
        with open(out_path, "rb") as f:
            while chunk := f.read(1024 * 1024):
                yield chunk
        try:
            os.remove(src_path)
            os.remove(out_path)
        except:
            pass

    headers = {"Content-Disposition": 'attachment; filename=\"output.mp4\"'}
    return StreamingResponse(iterfile(), media_type="video/mp4", headers=headers)

# -------- الواجهة --------
app.mount("/", StaticFiles(directory="public", html=True), name="static")