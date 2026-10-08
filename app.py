import hmac
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask,
    after_this_request,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from PIL import Image, ImageOps

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

SECRET_FILE = BASE_DIR / ".flask_secret"
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

APP_PASSWORD = os.environ.get("APP_PASSWORD")
CERT_DOMAIN = os.environ.get("CERT_DOMAIN")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5001"))
DISABLE_SSL = os.environ.get("DISABLE_SSL", "").lower() in ("1", "true", "yes")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "0"))  # 0 = illimité
MAX_DIMENSION = int(os.environ.get("MAX_DIMENSION", "1920"))

FAILED_ATTEMPT_LIMIT = 10
FAILED_ATTEMPT_LOCKOUT_SECONDS = 5 * 60


def _get_ssl_context():
    if DISABLE_SSL:
        return None
    if CERT_DOMAIN:
        cert_dir = Path("/etc/letsencrypt/live") / CERT_DOMAIN
        fullchain = cert_dir / "fullchain.pem"
        privkey = cert_dir / "privkey.pem"
        if fullchain.exists() and privkey.exists():
            return (str(fullchain), str(privkey))
        print(f"[ATTENTION] Certificat introuvable pour {CERT_DOMAIN} dans {cert_dir}, "
              "retour à un certificat auto-signé.")
    return "adhoc"


def _get_secret_key():
    env_secret = os.environ.get("FLASK_SECRET")
    if env_secret:
        return env_secret
    if SECRET_FILE.exists():
        return SECRET_FILE.read_bytes()
    secret = os.urandom(32)
    SECRET_FILE.write_bytes(secret)
    return secret


app = Flask(__name__)
app.secret_key = _get_secret_key()
app.config["MAX_CONTENT_LENGTH"] = (MAX_UPLOAD_MB * 1024 * 1024) if MAX_UPLOAD_MB > 0 else None

_failed_attempts = {}  # ip -> (count, first_attempt_ts)
_jobs = {}  # job_id -> {"status": ..., "current": int, "total": int, "error": str|None}
_jobs_lock = threading.Lock()


def _set_job(job_id, **kwargs):
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def _client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"


def _is_locked_out(ip):
    entry = _failed_attempts.get(ip)
    if not entry:
        return False
    count, first_ts = entry
    if count < FAILED_ATTEMPT_LIMIT:
        return False
    if time.time() - first_ts > FAILED_ATTEMPT_LOCKOUT_SECONDS:
        _failed_attempts.pop(ip, None)
        return False
    return True


def _record_failed_attempt(ip):
    count, first_ts = _failed_attempts.get(ip, (0, time.time()))
    if time.time() - first_ts > FAILED_ATTEMPT_LOCKOUT_SECONDS:
        count, first_ts = 0, time.time()
    _failed_attempts[ip] = (count + 1, first_ts)


@app.before_request
def require_gate_password():
    if not APP_PASSWORD:
        return
    if request.endpoint in ("gate", "static"):
        return
    if not session.get("gate_ok"):
        return redirect(url_for("gate"))


@app.route("/gate", methods=["GET", "POST"])
def gate():
    if not APP_PASSWORD:
        return redirect(url_for("index"))

    ip = _client_ip()
    if request.method == "GET":
        return render_template("gate.html")

    if _is_locked_out(ip):
        return render_template(
            "gate.html", error="Trop de tentatives. Réessaie dans quelques minutes."
        )

    submitted = request.form.get("password", "")
    if hmac.compare_digest(submitted, APP_PASSWORD):
        _failed_attempts.pop(ip, None)
        session["gate_ok"] = True
        return redirect(url_for("index"))

    _record_failed_attempt(ip)
    time.sleep(1)
    return render_template("gate.html", error="Mot de passe incorrect.")


@app.route("/")
def index():
    return render_template("index.html", max_upload_mb=MAX_UPLOAD_MB)


