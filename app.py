import hmac
import math
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
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "0"))
MAX_DIMENSION = int(os.environ.get("MAX_DIMENSION", "1920"))

FAILED_ATTEMPT_LIMIT = 10
FAILED_ATTEMPT_LOCKOUT_SECONDS = 5 * 60

OUTPUT_FPS = 30
TRANSITIONS = ("none", "fade", "slide")
ASPECTS = {"auto": None, "16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1), "4:3": (4, 3), "3:4": (3, 4)}
RESOLUTIONS = (480, 720, 1080)
FITS = ("contain", "cover")


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

_failed_attempts = {}
_jobs = {}
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


def _even(x):
    return max(2, int(round(x / 2)) * 2)


def _oriented_size(raw_path):
    with Image.open(raw_path) as img:
        w, h = img.size
        if img.getexif().get(0x0112) in (5, 6, 7, 8):
            w, h = h, w
        return w, h


def _video_size(first_size, aspect, short_side):
    w, h = aspect or first_size
    if w >= h:
        width, height = short_side * w / h, short_side
    else:
        width, height = short_side, short_side * h / w
    scale = min(1.0, MAX_DIMENSION / max(width, height))
    return _even(width * scale), _even(height * scale)


def _normalize_frame(raw_path, size, fit, background):
    with Image.open(raw_path) as img:
        img.draft("RGB", (max(size) * 2, max(size) * 2))
        img = ImageOps.exif_transpose(img).convert("RGB")
        if fit == "cover":
            return ImageOps.fit(img, size, Image.LANCZOS)
        return ImageOps.pad(img, size, Image.LANCZOS, color=background)


def _transition_frames(a, b, style, count):
    width = a.width
    for k in range(1, count + 1):
        t = k / (count + 1)
        if style == "fade":
            yield Image.blend(a, b, t)
        else:
            t = 0.5 - 0.5 * math.cos(t * math.pi)
            shift = round(width * t)
            frame = Image.new("RGB", a.size)
            frame.paste(a, (-shift, 0))
            frame.paste(b, (width - shift, 0))
            yield frame


def _process_job(job_id, work_dir, raw_paths, opts, output_path):
    n = len(raw_paths)
    duration, transition, tr_duration = opts["duration"], opts["transition"], opts["transition_duration"]
    tr_count = round(tr_duration * OUTPUT_FPS) if transition != "none" and n > 1 else 0
    total_steps = n + (n - 1) * tr_count + 100
    step = 0
    try:
        try:
            first_size = _oriented_size(raw_paths[0])
        except Exception as e:
            _set_job(job_id, status="error", error=f"Image invalide ({raw_paths[0].name}) : {e}")
            return
        size = _video_size(first_size, ASPECTS[opts["aspect"]], opts["resolution"])

        playlist = []
        previous = None
        for i, raw_path in enumerate(raw_paths):
            _set_job(job_id, status="normalizing", current=step, total=total_steps)
            try:
                frame = _normalize_frame(raw_path, size, opts["fit"], opts["background"])
            except Exception as e:
                _set_job(job_id, status="error", error=f"Image invalide (photo n° {i + 1}) : {e}")
                return
            raw_path.unlink(missing_ok=True)
            step += 1

            if previous is not None and tr_count:
                _set_job(job_id, status="transitions", current=step, total=total_steps)
                for k, tr_frame in enumerate(_transition_frames(previous, frame, transition, tr_count)):
                    name = f"tr_{i:05d}_{k:03d}.jpg"
                    tr_frame.save(work_dir / name, quality=90)
                    playlist.append((name, 1 / OUTPUT_FPS))
                    step += 1
                    if k % 10 == 0:
                        _set_job(job_id, current=step)

            name = f"frame_{i:05d}.jpg"
            frame.save(work_dir / name, quality=92)
            playlist.append((name, duration))
            previous = frame

        total_seconds = sum(d for _, d in playlist)
        lines = []
        for name, d in playlist:
            lines += [f"file '{name}'", f"duration {d:.6f}"]
        lines.append(f"file '{playlist[-1][0]}'")
        (work_dir / "playlist.txt").write_text("\n".join(lines) + "\n")

        _set_job(job_id, status="encoding", current=step, total=total_steps)
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(work_dir / "playlist.txt"),
            "-vf", f"fps={OUTPUT_FPS},format=yuv420p",
            "-t", f"{total_seconds:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(opts["crf"]),
            *(["-tune", "stillimage"] if not tr_count else []),
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats",
            str(output_path),
        ]
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    pct = min(100, int(int(line.split("=", 1)[1]) / 1e6 / total_seconds * 100))
                    _set_job(job_id, status="encoding", current=step + max(pct, 0), total=total_steps)
                except ValueError:
                    pass
        proc.wait(timeout=1800)
        stderr_output = proc.stderr.read()

        if proc.returncode != 0:
            _set_job(job_id, status="error", error=stderr_output[-3000:])
            return

        _set_job(job_id, status="done", current=total_steps, total=total_steps)
    except Exception as e:
        _set_job(job_id, status="error", error=str(e))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _form_float(name, default, low, high):
    try:
        value = float(request.form.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def _video_options():
    duration = _form_float("duration", 0, 0, 10)
    if not duration:
        duration = 1 / _form_float("fps", 1, 0.1, 10)
    duration = max(0.1, duration)
    transition = request.form.get("transition", "none")
    if transition not in TRANSITIONS:
        transition = "none"
    aspect = request.form.get("aspect", "auto")
    if aspect not in ASPECTS:
        aspect = "auto"
    try:
        resolution = int(request.form.get("resolution", 1080))
    except ValueError:
        resolution = 1080
    if resolution not in RESOLUTIONS:
        resolution = 1080
    fit = request.form.get("fit", "contain")
    if fit not in FITS:
        fit = "contain"
    background = request.form.get("background", "#000000")
    try:
        if len(background) != 7 or background[0] != "#":
            raise ValueError
        rgb = tuple(int(background[i:i + 2], 16) for i in (1, 3, 5))
    except ValueError:
        rgb = (0, 0, 0)
    return {
        "duration": duration,
        "transition": transition,
        "transition_duration": _form_float("transition_duration", 0.5, 0.1, 2),
        "aspect": aspect,
        "resolution": resolution,
        "fit": fit,
        "background": rgb,
        "crf": int(_form_float("crf", 23, 18, 32)),
    }


@app.route("/api/generate", methods=["POST"])
def generate():
    files = request.files.getlist("images")
    files = [f for f in files if f and f.filename]
    if not files:
        return jsonify({"error": "Aucune image reçue."}), 400

    opts = _video_options()

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
            "total": len(raw_paths) + 100,
            "error": None,
        }

    threading.Thread(
        target=_process_job,
        args=(job_id, work_dir, raw_paths, opts, output_path),
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
