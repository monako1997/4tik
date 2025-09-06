import os, tempfile, subprocess, datetime
from flask import Flask, request, send_file, Response, abort

app = Flask(__name__)

# تخزين محاولات المستخدمين لليوم
daily_usage = {}  # { "ip-date": count }

def today_str():
    return datetime.date.today().isoformat()

def client_ip():
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr or '0.0.0.0'

@app.route('/process', methods=['POST'])
def process_video():
    ip = client_ip()
    key = f"{ip}-{today_str()}"
    count = daily_usage.get(key, 0)

    if count >= 1:
        return Response("لقد استعملت حصتك اليومية (فيديو واحد). جرّب غدًا ✋", status=429)

    file = request.files.get('file')
    if not file:
        return abort(400, 'لم يتم رفع أي ملف')

    with tempfile.TemporaryDirectory() as td:
        in_path = os.path.join(td, 'input.mp4')
        out_path = os.path.join(td, 'output.mp4')
        file.save(in_path)

        # أمر ffmpeg (حسب طلبك)
        cmd = [
            'ffmpeg', '-hide_banner', '-y',
            '-itsscale', '2',
            '-i', in_path,
            '-c:v', 'copy',
            '-c:a', 'copy',
            out_path
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            return abort(500, 'فشل المعالجة')

        # تسجيل الاستخدام
        daily_usage[key] = count + 1

        return send_file(out_path,
                         as_attachment=True,
                         download_name='output.mp4',
                         mimetype='video/mp4')

@app.route('/')
def index():
    return app.send_static_file('index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))