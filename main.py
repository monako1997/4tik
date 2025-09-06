import os, json, hashlib, tempfile, subprocess, datetime, threading
from flask import Flask, request, send_file, Response, abort

app = Flask(__name__)

# === DAILY SERVER LIMIT (config) ===
DAILY_LIMIT = 1                      # مرة واحدة يوميًا
QUOTA_FILE = 'quota.json'            # ملف صغير لتتبع الاستخدام السيرفري
PEPPER = 'change-this-pepper'        # سلسلة ثابتة لزيادة أمان التجزئة (عدّليها)

quota_lock = threading.Lock()

def _today_str():
    return datetime.date.today().isoformat()

def _client_ip():
    # يدعم منصات استضافة تمّرر X-Forwarded-For
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        # أول IP هو الأقرب للعميل
        return xff.split(',')[0].strip()
    return request.remote_addr or '0.0.0.0'

def _fingerprint_for_today():
    ua = request.headers.get('User-Agent', '')
    ip = _client_ip()
    today = _today_str()
    raw = f"{ip}|{ua}|{today}|{PEPPER}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()

def _read_quota():
    if not os.path.exists(QUOTA_FILE):
        return {}
    try:
        with open(QUOTA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _write_quota(data):
    # كتابة ذرّية لتفادي تلف الملف
    tmp_fd, tmp_path = tempfile.mkstemp(prefix='quota_', suffix='.json')
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, QUOTA_FILE)
    finally:
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except: pass

def _used_up():
    key = _fingerprint_for_today()
    with quota_lock:
        q = _read_quota()
        return q.get(key, 0) >= DAILY_LIMIT

def _record_success():
    key = _fingerprint_for_today()
    with quota_lock:
        q = _read_quota()
        q[key] = q.get(key, 0) + 1
        _write_quota(q)

# ========= FFmpeg processing =========
def _run_ffmpeg(in_path, out_path):
    # حسب طلبك: itsscale 2 مع نسخ الفيديو/الصوت كما هو
    cmd = [
        'ffmpeg', '-hide_banner', '-y',
        '-itsscale', '2',
        '-i', in_path,
        '-c:v', 'copy',
        '-c:a', 'copy',
        out_path
    ]
    # شغّل ffmpeg وتحقق من الإرجاع
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(proc.stderr.decode('utf-8', errors='ignore'))

@app.route('/process', methods=['POST'])
def process_video():
    # === DAILY SERVER LIMIT: فحص الحد قبل أي معالجة
    if _used_up():
        # 429 = Too Many Requests
        return Response("Daily limit reached for this device. Try again tomorrow.", status=429)

    file = request.files.get('file')
    if not file:
        return abort(400, 'No file provided')

    # حفظ مؤقت ثم معالجة
    with tempfile.TemporaryDirectory() as td:
        in_path = os.path.join(td, 'input.mp4')
        out_path = os.path.join(td, 'output.mp4')
        file.save(in_path)

        try:
            _run_ffmpeg(in_path, out_path)
        except Exception as e:
            return abort(500, 'Processing failed')

        # === DAILY SERVER LIMIT: تسجيل النجاح بعد المعالجة
        _record_success()

        # إرسال الملف الناتج
        return send_file(
            out_path,
            as_attachment=True,
            download_name='output.mp4',
            mimetype='video/mp4'
        )

@app.route('/', methods=['GET'])
def root():
    # اختياري: قد تكون صفحتك index.html تُخدّم عبر static.
    return Response("OK", status=200)

if __name__ == '__main__':
    # شغّل الخادم محليًا
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))