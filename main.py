import psycopg2
import subprocess
import os
from flask import Flask, request, jsonify, send_file
from datetime import datetime, timedelta

app = Flask(__name__)

# 🔗 بيانات Supabase (من Connection Pooling)
DB_URL = "postgresql://postgres.ubartbsqgpuarlrtboyi:YOUR_PASSWORD@aws-1-eu-central-1.pooler.supabase.com:6543/postgres?sslmode=require"

def get_conn():
    return psycopg2.connect(DB_URL)

@app.route("/")
def home():
    return {"ok": True, "msg": "🚀 4Tik Pro Connected"}

# ✅ التحقق من المفتاح
@app.route("/me")
def me():
    key = request.headers.get("X-KEY")
    device = request.headers.get("X-DEVICE")
    if not key or not device:
        return jsonify({"error": "missing headers"}), 400

    conn = get_conn()
    cur = conn.cursor()

    # هل المفتاح موجود؟
    cur.execute("SELECT key FROM keys WHERE key=%s", (key,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return jsonify({"error": "invalid key"}), 401

    # تحقق من الربط
    cur.execute("SELECT * FROM binds WHERE key=%s", (key,))
    bind = cur.fetchone()

    if not bind:
        start = datetime.utcnow()
        expires = start + timedelta(days=30)
        cur.execute("INSERT INTO binds (key, device, start, expires, last_used) VALUES (%s,%s,%s,%s,%s)",
                    (key, device, start, expires, datetime.utcnow()))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({
            "key": key,
            "expires": expires.isoformat(),
            "days_left": 30,
            "bound_to_this_device": True
        })

    # تحديث آخر استخدام
    cur.execute("UPDATE binds SET last_used=%s WHERE key=%s", (datetime.utcnow(), key))
    conn.commit()
    expires = bind[3]
    days_left = (expires - datetime.utcnow()).days
    cur.close()
    conn.close()

    return jsonify({
        "key": key,
        "expires": expires.isoformat(),
        "days_left": days_left,
        "bound_to_this_device": (bind[1] == device)
    })

# ✅ معالجة الفيديو بـ itsscale 2
@app.route("/process", methods=["POST"])
def process_video():
    key = request.headers.get("X-KEY")
    device = request.headers.get("X-DEVICE")
    if not key or not device:
        return jsonify({"error": "missing headers"}), 400

    file = request.files.get("file")
    if not file:
        return jsonify({"error": "no file uploaded"}), 400

    input_path = "/tmp/input.mp4"
    output_path = "/tmp/output.mp4"
    file.save(input_path)

    try:
        # ⚡ استخدام FFmpeg مع itsscale 2
        cmd = [
            "ffmpeg", "-itsscale", "2",
            "-i", input_path,
            "-c:v", "copy",
            "-c:a", "copy",
            output_path
        ]
        subprocess.run(cmd, check=True)

        return send_file(output_path, as_attachment=True, download_name="output.mp4")
    except subprocess.CalledProcessError:
        return jsonify({"error": "ffmpeg failed"}), 500
    finally:
        if os.path.exists(input_path): os.remove(input_path)
        if os.path.exists(output_path): os.remove(output_path)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)