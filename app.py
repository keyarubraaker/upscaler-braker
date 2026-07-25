"""
Anime Video Upscaler - Web Server
Flask backend cu Real-ESRGAN Python (CPU, fara Vulkan)
"""
import os, subprocess, tempfile, shutil, time, threading, uuid, io
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template_string
from flask_cors import CORS
import imageio_ffmpeg

FFMPEG  = imageio_ffmpeg.get_ffmpeg_exe()
FFPROBE = FFMPEG.replace(FFMPEG, FFPROBE)
if not Path(FFPROBE).exists():
    FFPROBE = shutil.which(FFPROBE) or FFMPEG

app = Flask(__name__)
CORS(app)

UPLOAD_DIR = Path(tempfile.gettempdir()) / "anime_upscaler"
UPLOAD_DIR.mkdir(exist_ok=True)

jobs = {}

def fmt_time(s):
    s = max(0, int(s))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s" if h else (f"{m}m {s}s" if m else f"{s}s")

# ── procesare video cu Real-ESRGAN Python ────────────────────────────────────
def upscale_frame_realesrgan(img_np, upsampler, scale):
    """Upscaleaza un frame numpy RGB."""
    import numpy as np
    out, _ = upsampler.enhance(img_np, outscale=scale)
    return out

def process_video(job_id, input_path, scale, force1080):
    job = jobs[job_id]
    tmp = UPLOAD_DIR / job_id
    tmp.mkdir(exist_ok=True)

    try:
        # ── init model ────────────────────────────────────────────────────────
        job["status"]  = "loading_model"
        job["message"] = "Încarc modelul Real-ESRGAN..."
        job["progress"] = 2

        import torch
        import numpy as np
        from PIL import Image as PILImage

        try:
            import torch
            import torch.nn as nn
            import torch.nn.functional as F

            class RDB(nn.Module):
                def __init__(self, c=64, g=32):
                    super().__init__()
                    self.convs = nn.ModuleList([nn.Conv2d(c+i*g, g, 3, 1, 1) for i in range(4)])
                    self.conv5 = nn.Conv2d(c+4*g, c, 3, 1, 1)
                    self.act   = nn.LeakyReLU(0.2, True)
                def forward(self, x):
                    feats = [x]
                    for conv in self.convs:
                        feats.append(self.act(conv(torch.cat(feats, 1))))
                    return self.conv5(torch.cat(feats, 1)) * 0.2 + x

            class RRDB(nn.Module):
                def __init__(self, c=64, g=32):
                    super().__init__()
                    self.rdbs = nn.Sequential(*[RDB(c,g) for _ in range(3)])
                def forward(self, x): return self.rdbs(x) * 0.2 + x

            class RRDBNet(nn.Module):
                def __init__(self, nf=64, nb=6, gc=32):
                    super().__init__()
                    self.conv_first = nn.Conv2d(3, nf, 3, 1, 1)
                    self.body       = nn.Sequential(*[RRDB(nf, gc) for _ in range(nb)])
                    self.conv_body  = nn.Conv2d(nf, nf, 3, 1, 1)
                    self.conv_up1   = nn.Conv2d(nf, nf, 3, 1, 1)
                    self.conv_up2   = nn.Conv2d(nf, nf, 3, 1, 1)
                    self.conv_hr    = nn.Conv2d(nf, nf, 3, 1, 1)
                    self.conv_last  = nn.Conv2d(nf, 3, 3, 1, 1)
                    self.act        = nn.LeakyReLU(0.2, True)
                def forward(self, x):
                    f = self.conv_first(x)
                    f = f + self.conv_body(self.body(f))
                    f = self.act(self.conv_up1(F.interpolate(f, scale_factor=2, mode='nearest')))
                    f = self.act(self.conv_up2(F.interpolate(f, scale_factor=2, mode='nearest')))
                    return self.conv_last(self.act(self.conv_hr(f)))

            device    = torch.device('cpu')
            net       = RRDBNet().to(device)
            model_path = "/tmp/RealESRGAN_anime.pth"

            if not Path(model_path).exists():
                import urllib.request
                job["message"] = "Descarc model anime (~17MB)..."
                urllib.request.urlretrieve(
                    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
                    model_path)

            sd = torch.load(model_path, map_location=device, weights_only=False)
            sd = sd.get('params_ema', sd.get('params', sd))
            net.load_state_dict(sd, strict=True)
            net.eval()

            def upscale_fn(img_np):
                t = torch.from_numpy(img_np.astype('float32')/255).permute(2,0,1).unsqueeze(0)
                with torch.no_grad():
                    o = net(t)
                return (o.squeeze(0).permute(1,2,0).clamp(0,1).numpy()*255).astype('uint8')

            use_realesrgan = True
            job["message"] = "✅ Model Real-ESRGAN anime încărcat"

        except Exception as e:
            job["message"] = f"⚠ Model unavailable ({e}), folosesc Lanczos"
            use_realesrgan = False
            upscale_fn     = None

        # ── video info ────────────────────────────────────────────────────────
        job["status"]  = "extracting"
        job["message"] = "Extrag frames..."
        job["progress"] = 5

        r = subprocess.run(
            [FFPROBE, "-v", "quiet", "-print_format", "json",
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

        # resize dacă force1080
        if force1080 and scale == 2:
            target_h = 540
            target_w = int(w * target_h / h) & ~1
            vf = ["-vf", f"scale={target_w}:{target_h}:flags=lanczos"]
        else:
            target_w, target_h = w, h
            vf = []

        subprocess.run(
            [FFMPEG, "-i", str(input_path),
             "-qscale:v", "1", "-qmin", "1"] + vf +
            [str(frames_in / "frame%08d.png"), "-y", "-loglevel", "error"],
            check=True)

        frame_files = sorted(frames_in.glob("*.png"))
        n_frames    = len(frame_files)
        if n_frames == 0:
            raise Exception("Nu s-au extras frames")

        job["message"]  = f"✅ {n_frames} frames extrase"
        job["n_frames"] = n_frames
        job["progress"] = 10

        # ── upscale frame cu frame ────────────────────────────────────────────
        job["status"]  = "upscaling"
        job["message"] = f"Upscaling {n_frames} frames..."
        start = time.time()

        for i, fp in enumerate(frame_files):
            if job.get("cancelled"):
                return

            img = np.array(PILImage.open(fp).convert("RGB"))

            if use_realesrgan and upscale_fn:
                try:
                    out = upscale_fn(img)
                except Exception:
                    from PIL import Image as PILImage
                    out = np.array(PILImage.fromarray(img).resize(
                        (img.shape[1]*scale, img.shape[0]*scale), PILImage.LANCZOS))
            else:
                from PIL import Image as PILImage
                out = np.array(PILImage.fromarray(img).resize(
                    (img.shape[1]*scale, img.shape[0]*scale), PILImage.LANCZOS))

            PILImage.fromarray(out.astype('uint8')).save(
                str(frames_out / fp.name))

            done    = i + 1
            elapsed = time.time() - start
            fps_p   = done / elapsed if elapsed > 0 else 0
            eta     = (n_frames - done) / fps_p if fps_p > 0 else 0
            prog    = 10 + int((done / n_frames) * 80)

            job["progress"] = prog
            job["message"]  = f"Upscaling {done}/{n_frames} ({fps_p:.1f} fr/s) ETA {fmt_time(eta)}"
            job["done"]     = done

        n_up = len(list(frames_out.glob("*.png")))
        if n_up == 0:
            raise Exception("0 frames upscalate")

        # ── audio + asamblare ─────────────────────────────────────────────────
        job["status"]  = "assembling"
        job["message"] = "Asamblare video..."
        job["progress"] = 92

        audio     = tmp / "audio.aac"
        has_audio = subprocess.run(
            [FFMPEG, "-i", str(input_path), "-vn", "-acodec", "copy",
             str(audio), "-y", "-loglevel", "error"],
            capture_output=True).returncode == 0

        out_path = tmp / f"upscaled_{uuid.uuid4().hex[:8]}.mp4"
        pattern  = str(frames_out / "frame%08d.png")
        cmd_ass  = [FFMPEG, "-framerate", str(fps), "-i", pattern]
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
        job["message"]  = f"✅ Gata! {n_frames} frames"
        job["output"]   = str(out_path)
        job["out_size"] = out_path.stat().st_size

    except Exception as e:
        job["status"]   = "error"
        job["message"]  = f"❌ Eroare: {e}"
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
    return jsonify({"status": "ok", FFMPEG: bool(find_exe(FFMPEG)),
                    "cugan": bool(find_exe("realcugan-ncnn-vulkan") or
                                  find_exe("realesrgan-ncnn-vulkan"))})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
