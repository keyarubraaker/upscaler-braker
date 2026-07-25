"""
Anime Video Upscaler - Web Server
Flask backend pentru procesare video cu Real-ESRGAN
"""
import os, subprocess, tempfile, shutil, time, threading, uuid
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template_string
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

UPLOAD_DIR = Path(tempfile.gettempdir()) / "anime_upscaler"
UPLOAD_DIR.mkdir(exist_ok=True)

# starea joburilor
jobs = {}

# ── helper: gaseste realcugan sau ffmpeg ──────────────────────────────────────
def find_exe(name):
    return shutil.which(name)

def fmt_time(s):
    s = max(0, int(s))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s" if h else (f"{m}m {s}s" if m else f"{s}s")

# ── procesare video ───────────────────────────────────────────────────────────
def process_video(job_id, input_path, scale, force1080):
    job = jobs[job_id]
    tmp  = UPLOAD_DIR / job_id
    tmp.mkdir(exist_ok=True)

    try:
        job["status"]  = "extracting"
        job["message"] = "Extrag frames..."
        job["progress"] = 5

        # video info
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", str(input_path)],
            capture_output=True, text=True, timeout=30)
        import json as _json
        data = _json.loads(r.stdout)
        vstream = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
        fps_raw = vstream.get("r_frame_rate", "24/1").split("/")
        fps = float(fps_raw[0]) / float(fps_raw[1])
        w   = int(vstream.get("width", 0))
        h   = int(vstream.get("height", 0))
        dur = float(data["format"].get("duration", 0))

        frames_in  = tmp / "in"
        frames_out = tmp / "out"
        frames_in.mkdir()
        frames_out.mkdir()

        # resize daca force1080
        if force1080 and scale == 2:
            target_h = 540
            target_w = int(w * target_h / h) & ~1
            vf = ["-vf", f"scale={target_w}:{target_h}:flags=lanczos"]
        else:
            target_w, target_h = w, h
            vf = []

        cmd_extract = ["ffmpeg", "-i", str(input_path),
                       "-qscale:v", "1", "-qmin", "1"] + vf + [
                       str(frames_in / "frame%08d.png"),
                       "-y", "-loglevel", "error"]
        subprocess.run(cmd_extract, check=True)

        frame_files = sorted(frames_in.glob("*.png"))
        n_frames    = len(frame_files)
        if n_frames == 0:
            raise Exception("Nu s-au extras frames")

        job["message"]    = f"✅ {n_frames} frames extrase"
        job["n_frames"]   = n_frames
        job["progress"]   = 10

        # upscale cu realcugan
        job["status"]  = "upscaling"
        job["message"] = f"Upscaling {n_frames} frames..."

        cugan_exe = find_exe("realesrgan-ncnn-vulkan") or find_exe("realcugan-ncnn-vulkan")
        if not cugan_exe:
            raise Exception("realcugan/realesrgan nu e instalat pe server")

        cmd_up = [cugan_exe,
                  "-i", str(frames_in),
                  "-o", str(frames_out),
                  "-n", "up2x-no-denoise",
                  "-s", str(scale),
                  "-j", "1:2:1"]
        proc = subprocess.Popen(cmd_up, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)

        start = time.time()
        while proc.poll() is None:
            done = len(list(frames_out.glob("*.png")))
            elapsed = time.time() - start
            fps_p   = done / elapsed if elapsed > 0 else 0
            eta     = (n_frames - done) / fps_p if fps_p > 0 else 0
            prog    = 10 + int((done / max(n_frames, 1)) * 80)
            job["progress"] = prog
            job["message"]  = f"Upscaling {done}/{n_frames} ({fps_p:.1f} fr/s) ETA {fmt_time(eta)}"
            job["done"]     = done
            time.sleep(1)

        n_up = len(list(frames_out.glob("*.png")))
        if n_up == 0:
            raise Exception("0 frames upscalate")

        # audio
        job["status"]  = "assembling"
        job["message"] = "Asamblare video..."
        job["progress"] = 92

        audio = tmp / "audio.aac"
        has_audio = subprocess.run(
            ["ffmpeg", "-i", str(input_path), "-vn", "-acodec", "copy",
             str(audio), "-y", "-loglevel", "error"],
            capture_output=True).returncode == 0

        out_path = tmp / f"upscaled_{uuid.uuid4().hex[:8]}.mp4"
        pattern  = str(frames_out / "frame%08d.png")
        cmd_ass  = ["ffmpeg", "-framerate", str(fps), "-i", pattern]
        if has_audio:
            cmd_ass += ["-i", str(audio),
                        "-c:v", "libx264", "-crf", "16", "-preset", "fast",
                        "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd_ass += ["-c:v", "libx264", "-crf", "16", "-preset", "fast"]
        cmd_ass += ["-pix_fmt", "yuv420p", str(out_path),
                    "-y", "-loglevel", "error"]

        subprocess.run(cmd_ass, check=True)

        job["status"]   = "done"
        job["progress"] = 100
        job["message"]  = f"✅ Gata! {n_frames} frames upscalate"
        job["output"]   = str(out_path)
        job["out_size"] = out_path.stat().st_size

    except Exception as e:
        job["status"]  = "error"
        job["message"] = f"❌ Eroare: {e}"
        job["progress"] = 0

# ── routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(open(
        Path(__file__).parent / "static" / "index.html"
    ).read())

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_file(Path(__file__).parent / "static" / filename)

@app.route("/upload", methods=["POST"])
def upload():
    if "video" not in request.files:
        return jsonify({"error": "No file"}), 400

    file      = request.files["video"]
    scale     = int(request.form.get("scale", 2))
    force1080 = request.form.get("force1080", "true").lower() == "true"

    job_id   = uuid.uuid4().hex
    tmp      = UPLOAD_DIR / job_id
    tmp.mkdir(exist_ok=True)
    in_path  = tmp / file.filename
    file.save(str(in_path))

    jobs[job_id] = {
        "status": "queued", "progress": 0,
        "message": "In coada...", "output": None,
        "n_frames": 0, "done": 0
    }

    t = threading.Thread(
        target=process_video,
        args=(job_id, in_path, scale, force1080),
        daemon=True)
    t.start()

    return jsonify({"job_id": job_id})

@app.route("/status/<job_id>")
def status(job_id):
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(jobs[job_id])

@app.route("/download/<job_id>")
def download(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "Not ready"}), 404
    out = job["output"]
    return send_file(out, as_attachment=True,
                     download_name="upscaled.mp4")

@app.route("/ping")
def ping():
    return jsonify({"status": "ok", "ffmpeg": bool(find_exe("ffmpeg")),
                    "cugan": bool(find_exe("realcugan-ncnn-vulkan") or
                                  find_exe("realesrgan-ncnn-vulkan"))})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
