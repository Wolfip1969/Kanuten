#!/usr/bin/env python3
"""Weboberfläche für fotokugel.py.  Start:  python app.py  (öffnet den Browser, im WLAN per QR-Code erreichbar)

    python app.py --nur-lokal   nur auf diesem Rechner erreichbar
"""
import argparse
import json
import secrets
import socket
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from PIL import Image, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

HERE = Path(__file__).resolve().parent
PROJECTS = HERE / "projekte"
PORT = int(os.environ.get("FOTOKUGEL_PORT", "8777"))
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff"}
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac"}
JOBS = {}            # projekt-id -> {"proc", "log", "mode", "started", "done", "ok", "out"}
LOCK = threading.Lock()
TOKEN = secrets.token_urlsafe(9)      # geheimer Schlüssel für Zugriffe aus dem WLAN
LAN_URL = None


def safe_name(name):
    name = Path(unquote(name)).name
    name = re.sub(r"[^\w.\- äöüÄÖÜß()]", "_", name).strip() or "datei"
    return name


def project_dir(pid):
    if not re.fullmatch(r"[a-f0-9]{8}", pid or ""):
        raise ValueError("ungültiges Projekt")
    d = PROJECTS / pid
    (d / "fotos").mkdir(parents=True, exist_ok=True)
    return d


def settings_path(d):
    return d / "einstellungen.json"


def load_settings(d):
    try:
        return json.loads(settings_path(d).read_text())
    except (OSError, ValueError):
        return {}


def photos_of(d):
    return sorted(p for p in (d / "fotos").iterdir() if p.is_file() and p.suffix.lower() in PHOTO_EXTS)


def thumb(d, name):
    src = d / "fotos" / safe_name(name)
    dst = d / "vorschaubilder" / (src.stem + ".jpg")
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        dst.parent.mkdir(exist_ok=True)
        img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
        img.thumbnail((360, 360))
        img.save(dst, quality=85)
    return dst


def reader(pid, proc):
    job = JOBS[pid]
    buf = b""
    while True:
        chunk = proc.stdout.read(256)
        if not chunk:
            break
        buf += chunk
        job["log"] = buf.decode("utf-8", "replace")[-6000:]
    proc.wait()
    job["done"] = True
    job["ok"] = proc.returncode == 0


def progress(job):
    log = job["log"]
    if job["done"]:
        return 100 if job["ok"] else 0
    m = re.findall(r"Bild (\d+)/(\d+)", log)
    if m:
        a, b = map(int, m[-1])
        return 8 + int(90 * a / b)
    m = re.findall(r"Kacheln (\d+)/(\d+)", log)
    if m:
        a, b = map(int, m[-1])
        return int(8 * a / b)
    return 1


