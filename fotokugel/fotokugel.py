#!/usr/bin/env python3
"""Fotokugel: Fotos werden zur Videowand, die sich in eine rotierende Kugel verwandelt.

Beispiel:
    python fotokugel.py ~/Bilder/Shooting --ende IMG_0412.jpg --format reel --musik song.mp3
"""
import argparse
import hashlib
import http.server
import json
import math
import os
import random
import shutil
import subprocess
import sys
import threading
from functools import partial
from pathlib import Path

try:
    from PIL import Image, ImageFilter, ImageOps
except ImportError:
    sys.exit("Pillow fehlt. Installieren mit:  pip install pillow numpy")

try:
    import pillow_heif  # optional: iPhone-HEIC-Fotos
    pillow_heif.register_heif_opener()
except ImportError:
    pass

try:
    import cv2  # optional: Gesichtserkennung für bessere Zuschnitte (opencv < 5)
    import numpy as np
    if not hasattr(cv2, "CascadeClassifier"):
        cv2 = None
except ImportError:
    cv2 = None

HERE = Path(__file__).resolve().parent
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff"}
FORMATS = {"reel": (1080, 1920), "quadrat": (1080, 1080), "hochformat": (1080, 1350), "quer": (1920, 1080)}
COLORS = {"weiss": "#f6f6f6", "schwarz": "#0d0d0d", "grau": "#9a9a9a"}
TILE = 512


# --- Zuschnitt -----------------------------------------------------------------
_face_cascade = None


def face_center(img):
    """Mitte des größten Gesichts (x, y) oder None."""
    global _face_cascade
    if cv2 is None:
        return None
    if _face_cascade is None:
        _face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    small = img.copy()
    small.thumbnail((800, 800))
    gray = np.asarray(small.convert("L"))
    faces = _face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(40, 40))
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    s = img.width / small.width
    return ((x + w / 2) * s, (y + h / 2) * s)


def crop_box(img, aspect):
    """Ausschnitt mit Seitenverhältnis `aspect` (B/H), Gesicht im oberen Drittel, sonst sinnvolle Mitte."""
    w, h = img.size
    if w / h > aspect:
        cw, ch = h * aspect, h
    else:
        cw, ch = w, w / aspect
    fc = face_center(img)
    if fc:
        cx, cy = fc[0], fc[1] + ch * 0.12          # Gesicht etwas über der Mitte
    else:
        cx, cy = w / 2, (ch / 2 + (h - ch) * 0.25) if h > w else h / 2
    x = min(max(cx - cw / 2, 0), w - cw)
    y = min(max(cy - ch / 2, 0), h - ch)
    return (round(x), round(y), round(x + cw), round(y + ch))