def _normalize_frame(raw_path, target_size):
    with Image.open(raw_path) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")

        if img.width > MAX_DIMENSION or img.height > MAX_DIMENSION:
            img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

        if target_size is None:
            target_size = img.size

        return ImageOps.pad(img, target_size, color=(0, 0, 0)), target_size


def _process_job(job_id, work_dir, raw_paths, fps, output_path):
    n = len(raw_paths)
    total_steps = n * 2  # normalizing (0..n) + encoding (n..2n)
    try:
        target_size = None
        for i, raw_path in enumerate(raw_paths):
            _set_job(job_id, status="normalizing", current=i, total=total_steps)
            try:
                frame, target_size = _normalize_frame(raw_path, target_size)
            except Exception as e:
                _set_job(job_id, status="error", error=f"Image invalide ({raw_path.name}) : {e}")
                return
            frame.save(work_dir / f"frame_{i:05d}.jpg", quality=92)
            raw_path.unlink(missing_ok=True)

        _set_job(job_id, status="encoding", current=n, total=total_steps)

        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(work_dir / "frame_%05d.jpg"),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            "-progress", "pipe:1",
            "-nostats",
            str(output_path),
        ]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("frame="):
                try:
                    frame_num = min(int(line.split("=", 1)[1]), n)
                    _set_job(job_id, status="encoding", current=n + frame_num, total=total_steps)
                except ValueError:
                    pass
        proc.wait(timeout=900)
        stderr_output = proc.stderr.read()

        if proc.returncode != 0:
            _set_job(job_id, status="error", error=stderr_output[-3000:])
            return

        _set_job(job_id, status="done", current=total_steps, total=total_steps)
    except Exception as e:
        _set_job(job_id, status="error", error=str(e))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.route("/api/generate", methods=["POST"])
def generate():
    files = request.files.getlist("images")
    files = [f for f in files if f and f.filename]
    if not files:
        return jsonify({"error": "Aucune image reçue."}), 400

    try:
        fps = float(request.form.get("fps", "1"))
    except ValueError:
        fps = 1.0
    fps = max(0.1, min(fps, 60))

    job_id = uuid.uuid4().hex[:12]
    work_dir = Path(tempfile.mkdtemp(prefix=f"ptv_{job_id}_"))

    raw_paths = []
    for i, f in enumerate(files):
        ext = Path(f.filename).suffix or ".jpg"
        raw_path = work_dir / f"raw_{i:05d}{ext}"
        f.save(raw_path)
        raw_paths.append(raw_path)

    output_path = OUTPUT_DIR / f"video_{job_id}.mp4"
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "normalizing",
            "current": 0,
            "total": len(raw_paths) * 2,
            "error": None,
        }

    threading.Thread(
        target=_process_job,
        args=(job_id, work_dir, raw_paths, fps, output_path),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def job_status(job_id):
    job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "not_found"}), 404
    return jsonify(job)


@app.route("/api/download/<job_id>")
def download(job_id):
    job = _jobs.get(job_id)
    if not job or job.get("status") != "done":
        return "", 425

    output_path = OUTPUT_DIR / f"video_{job_id}.mp4"
    if not output_path.exists():
        return "", 404

    @after_this_request
    def cleanup(response):
        try:
            output_path.unlink(missing_ok=True)
        except Exception:
            pass
        with _jobs_lock:
            _jobs.pop(job_id, None)
        return response

    return send_file(output_path, as_attachment=True, download_name="video.mp4")


@app.route("/logout")
def logout():
    session.pop("gate_ok", None)
    return redirect(url_for("gate" if APP_PASSWORD else "index"))


if __name__ == "__main__":
    is_local_only = HOST in ("127.0.0.1", "localhost")
    if not APP_PASSWORD and not is_local_only:
        print(
            "\n[ATTENTION] Aucun APP_PASSWORD défini : l'app sera accessible sans mot de "
            "passe à quiconque atteint ce port. Lance plutôt :\n"
            "  APP_PASSWORD='ton-mot-de-passe' python app.py\n"
        )
    app.run(host=HOST, port=PORT, ssl_context=_get_ssl_context(), threaded=True)
