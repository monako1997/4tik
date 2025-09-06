import os, json, time, subprocess
from datetime import datetime, timedelta
from fastapi import FastAPI, UploadFile, Header, Response
from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from tempfile import NamedTemporaryFile

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---- مفاتيح مصرح بها (ضع مفاتيحك الفعلية وتواريخ الانتهاء) ----
# مثال: {"KEYVALUE1":{"expires":"2025-12-31"}, "KEYVALUE2":{"expires":"2026-01-15"}}
KEYS_FILE = "keys.json"
BINDS_FILE = "binds.json"

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except: return default

def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

# حمّل/أنشئ الملفات
keys = load_json(KEYS_FILE, {
    # ضع مفاتيحك هنا إن لم تستخدم keys.json خارجي
    "DEMO-KEY-1234": {"expires": "2026-12-31"}
})
binds = load_json(BINDS_FILE, {})  # شكل: { "DEMO-KEY-1234": {"device":"<hash>", "last_used":"2025-09-06 12:00"} }

def now_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def is_expired(iso):
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
        return datetime.utcnow().date() > d.date()
    except:
        return True

def days_left(iso):
    try:
        d = datetime.strptime(iso, "%Y-%m-%d").date()
        return (d - datetime.utcnow().date()).days
    except:
        return 0

def auth_guard(x_key: str | None, x_device: str | None):
    # 1) لو ما في مفتاح ولكن الجهاز معروف سابقاً (ربط مسبق) سنسمح بذلك فقط لو وجدنا ربطاً يناسبه
    if (not x_key) and x_device:
        # ابحث إن كان أي مفتاح مربوط بهذا الجهاز
        for k, b in binds.items():
            if b.get("device") == x_device:
                kmeta = keys.get(k)
                if (not kmeta) or is_expired(kmeta["expires"]): return (False, "expired", None)
                # نجح السماح بالجهاز وحده
                binds[k]["last_used"] = now_str()
                save_json(BINDS_FILE, binds)
                return (True, k, kmeta)
        return (False, "no-key-and-unknown-device", None)

    # 2) مفتاح مفقود
    if not x_key: return (False, "missing-key", None)
    if not x_device: return (False, "missing-device", None)

    meta = keys.get(x_key)
    if not meta: return (False, "invalid-key", None)
    if is_expired(meta["expires"]): return (False, "expired", None)

    bound = binds.get(x_key)
    if not bound:
        # أول ربط
        binds[x_key] = {"device": x_device, "last_used": now_str()}
        save_json(BINDS_FILE, binds)
        return (True, x_key, meta)

    # مفتاح مربوط من قبل
    if bound["device"] != x_device:
        return (False, "bound-to-other-device", None)

    # نفس الجهاز
    binds[x_key]["last_used"] = now_str()
    save_json(BINDS_FILE, binds)
    return (True, x_key, meta)

@app.post("/check")
def check(x_device: str | None = Header(None)):
    # يسمح بمعرفة هل الجهاز معروف مسبقًا ليعمل "DEVICE_ONLY__" في الواجهة
    if not x_device:
        return JSONResponse({"ok": False, "error": "missing-device"}, status_code=400)
    for k, b in binds.items():
        if b.get("device") == x_device:
            kmeta = keys.get(k)
            if (not kmeta) or is_expired(kmeta["expires"]):
                return JSONResponse({"ok": False, "error": "expired"}, status_code=401)
            return {"ok": True}
    return JSONResponse({"ok": False, "error": "unknown-device"}, status_code=404)

@app.get("/me")
def me(x_key: str | None = Header(None), x_device: str | None = Header(None)):
    ok, code, meta = auth_guard(x_key, x_device)
    if not ok:
        msg = {
            "missing-key": "المفتاح مفقود",
            "missing-device": "الجهاز مفقود",
            "invalid-key": "مفتاح غير صحيح",
            "expired": "انتهى الاشتراك",
            "bound-to-other-device": "المفتاح مربوط بجهاز آخر",
            "no-key-and-unknown-device": "الجهاز غير معروف"
        }.get(code, "غير مصرح")
        return JSONResponse({"error": msg}, status_code=401)

    # معلومات اشتراك مبسّطة
    k = code
    b = binds.get(k, {})
    return {
        "key_masked": k[:4] + "****" + k[-4:],
        "expires": meta["expires"],
        "days_left": days_left(meta["expires"]),
        "bound": True if b else False,
        "bound_to_this_device": (b.get("device") == x_device) if b else False,
        "last_used": b.get("last_used") if b else None
    }

@app.post("/process")
async def process(file: UploadFile, x_key: str | None = Header(None), x_device: str | None = Header(None)):
    ok, code, meta = auth_guard(x_key, x_device)
    if not ok:
        msg = {
            "missing-key": "المفتاح مفقود",
            "missing-device": "الجهاز مفقود",
            "invalid-key": "مفتاح غير صحيح",
            "expired": "انتهى الاشتراك",
            "bound-to-other-device": "المفتاح مربوط بجهاز آخر",
            "no-key-and-unknown-device": "الجهاز غير معروف"
        }.get(code, "غير مصرح")
        return PlainTextResponse(msg, status_code=401)

    # حد الحجم 100 ميقا
    # FastAPI لا يعرف الحجم قبل القراءة، فنكتب للقرص مؤقتًا
    with NamedTemporaryFile(delete=False, suffix=".mp4") as src:
        content = await file.read()
        if len(content) > 100 * 1024 * 1024:
            return PlainTextResponse("الملف يتجاوز 100 ميقا", status_code=400)
        src.write(content)
        src_path = src.name

    out_path = src_path.replace(".mp4", "_out.mp4")

    # أمر FFmpeg الخاص بك (الترقية مع الحفاظ على الصوت/الفيديو بنقل مباشر)
    # ملاحظة: -itsscale مفيد للتايم ستامب؛ استعمل أمرك الحقيقي هنا
    cmd = ["ffmpeg", "-y", "-itsscale", "2", "-i", src_path, "-c:v", "copy", "-c:a", "copy", out_path]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        return PlainTextResponse("فشل FFmpeg", status_code=500)

    def iterfile():
        with open(out_path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk: break
                yield chunk
        try:
            os.remove(src_path)
            os.remove(out_path)
        except: pass

    headers = {"Content-Disposition": 'attachment; filename="output.mp4"'}
    return StreamingResponse(iterfile(), media_type="video/mp4", headers=headers)