def stage(job):
    log = job["log"]
    if job["done"]:
        return "Fertig" if job["ok"] else "Fehler"
    if "Rendere" in log:
        return "Video wird gerendert" if job["mode"] == "video" else "Vorschaubilder werden erstellt"
    if "Kacheln" in log:
        return "Fotos werden zugeschnitten"
    return "Startet"


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, ctype=None, download=False):
        if not path.is_file():
            return self.send_error(404)
        size = path.stat().st_size
        ctype = ctype or {".jpg": "image/jpeg", ".mp4": "video/mp4", ".html": "text/html; charset=utf-8",
                          ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav"}.get(path.suffix.lower(), "application/octet-stream")
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else end
            else:
                start = size - int(m.group(2))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-store")
        if download:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(path.name)}")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def is_local(self):
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def authorized(self, q):
        """Vom Rechner selbst immer, aus dem WLAN nur mit dem Schlüssel aus dem QR-Code."""
        if self.is_local():
            return True
        cookie = self.headers.get("Cookie", "")
        return f"fk={TOKEN}" in cookie or q.get("k") == TOKEN

    def deny(self):
        body = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                "<body style='font:17px -apple-system,sans-serif;padding:32px;max-width:28em'>"
                "<h2>Kein Zugriff</h2><p>Bitte den QR-Code am Rechner scannen. Der Link ändert sich bei jedem Start "
                "der Fotokugel.</p></body>").encode()
        self.send_response(403)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------------------------------------------------------------- GET
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if not self.authorized(q):
            return self.deny()
        try:
            if u.path in ("/", "/index.html"):
                if q.get("k") == TOKEN:                     # Schlüssel als Cookie merken, sauberer Link
                    self.send_response(303)
                    self.send_header("Set-Cookie", f"fk={TOKEN}; Path=/; Max-Age=2592000; SameSite=Strict")
                    self.send_header("Location", "/")
                    self.end_headers()
                    return
                return self.send_file(HERE / "ui.html")
            if u.path == "/lib/qrcode.js":
                return self.send_file(HERE / "node_modules" / "qrcode-generator" / "qrcode.js", "text/javascript")
            if u.path == "/api/info":
                return self.send_json({"lanUrl": LAN_URL if self.is_local() else None, "lokal": self.is_local()})
            if u.path == "/api/projekt":
                d = project_dir(q.get("id"))
                s = load_settings(d)
                ph = photos_of(d)
                music = next((p for p in d.iterdir() if p.suffix.lower() in AUDIO_EXTS), None)
                return self.send_json({
                    "fotos": [p.name for p in ph],
                    "musik": music.name if music else None,
                    "einstellungen": s,
                    "ergebnis": self.results(d),
                })
            if u.path == "/api/thumb":
                return self.send_file(thumb(project_dir(q["id"]), q["name"]), "image/jpeg")
            if u.path == "/api/datei":
                d = project_dir(q["id"])
                rel = Path(unquote(q["pfad"]))
                if ".." in rel.parts:
                    return self.send_error(403)
                return self.send_file(d / rel, download=q.get("download") == "1")
            if u.path == "/api/status":
                job = JOBS.get(q.get("id"))
                if not job:
                    return self.send_json({"laeuft": False})
                return self.send_json({"laeuft": not job["done"], "fertig": job["done"], "ok": job["ok"],
                                       "modus": job["mode"], "prozent": progress(job), "schritt": stage(job),
                                       "log": job["log"][-1500:], "sekunden": int(time.time() - job["started"])})
        except (ValueError, KeyError, OSError) as e:
            return self.send_json({"fehler": str(e)}, 400)
        return self.send_error(404)

    def results(self, d):
        out = {}
        vids = sorted((d / "ergebnis").glob("*.mp4"), key=lambda p: p.stat().st_mtime) if (d / "ergebnis").exists() else []
        if vids:
            out["video"] = "ergebnis/" + vids[-1].name
            out["videoZeit"] = int(vids[-1].stat().st_mtime)
        st = d / "fotos" / "fotokugel_vorschau"
        if st.exists():
            out["standbilder"] = ["fotos/fotokugel_vorschau/" + p.name for p in sorted(st.glob("*.jpg"))]
            out["standbilderZeit"] = int(max((p.stat().st_mtime for p in st.glob("*.jpg")), default=0))
        return out

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if not self.authorized(q):
            return self.deny()
        try:
            if u.path == "/api/neu":
                pid = uuid.uuid4().hex[:8]
                project_dir(pid)
                return self.send_json({"id": pid})
            length = int(self.headers.get("Content-Length", 0))
            if u.path == "/api/upload":
                d = project_dir(q["id"])
                name = safe_name(q["name"])
                ext = Path(name).suffix.lower()
                if q.get("art") == "musik":
                    if ext not in AUDIO_EXTS:
                        return self.send_json({"fehler": "Bitte MP3, M4A oder WAV wählen."}, 400)
                    for old in d.iterdir():
                        if old.suffix.lower() in AUDIO_EXTS:
                            old.unlink()
                    target = d / name
                else:
                    if ext not in PHOTO_EXTS:
                        return self.send_json({"fehler": f"{name}: kein unterstütztes Foto"}, 400)
                    target = d / "fotos" / name
                with open(target, "wb") as f:
                    left = length
                    while left > 0:
                        chunk = self.rfile.read(min(1 << 20, left))
                        if not chunk:
                            break
                        f.write(chunk)
                        left -= len(chunk)
                return self.send_json({"ok": True, "name": name})
            body = json.loads(self.rfile.read(length) or b"{}")
            if u.path == "/api/loeschen":
                d = project_dir(body["id"])
                if body.get("musik"):
                    for old in d.iterdir():
                        if old.suffix.lower() in AUDIO_EXTS:
                            old.unlink()
                for n in body.get("fotos", []):
                    p = d / "fotos" / safe_name(n)
                    if p.is_file():
                        p.unlink()
                return self.send_json({"ok": True})
            if u.path == "/api/einstellungen":
                d = project_dir(body["id"])
                settings_path(d).write_text(json.dumps(body.get("einstellungen", {})))
                return self.send_json({"ok": True})
            if u.path == "/api/start":
                return self.start(body)
            if u.path == "/api/abbrechen":
                job = JOBS.get(body.get("id"))
                if job and not job["done"]:
                    if os.name == "nt":
                        job["proc"].send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        os.killpg(job["proc"].pid, signal.SIGTERM)   # auch Node und ffmpeg beenden
                return self.send_json({"ok": True})
        except (ValueError, KeyError, OSError) as e:
            return self.send_json({"fehler": str(e)}, 400)
        return self.send_error(404)

    def start(self, body):
        pid = body["id"]
        d = project_dir(pid)
        s = body.get("einstellungen", {})
        settings_path(d).write_text(json.dumps(s))
        with LOCK:
            job = JOBS.get(pid)
            if job and not job["done"]:
                return self.send_json({"fehler": "Es läuft bereits ein Auftrag."}, 409)
            ph = photos_of(d)
            if len(ph) < 2:
                return self.send_json({"fehler": "Bitte mindestens 2 Fotos hinzufügen."}, 400)
            mode = body.get("modus", "video")
            fmt = s.get("format", "reel")
            (d / "ergebnis").mkdir(exist_ok=True)
            out = d / "ergebnis" / f"fotokugel_{fmt}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
            cmd = [sys.executable, "-u", str(HERE / "fotokugel.py"), str(d / "fotos"),
                   "--format", fmt, "--dauer", str(float(s.get("dauer", 25))),
                   "--fps", str(int(s.get("fps", 30))), "--fugen", s.get("fugen", "weiss"),
                   "--ende-bild", s.get("endeBild", "ganz"), "--qualitaet", s.get("qualitaet", "max"),
                   "--seed", str(int(s.get("seed", 7))), "--ausgabe", str(out)]
            ende = s.get("ende")
            if ende and (d / "fotos" / ende).exists():
                cmd += ["--ende", ende]
            if s.get("sw"):
                cmd.append("--sw")
            music = next((p for p in d.iterdir() if p.suffix.lower() in AUDIO_EXTS), None)
            if music and s.get("musikAn", True):
                cmd += ["--musik", str(music), "--musik-start", str(float(s.get("musikStart", 0)))]
            if mode == "standbilder":
                cmd.append("--standbilder")
            if sys.platform == "darwin" and shutil.which("caffeinate"):
                cmd = ["caffeinate", "-i", "-s"] + cmd           # Mac schläft beim Rendern nicht ein
            proc = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                                       else {"start_new_session": True}))
            JOBS[pid] = {"proc": proc, "log": "", "mode": mode, "started": time.time(), "done": False, "ok": False}
            threading.Thread(target=reader, args=(pid, proc), daemon=True).start()
        return self.send_json({"ok": True})


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.168.0.1", 9))                  # sendet nichts, ermittelt nur die eigene Adresse
            ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def main():
    global LAN_URL
    ap = argparse.ArgumentParser()
    ap.add_argument("--nur-lokal", action="store_true", help="nicht im WLAN freigeben")
    args = ap.parse_args()
    PROJECTS.mkdir(exist_ok=True)
    missing = [n for n in ("ffmpeg", "node") if not shutil.which(n)]
    if missing:
        print("Achtung, nicht gefunden:", ", ".join(missing), "(siehe README)")
    if not (HERE / "node_modules" / "three").exists():
        print("Achtung: im Ordner fotokugel einmal  npm install  ausführen")
    httpd = ThreadingHTTPServer(("127.0.0.1" if args.nur_lokal else "0.0.0.0", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Fotokugel läuft auf {url}  (Beenden mit Strg+C)")
    ip = None if args.nur_lokal else lan_ip()
    if ip:
        LAN_URL = f"http://{ip}:{PORT}/?{urlencode({'k': TOKEN})}"
        print(f"Am iPhone (gleiches WLAN): {LAN_URL}")
        print("  oder einfach den QR-Code in der Oberfläche scannen.")
    if not os.environ.get("FOTOKUGEL_KEIN_BROWSER"):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")


if __name__ == "__main__":
    main()