def end_frame(img, W, H, mode):
    """Endbild in Zielgröße: 'ganz' = komplettes Foto mit weichgezeichnetem Hintergrund, 'fuellen' = Zuschnitt."""
    if mode == "fuellen":
        return img.crop(crop_box(img, W / H)).resize((W, H), Image.LANCZOS)
    bg = img.crop(crop_box(img, W / H)).resize((W // 4, H // 4), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(18)).resize((W, H), Image.LANCZOS)
    s = min(W / img.width, H / img.height)
    fg = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    return bg


def load(path):
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)            # Handyfotos richtig drehen
    return img.convert("RGB")


# --- Raster ----------------------------------------------------------------------
def grid_size(n):
    for cols, rows in ((18, 9), (24, 12), (30, 15)):
        if cols * rows >= n:
            return cols, rows
    return 30, 15


def build_grid(n, cols, rows, end_idx, bw, seed):
    """Verteilt n Fotos so, dass gleiche Fotos möglichst weit auseinander liegen (auch über die Kugelnaht)."""
    rnd = random.Random(seed)
    cells = [(r, c) for r in range(rows) for c in range(cols)]
    end_cell = (rows // 2, cols // 2 - (1 if (rows // 2 + cols // 2) % 2 else 0))
    pool = list(range(n))
    rnd.shuffle(pool)
    assign = {}
    order = [c for c in cells if c != end_cell]
    rnd.shuffle(order)
    assign[end_cell] = end_idx
    rest = [i for i in pool if i != end_idx] or [end_idx]
    k = 0
    for c in order:
        assign[c] = rest[k % len(rest)]
        k += 1
    mind = 3 if n >= 30 else 2 if n >= 12 else 1

    def cd(a, b):
        dc = abs(a[1] - b[1])
        return max(abs(a[0] - b[0]), min(dc, cols - dc))

    near = {c: [d for d in cells if d != c and cd(c, d) <= mind] for c in cells}

    def cost(c):
        return sum((mind + 1 - cd(c, d)) * 10 for d in near[c] if assign[d] == assign[c])

    temp = 20.0
    for _ in range(min(200000, 900 * len(cells))):
        a, b = rnd.sample(order, 2)
        if assign[a] == assign[b]:
            continue
        before = cost(a) + cost(b)
        assign[a], assign[b] = assign[b], assign[a]
        delta = cost(a) + cost(b) - before
        if delta > 0 and rnd.random() >= math.exp(-delta / temp):
            assign[a], assign[b] = assign[b], assign[a]
        temp = max(0.05, temp * 0.99995)
    clashes = sum(1 for c in cells for d in near[c] if assign[d] == assign[c]) // 2
    return [[assign[(r, c)] for c in range(cols)] for r in range(rows)], {"r": end_cell[0], "c": end_cell[1]}, clashes


# --- Server ----------------------------------------------------------------------
class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(root):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    ap = argparse.ArgumentParser(description="Fotos -> Videowand -> rotierende Kugel -> Zoom aufs Endbild")
    ap.add_argument("ordner", help="Verzeichnis mit den Fotos")
    ap.add_argument("--ende", help="Dateiname des Endbilds (Standard: erstes Foto)")
    ap.add_argument("--ende-bild", choices=["ganz", "fuellen"], default="ganz",
                    help="ganz = ganzes Foto mit unscharfem Rand (Standard), fuellen = bildfüllend zuschneiden")
    ap.add_argument("--format", choices=FORMATS, default="reel", help="reel=1080x1920, quadrat, hochformat=1080x1350, quer")
    ap.add_argument("--dauer", type=float, default=25, help="Länge in Sekunden (Standard 25)")
    ap.add_argument("--fps", type=int, default=30, choices=[30, 60])
    ap.add_argument("--musik", help="MP3/M4A/WAV, wird untergelegt und am Ende ausgeblendet")
    ap.add_argument("--musik-start", type=float, default=0, help="Startpunkt im Song in Sekunden")
    ap.add_argument("--sw", action="store_true", help="Schachbrett Farbe/SW mit Farb-Wellen")
    ap.add_argument("--fugen", choices=COLORS, default="weiss", help="Farbe zwischen den Kacheln auf der Kugel")
    ap.add_argument("--qualitaet", choices=["max", "vorschau"], default="max")
    ap.add_argument("--standbilder", action="store_true", help="nur 5 Vorschaubilder statt Video")
    ap.add_argument("--ausgabe", help="Zieldatei (Standard: fotokugel_<format>.mp4 im Fotoordner)")
    ap.add_argument("--seed", type=int, default=7, help="andere Zahl = andere Verteilung der Fotos")
    args = ap.parse_args()

    src = Path(args.ordner).expanduser().resolve()
    photos = sorted(p for p in src.iterdir() if p.suffix.lower() in EXTS and not p.name.startswith("."))
    if not photos:
        sys.exit(f"Keine Fotos in {src} gefunden.")
    end_photo = photos[0]
    if args.ende:
        hits = [p for p in photos if p.name == args.ende or p.stem == Path(args.ende).stem]
        if not hits:
            sys.exit(f"Endbild '{args.ende}' nicht im Ordner gefunden.")
        end_photo = hits[0]
    ffmpeg = shutil.which("ffmpeg") or sys.exit("ffmpeg nicht gefunden. Bitte installieren (siehe README).")
    node = shutil.which("node") or sys.exit("Node.js nicht gefunden. Bitte installieren (siehe README).")
    if not (HERE / "node_modules" / "three").exists():
        sys.exit("Abhängigkeiten fehlen. Im Ordner fotokugel einmal ausführen:  npm install")

    W, H = FORMATS[args.format]
    work = HERE / ".arbeit" / f"{src.name}_{hashlib.md5(str(src).encode()).hexdigest()[:6]}"
    if work.exists():
        shutil.rmtree(work)
    (work / "tiles").mkdir(parents=True)
    print(f"{len(photos)} Fotos, Endbild: {end_photo.name}, Format {W}x{H}")
    if cv2 is None:
        print('  Hinweis: ohne opencv kein Gesichts-Zuschnitt (pip install "opencv-python-headless<5")')

    tiles, tiles_bw = [], []
    end_idx = photos.index(end_photo)
    for i, p in enumerate(photos):
        img = load(p)
        t = img.crop(crop_box(img, 1.0)).resize((TILE, TILE), Image.LANCZOS)
        t.save(work / "tiles" / f"{i:04d}.jpg", quality=92)
        tiles.append(f"tiles/{i:04d}.jpg")
        if args.sw:
            ImageOps.grayscale(t).convert("RGB").save(work / "tiles" / f"{i:04d}_sw.jpg", quality=92)
            tiles_bw.append(f"tiles/{i:04d}_sw.jpg")
        if i == end_idx:
            img.crop(crop_box(img, 1.0)).resize((1600, 1600), Image.LANCZOS).save(work / "end_tile.jpg", quality=94)
            end_frame(img, W, H, args.ende_bild).save(work / "end_frame.jpg", quality=95)
        print(f"\r  Kacheln {i + 1}/{len(photos)}", end="", flush=True)
    print()

    cols, rows = grid_size(len(photos))
    if len(photos) > cols * rows:
        print(f"  Hinweis: nur {cols * rows} von {len(photos)} Fotos passen auf die Kugel")
    grid, end_cell, clashes = build_grid(len(photos), cols, rows, end_idx, args.sw, args.seed)
    print(f"  Raster {cols}x{rows} = {cols * rows} Kacheln" + (f", {clashes} nahe Wiederholungen" if clashes else ""))

    ss, crf = (2, 16) if args.qualitaet == "max" else (1, 23)
    out = Path(args.ausgabe).expanduser().resolve() if args.ausgabe else src / f"fotokugel_{args.format}.mp4"
    silent = work / "video_ohne_ton.mp4"
    stills_dir = src / "fotokugel_vorschau"
    job = {
        "width": W, "height": H, "supersample": ss, "fps": args.fps, "duration": args.dauer,
        "cols": cols, "rows": rows, "grid": grid, "end": end_cell, "seed": args.seed,
        "tiles": tiles, "tilesBw": tiles_bw, "bw": args.sw,
        "endTile": "end_tile.jpg", "endFrame": "end_frame.jpg",
        "background": "#000000", "gapColor": COLORS[args.fugen],
        "ffmpeg": ffmpeg, "videoOut": str(silent if args.musik else out),
        # Instagram: H.264 High, yuv420p, konstante Bildrate, faststart
        "videoArgs": ["-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-profile:v", "high",
                      "-level:v", "4.2", "-pix_fmt", "yuv420p", "-r", str(args.fps), "-g", str(args.fps * 2),
                      "-movflags", "+faststart"],
        "stills": [round(x * args.dauer / 25, 2) for x in (4.8, 8.0, 12.0, 21.0, 24.5)],
        "stillsDir": str(stills_dir),
    }
    stills_dir.mkdir(exist_ok=True)
    (work / "job.json").write_text(json.dumps(job))

    httpd = serve(HERE)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/scene.html?job=/.arbeit/{work.name}/"
    mode = "stills" if args.standbilder else "video"
    print("Rendere " + ("Standbilder" if mode == "stills" else f"Video ({args.qualitaet}) ..."))
    r = subprocess.run([node, str(HERE / "render.js"), url, str(work / "job.json"), mode], cwd=HERE)
    httpd.shutdown()
    if r.returncode != 0:
        sys.exit("Rendern fehlgeschlagen.")
    if mode == "stills":
        print(f"Fertig: Standbilder liegen in {stills_dir}")
        return

    if args.musik:
        fade = min(1.5, args.dauer / 5)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(silent),
                        "-ss", str(args.musik_start), "-t", str(args.dauer), "-i", str(Path(args.musik).expanduser()),
                        "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                        "-af", f"afade=t=in:d=0.3,afade=t=out:st={args.dauer - fade}:d={fade}",
                        "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out)],
                       check=True)
    print(f"Fertig: {out}")


if __name__ == "__main__":
    main()
