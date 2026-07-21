"""
Anime Video Upscaler - Android App
Kivy + KivyMD pentru UI modern
"""
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.utils import get_color_from_hex
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.slider import Slider
from kivy.uix.switch import Switch
from kivy.uix.filechooser import FileChooserListView
from kivy.storage.jsonstore import JsonStore
import threading, time, os, io, requests
from pathlib import Path

BG      = get_color_from_hex("#0d0d1a")
BG2     = get_color_from_hex("#13131f")
BG3     = get_color_from_hex("#1a1a2e")
ACCENT  = get_color_from_hex("#3a86ff")
GREEN   = get_color_from_hex("#2ecc71")
TEXT    = get_color_from_hex("#e0e0ff")
TEXT2   = get_color_from_hex("#8888aa")
RED     = get_color_from_hex("#e74c3c")

Window.clearcolor = BG

store = JsonStore("settings.json")

def load_setting(key, default):
    try:
        return store.get(key)["value"]
    except Exception:
        return default

def save_setting(key, value):
    store.put(key, value=value)


class HomeScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.video_path  = None
        self.is_proc     = False
        self.cancel_flag = False
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))

        # header
        hdr = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))
        hdr.add_widget(Label(text="⚡", font_size=dp(26), size_hint_x=None, width=dp(36)))
        hdr.add_widget(Label(text="Anime Upscaler", font_size=dp(18),
                             bold=True, color=TEXT, halign="left",
                             text_size=(dp(200), None)))
        hdr.add_widget(Label(text="FREE", font_size=dp(11), color=GREEN,
                             size_hint_x=None, width=dp(40)))
        root.add_widget(hdr)

        # stats row
        stats = BoxLayout(size_hint_y=None, height=dp(110), spacing=dp(8))

        self.card_time   = self._stat_card("⏱", "elapsed", "ETA")
        self.card_mid    = self._mid_card()
        self.card_frames = self._stat_card("🎞", "frames", "fr/s")

        stats.add_widget(self.card_time)
        stats.add_widget(self.card_mid)
        stats.add_widget(self.card_frames)
        root.add_widget(stats)

        # progress bar
        from kivy.uix.progressbar import ProgressBar
        self.prog = ProgressBar(max=100, value=0, size_hint_y=None, height=dp(6))
        self.prog_lbl = Label(text="", font_size=dp(11), color=TEXT2,
                              size_hint_y=None, height=dp(18))
        root.add_widget(self.prog)
        root.add_widget(self.prog_lbl)

        # file info
        self.file_lbl = Label(text="Niciun video selectat", font_size=dp(12),
                              color=TEXT2, size_hint_y=None, height=dp(36),
                              halign="center", text_size=(dp(340), None))
        root.add_widget(self.file_lbl)

        # buttons
        self.btn_select = self._btn("📂  Selectează Video", BG3, ACCENT, self.select_video)
        self.btn_start  = self._btn("▶  Start Upscale", ACCENT, TEXT, self.start_upscale)
        self.btn_start.disabled = True
        btn_settings    = self._btn("⚙  Setări", BG3, TEXT2,
                                    lambda x: setattr(self.manager, "current", "settings"))

        root.add_widget(self.btn_select)
        root.add_widget(self.btn_start)
        root.add_widget(btn_settings)

        # log
        sv = ScrollView(size_hint_y=1)
        self.log_lbl = Label(text="[color=#445566]Pornit. Selectează un video.[/color]",
                             markup=True, font_size=dp(11), halign="left",
                             valign="top", text_size=(dp(340), None),
                             size_hint_y=None)
        self.log_lbl.bind(texture_size=lambda i, v: setattr(i, "height", v[1]))
        sv.add_widget(self.log_lbl)
        root.add_widget(sv)

        self.add_widget(root)

    def _stat_card(self, icon, val_id, sub_id):
        card = BoxLayout(orientation="vertical", spacing=dp(2),
                         padding=dp(6))
        card.add_widget(Label(text=icon, font_size=dp(22), color=TEXT2,
                              size_hint_y=None, height=dp(30)))
        val = Label(text="—", font_size=dp(13), bold=True,
                    color=get_color_from_hex("#aaddff"),
                    size_hint_y=None, height=dp(22))
        sub = Label(text="—", font_size=dp(10), color=TEXT2,
                    size_hint_y=None, height=dp(18))
        setattr(self, f"lbl_{val_id}", val)
        setattr(self, f"lbl_{sub_id}", sub)
        card.add_widget(val)
        card.add_widget(sub)
        return card

    def _mid_card(self):
        card = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(8))
        self.mid_icon = Label(text="📂", font_size=dp(36), color=TEXT2,
                              size_hint_y=None, height=dp(48))
        self.mid_lbl  = Label(text="tap pentru\na selecta", font_size=dp(11),
                              color=TEXT2, halign="center",
                              text_size=(dp(130), None),
                              size_hint_y=None, height=dp(40))
        card.add_widget(self.mid_icon)
        card.add_widget(self.mid_lbl)
        from kivy.uix.behaviors import ButtonBehavior
        class TapCard(ButtonBehavior, BoxLayout): pass
        # card e clickabil
        card.bind(on_touch_down=lambda w, t: self.select_video(None) if w.collide_point(*t.pos) else None)
        return card

    def _btn(self, text, bg, fg, cb):
        from kivy.graphics import Color, RoundedRectangle
        btn = Button(text=text, size_hint_y=None, height=dp(48),
                     font_size=dp(15), bold=True,
                     background_color=(0,0,0,0), color=fg)
        with btn.canvas.before:
            Color(*bg)
            btn._rect = RoundedRectangle(pos=btn.pos, size=btn.size, radius=[dp(12)])
        btn.bind(pos=lambda w,v: setattr(w._rect, "pos", v),
                 size=lambda w,v: setattr(w._rect, "size", v))
        btn.bind(on_release=cb)
        return btn

    def select_video(self, *args):
        from android.permissions import request_permissions, Permission
        from android.storage import primary_external_storage_path
        try:
            request_permissions([Permission.READ_EXTERNAL_STORAGE,
                                  Permission.WRITE_EXTERNAL_STORAGE])
        except Exception:
            pass
        self.manager.current = "filepicker"

    def on_file_selected(self, path):
        if not path:
            return
        self.video_path = path
        name = Path(path).name
        if len(name) > 22:
            name = name[:20] + "…"
        self.mid_icon.text = "🎬"
        self.mid_lbl.text  = name
        size_mb = os.path.getsize(path) / 1_048_576
        self.file_lbl.text = f"{name}  •  {size_mb:.1f} MB"
        self.btn_start.disabled = False
        self.log("✅ Video selectat: " + name)

    def log(self, msg, color="#8888bb"):
        ts  = time.strftime("%H:%M:%S")
        cur = self.log_lbl.text
        new = f"{cur}\n[color={color}][{ts}] {msg}[/color]"
        # pastreaza max 40 linii
        lines = new.split("\n")
        if len(lines) > 40:
            lines = lines[-40:]
        self.log_lbl.text = "\n".join(lines)

    def update_stats(self, done, total, elapsed, eta, fps):
        self.lbl_elapsed.text = fmt_time(elapsed)
        self.lbl_ETA.text     = f"ETA: {fmt_time(eta)}"
        self.lbl_frames.text  = f"{done}/{total}"
        self.lbl_frs.text     = f"{fps:.1f}"
        self.prog.value       = (done / total * 100) if total > 0 else 0
        self.prog_lbl.text    = f"Upscaling {done}/{total}  ({fps:.1f} fr/s)"

    def start_upscale(self, *args):
        if self.is_proc:
            self.cancel_flag = True
            self.btn_start.text = "▶  Start Upscale"
            return

        token = load_setting("hf_token", "")
        if not token:
            self.log("❌ Introdu token HuggingFace în Setări!", "#e74c3c")
            self.manager.current = "settings"
            return

        self.is_proc     = True
        self.cancel_flag = False
        self.btn_start.text = "⏹  Oprește"
        threading.Thread(target=self._process, args=(token,), daemon=True).start()

    def _process(self, token):
        scale     = int(load_setting("scale",     2))
        workers   = int(load_setting("workers",   8))
        force1080 = bool(load_setting("force1080", True))

        self.log(f"▶ Start: ×{scale}  workers={workers}  force1080={force1080}")

        # extrage frames cu ffmpeg (daca disponibil) sau VideoFrame
        try:
            frames = self._extract_frames(force1080)
        except Exception as e:
            Clock.schedule_once(lambda dt: self.log(f"❌ Extragere eroare: {e}", "#e74c3c"))
            self._done()
            return

        n = len(frames)
        if n == 0:
            Clock.schedule_once(lambda dt: self.log("❌ 0 frames extrase!", "#e74c3c"))
            self._done()
            return

        Clock.schedule_once(lambda dt: self.log(f"✅ {n} frames extrase."))

        # upscale via HuggingFace
        upscaled = [None] * n
        start_t  = time.time()
        done_cnt = [0]
        errors   = [0]
        lock     = threading.Lock()

        def upscale_one(i, blob):
            url = "https://api-inference.huggingface.co/models/ai-forever/Real-ESRGAN"
            for attempt in range(3):
                try:
                    resp = requests.post(url,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type":  "image/png",
                            "x-wait-for-model": "true",
                        },
                        data=blob, timeout=120)
                    if resp.status_code == 200 and len(resp.content) > 1000:
                        return resp.content
                    elif resp.status_code == 503:
                        time.sleep(3)
                        continue
                    else:
                        break
                except Exception:
                    time.sleep(1)
            return blob  # fallback original

        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(upscale_one, i, frames[i]): i for i in range(n)}
            for fut in as_completed(futs):
                if self.cancel_flag:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                i   = futs[fut]
                res = fut.result()
                upscaled[i] = res
                with lock:
                    done_cnt[0] += 1
                    done = done_cnt[0]
                elapsed = time.time() - start_t
                fps_v   = done / elapsed if elapsed > 0 else 0
                eta     = (n - done) / fps_v if fps_v > 0 else 0
                Clock.schedule_once(
                    lambda dt, d=done, e=elapsed, et=eta, f=fps_v:
                    self.update_stats(d, n, e, et, f))
                if done % max(5, n//20) == 0 or done == n:
                    Clock.schedule_once(
                        lambda dt, d=done, f=fps_v, e=fmt_time(eta):
                        self.log(f"  [{d}/{n}]  {f:.1f} fr/s  ETA {e}"))

        # salveaza frames upscalate
        out_dir = Path(self.video_path).parent / "upscaled_frames"
        out_dir.mkdir(exist_ok=True)
        for i, data in enumerate(upscaled):
            if data:
                (out_dir / f"frame_{i+1:06d}.png").write_bytes(data)

        Clock.schedule_once(lambda dt: self.log(
            f"✅ Gata! Frames salvate în:\n{out_dir}", "#2ecc71"))
        self._done()

    def _extract_frames(self, force1080):
        """Extrage frames din video ca PNG bytes."""
        import subprocess
        out_dir = Path(self.video_path).parent / "frames_tmp"
        out_dir.mkdir(exist_ok=True)

        vf = "scale=960:540:flags=lanczos" if force1080 else "null"
        cmd = ["ffmpeg", "-i", self.video_path,
               "-vf", vf, "-qscale:v", "1",
               str(out_dir / "frame%06d.png"),
               "-y", "-loglevel", "error"]
        subprocess.run(cmd, check=True)
        frames = []
        for f in sorted(out_dir.glob("*.png")):
            frames.append(f.read_bytes())
            f.unlink()
        out_dir.rmdir()
        return frames

    def _done(self):
        self.is_proc = False
        Clock.schedule_once(lambda dt: setattr(self.btn_start, "text", "▶  Start Upscale"))


class SettingsScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))

        # header
        hdr = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        back = Button(text="← Înapoi", size_hint_x=None, width=dp(100),
                      font_size=dp(13), color=TEXT2,
                      background_color=(0,0,0,0))
        back.bind(on_release=lambda x: setattr(self.manager, "current", "home"))
        hdr.add_widget(back)
        hdr.add_widget(Label(text="⚙  Setări", font_size=dp(17), bold=True, color=TEXT))
        root.add_widget(hdr)

        sv = ScrollView()
        content = BoxLayout(orientation="vertical", spacing=dp(12),
                            size_hint_y=None, padding=[0, 0, 0, dp(20)])
        content.bind(minimum_height=content.setter("height"))

        # token
        content.add_widget(self._section("☁ HuggingFace Token (gratuit)"))
        content.add_widget(Label(
            text="huggingface.co → Settings → Access Tokens → New token",
            font_size=dp(11), color=TEXT2, size_hint_y=None, height=dp(32),
            halign="left", text_size=(dp(340), None)))
        self.token_input = TextInput(
            text=load_setting("hf_token", ""),
            hint_text="hf_...", password=True,
            size_hint_y=None, height=dp(44),
            background_color=BG3, foreground_color=TEXT,
            font_size=dp(13), multiline=False)
        content.add_widget(self.token_input)

        btn_test = Button(text="Test Token", size_hint_y=None, height=dp(38),
                          font_size=dp(13), color=ACCENT,
                          background_color=BG3)
        btn_test.bind(on_release=self.test_token)
        content.add_widget(btn_test)
        self.token_status = Label(text="", font_size=dp(11), color=TEXT2,
                                  size_hint_y=None, height=dp(24))
        content.add_widget(self.token_status)

        # force 1080p
        content.add_widget(self._section("⚡ Force 1080p output"))
        row1080 = BoxLayout(size_hint_y=None, height=dp(44))
        row1080.add_widget(Label(
            text="Resize→540p, upscale×2=1080p (mai rapid)",
            font_size=dp(12), color=TEXT2))
        self.sw_1080 = Switch(active=bool(load_setting("force1080", True)),
                              size_hint_x=None, width=dp(70))
        row1080.add_widget(self.sw_1080)
        content.add_widget(row1080)

        # workers
        content.add_widget(self._section("🔄 Requests paralele"))
        self.lbl_workers = Label(
            text=f"Workers: {int(load_setting('workers', 8))}",
            font_size=dp(12), color=TEXT2, size_hint_y=None, height=dp(24))
        content.add_widget(self.lbl_workers)
        self.sl_workers = Slider(min=1, max=16,
                                 value=int(load_setting("workers", 8)),
                                 size_hint_y=None, height=dp(36))
        self.sl_workers.bind(value=lambda s, v: setattr(
            self.lbl_workers, "text", f"Workers: {int(v)}"))
        content.add_widget(self.sl_workers)

        # scale
        content.add_widget(self._section("📐 Scale factor"))
        scale_row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        self.btn_s2 = Button(text="×2", font_size=dp(15), bold=True,
                             background_color=ACCENT, color=TEXT)
        self.btn_s4 = Button(text="×4", font_size=dp(15), bold=True,
                             background_color=BG3, color=TEXT2)
        self.btn_s2.bind(on_release=lambda x: self._set_scale(2))
        self.btn_s4.bind(on_release=lambda x: self._set_scale(4))
        scale_row.add_widget(self.btn_s2)
        scale_row.add_widget(self.btn_s4)
        content.add_widget(scale_row)
        self._set_scale(int(load_setting("scale", 2)))

        # save
        btn_save = Button(text="💾  Salvează", size_hint_y=None, height=dp(50),
                          font_size=dp(15), bold=True,
                          background_color=GREEN, color=(0,0,0,1))
        btn_save.bind(on_release=self.save)
        content.add_widget(btn_save)

        sv.add_widget(content)
        root.add_widget(sv)
        self.add_widget(root)

    def _section(self, text):
        return Label(text=text, font_size=dp(14), bold=True, color=TEXT,
                     size_hint_y=None, height=dp(32),
                     halign="left", text_size=(dp(340), None))

    def _set_scale(self, s):
        self._scale = s
        self.btn_s2.background_color = ACCENT if s == 2 else BG3
        self.btn_s4.background_color = ACCENT if s == 4 else BG3
        self.btn_s2.color = TEXT if s == 2 else TEXT2
        self.btn_s4.color = TEXT if s == 4 else TEXT2

    def test_token(self, *args):
        token = self.token_input.text.strip()
        if not token:
            self.token_status.color = get_color_from_hex("#f39c12")
            self.token_status.text  = "⚠ Introdu token-ul mai întâi"
            return
        self.token_status.color = TEXT2
        self.token_status.text  = "⏳ Testez…"
        threading.Thread(target=self._do_test, args=(token,), daemon=True).start()

    def _do_test(self, token):
        try:
            r = requests.get("https://huggingface.co/api/whoami",
                             headers={"Authorization": f"Bearer {token}"}, timeout=10)
            if r.status_code == 200:
                name = r.json().get("name", "user")
                Clock.schedule_once(lambda dt: (
                    setattr(self.token_status, "color", GREEN),
                    setattr(self.token_status, "text", f"✅ Conectat: {name}")))
            else:
                Clock.schedule_once(lambda dt: (
                    setattr(self.token_status, "color", RED),
                    setattr(self.token_status, "text", "❌ Token invalid!")))
        except Exception as e:
            Clock.schedule_once(lambda dt: (
                setattr(self.token_status, "color", RED),
                setattr(self.token_status, "text", f"❌ {str(e)[:40]}")))

    def save(self, *args):
        save_setting("hf_token",   self.token_input.text.strip())
        save_setting("force1080",  self.sw_1080.active)
        save_setting("workers",    int(self.sl_workers.value))
        save_setting("scale",      self._scale)
        self.token_status.color = GREEN
        self.token_status.text  = "✅ Salvat!"
        Clock.schedule_once(lambda dt: setattr(self.manager, "current", "home"), 0.8)


class FilePickerScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        hdr  = BoxLayout(size_hint_y=None, height=dp(44))
        back = Button(text="← Înapoi", size_hint_x=None, width=dp(100),
                      background_color=(0,0,0,0), color=TEXT2, font_size=dp(13))
        back.bind(on_release=lambda x: setattr(self.manager, "current", "home"))
        hdr.add_widget(back)
        hdr.add_widget(Label(text="Selectează video", font_size=dp(16),
                             bold=True, color=TEXT))
        root.add_widget(hdr)

        try:
            from android.storage import primary_external_storage_path
            start = primary_external_storage_path()
        except Exception:
            start = os.path.expanduser("~")

        fc = FileChooserListView(path=start,
                                  filters=["*.mp4","*.mkv","*.avi","*.mov","*.webm"],
                                  size_hint_y=1)
        fc.bind(selection=self.on_select)
        root.add_widget(fc)
        self.add_widget(root)

    def on_select(self, chooser, selection):
        if selection:
            path = selection[0]
            home = self.manager.get_screen("home")
            home.on_file_selected(path)
            self.manager.current = "home"


def fmt_time(s):
    s = max(0, int(s))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h: return f"{h}h {m}m {s}s"
    if m: return f"{m}m {s}s"
    return f"{s}s"


class AnimeUpscalerApp(App):
    def build(self):
        self.title = "Anime Upscaler"
        sm = ScreenManager()
        sm.add_widget(HomeScreen(name="home"))
        sm.add_widget(SettingsScreen(name="settings"))
        sm.add_widget(FilePickerScreen(name="filepicker"))
        return sm


if __name__ == "__main__":
    AnimeUpscalerApp().run()
