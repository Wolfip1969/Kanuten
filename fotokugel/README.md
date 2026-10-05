# Fotokugel

Aus einem Ordner mit Fotos wird ein kurzes Video:

1. Die Fotos ploppen als **Videowand** auf.
2. Die Wand biegt sich zum Zylinder und wird zur **rotierenden Kugel**.
3. Die Kugel bremst ab, die Kamera fliegt in das **Endbild**, das am Schluss den ganzen Bildschirm füllt.

Gleiche Fotos liegen nie direkt nebeneinander, auch nicht über die Naht der Kugel hinweg. Bei vielen Fotos wird das Raster automatisch größer (162, 288 oder 450 Kacheln).

## Einrichten (einmalig)

Du brauchst **Python 3.9+**, **Node.js 18+** und **ffmpeg**.

**Mac**: Zuerst [Homebrew](https://brew.sh) installieren. Dazu im Terminal den Befehl von der Homebrew-Startseite einfügen. Dann:

```bash
brew install python node ffmpeg
```

Den Ordner `fotokugel` auf den Mac holen, zum Beispiel über GitHub mit „Code“ → „Download ZIP“ und dann entpacken. Im Terminal mit `cd` in den Ordner wechseln, am einfachsten `cd ` tippen und den Ordner ins Terminalfenster ziehen.

**Windows**: Python von python.org, Node.js von nodejs.org und ffmpeg mit `winget install ffmpeg` installieren.

Danach im Ordner `fotokugel`:

```bash
npm install
npx playwright install chromium
pip3 install pillow numpy "opencv-python-headless<5"
```

`opencv` ist optional. Damit werden die Kacheln so zugeschnitten, dass das Gesicht drin ist. Für iPhone-HEIC-Fotos zusätzlich `pip install pillow-heif`.

## Als App auf dem Mac

Einmal **`Mac-App erstellen.command`** doppelklicken. Danach liegt **Fotokugel.app** in deinem Programme-Ordner (`~/Programme`), mit eigenem Symbol. Zieh sie ins Dock.

Ein Klick auf die App startet die Fotokugel im Hintergrund und öffnet die Oberfläche. Solange sie läuft, schläft der Mac nicht ein. Beenden kannst du sie über den Knopf **Beenden** oben rechts in der Oberfläche.

Falls macOS beim ersten Öffnen warnt („nicht verifizierter Entwickler“): Rechtsklick auf die App → **Öffnen** → **Öffnen**.

## Als App auf dem iPhone

Seite wie unten beschrieben per QR-Code öffnen, dann in Safari **Teilen** → **Zum Home-Bildschirm**. Die Fotokugel erscheint als App-Symbol und öffnet sich ohne Browserleiste.

## Unterwegs nutzen (Tailscale)

Damit das iPhone den Mac auch außerhalb des WLANs erreicht, ohne dass der Mac im offenen Internet steht:

1. **Tailscale** kostenlos installieren, auf dem Mac aus dem App Store und auf dem iPhone ebenfalls aus dem App Store.
2. Auf beiden Geräten mit **demselben Konto** anmelden, zum Beispiel deinem Google- oder Apple-Konto.
3. In der Fotokugel am Mac auf **Am iPhone öffnen** klicken. Neben „Zuhause“ erscheint jetzt ein zweiter QR-Code **Unterwegs**. Den einmal scannen und als App auf den Home-Bildschirm legen.

Unterwegs muss am iPhone Tailscale eingeschaltet sein (VPN-Symbol oben). Der Mac muss eingeschaltet, wach und mit dem Internet verbunden sein. Zugeklappt im Akkubetrieb schläft er trotzdem ein. Am Netzteil hilft: Systemeinstellungen → Batterie → Optionen → „Automatischen Ruhezustand bei ausgeschaltetem Display verhindern“.

Tailscale verbindet nur deine eigenen Geräte untereinander. Zusätzlich schützt der geheime Schlüssel im QR-Code-Link.

## Weboberfläche

Über die **Fotokugel.app** (siehe oben), per Doppelklick auf **`Fotokugel starten.command`** (Mac) oder **`Fotokugel starten.bat`** (Windows). Alternativ im Terminal `python app.py` starten. Der Browser öffnet sich dann mit `http://127.0.0.1:8777`.

1. **Fotos** ins Fenster ziehen. Ein Klick auf ein Foto macht es zum Endbild (goldener Rahmen).
2. **Format, Länge und Musik** wählen. Mit dem Player findest du die passende Stelle im Song. „Aktuelle Stelle übernehmen“ setzt dort den Startpunkt.
3. **Vorschau** erzeugt in Sekunden 5 Standbilder. **Video erstellen** rendert das fertige Video mit Fortschrittsanzeige.
4. **Video herunterladen**.

Fotos, Musik und Ergebnisse liegen im Unterordner `projekte/` und bleiben auch nach einem Neustart erhalten. Mit „Neues Projekt“ beginnst du von vorn.

### Vom iPhone aus bedienen

Der Mac rechnet, das iPhone ist die Fernbedienung.

1. Fotokugel am Mac starten (Doppelklick auf `Fotokugel starten.command`).
2. Oben rechts auf **Am iPhone öffnen** klicken. Es erscheint ein QR-Code.
3. QR-Code mit der iPhone-Kamera scannen. iPhone und Mac müssen im selben WLAN sein.
4. Am iPhone Fotos aus der Mediathek wählen, Endbild antippen, Video erstellen.
5. **Video herunterladen** antippen. Das Video landet in der App **Dateien** unter Downloads. Dort antippen, dann **Teilen** und **Video sichern**. Danach ist es in Fotos und kann zu Instagram oder CapCut.

Beim ersten Start fragt macOS eventuell, ob Python eingehende Verbindungen annehmen darf. Bitte **Erlauben** wählen, sonst erreicht das iPhone den Mac nicht. Während des Renderns schläft der Mac nicht ein, der Bildschirm darf aber ausgehen.

Musik am iPhone: Wählbar sind nur Dateien aus der App Dateien, zum Beispiel heruntergeladene MP3s. Songs aus Apple Music gehen nicht.

**Sicherheit:** Der Link im QR-Code enthält einen geheimen Schlüssel. Ohne ihn bekommt niemand im WLAN Zugriff. Der Schlüssel steht in der Datei `.schluessel`. Wer sie löscht, bekommt beim nächsten Start einen neuen, dann müssen alle iPhones den QR-Code neu scannen. Hochgeladen wird nur auf deinen Mac, nichts ins Internet. Mit `python app.py --nur-lokal` ist die Oberfläche nur am Mac selbst erreichbar.

## Benutzen im Terminal

```bash
python fotokugel.py <Fotoordner> --ende <Dateiname> --format reel --musik <song.mp3>
```

Das Video landet als `fotokugel_reel.mp4` im Fotoordner.

Ein schneller Test vorab: Mit `--standbilder` entstehen nur 5 Vorschaubilder im Unterordner `fotokugel_vorschau`. Das dauert Sekunden statt Minuten.

### Optionen

| Option | Bedeutung | Standard |
|---|---|---|
| `--ende foto.jpg` | Foto, in das am Ende gezoomt wird | erstes Foto |
| `--format` | `reel` 1080×1920, `quadrat` 1080×1080, `hochformat` 1080×1350, `quer` 1920×1080 | `reel` |
| `--ende-bild` | `ganz`: ganzes Endfoto mit unscharfem Rand, `fuellen`: bildfüllend zuschneiden | `ganz` |
| `--musik song.mp3` | Musik unterlegen, am Ende 1,5 s ausblenden | ohne Ton |
| `--musik-start 32` | ab dieser Sekunde im Song starten | 0 |
| `--dauer 25` | Länge in Sekunden, der ganze Ablauf wird gestreckt oder gestaucht | 25 |
| `--fps 60` | 60 statt 30 Bilder pro Sekunde | 30 |
| `--sw` | Schachbrett Farbe/Schwarz-Weiß mit Farb-Wellen | aus |
| `--fugen` | Farbe zwischen den Kacheln auf der Kugel: `weiss`, `schwarz`, `grau` | `weiss` |
| `--qualitaet vorschau` | schneller, für einen ersten Blick aufs Video | `max` |
| `--seed 3` | andere Zahl ergibt eine andere Verteilung der Fotos | 7 |
| `--ausgabe pfad.mp4` | eigener Dateiname | im Fotoordner |

### Ablauf bei 25 Sekunden

| Zeit | Was passiert |
|---|---|
| 0:00–0:05 | Kacheln ploppen auf, Kamerafahrt über die Wand |
| 0:05–0:09 | Wand wird zum Zylinder, dann zur Kugel |
| 0:09–0:21 | Kugel dreht sich (etwa zwei Umdrehungen) |
| 0:21–0:24 | Kugel bremst, Flug ins Endbild |
| 0:24–0:25 | Endbild steht |

Bei 25 s und Musik mit 120 BPM liegen die Übergänge bei 0:05, 0:07, 0:09 und 0:21,5 jeweils auf einem Schlag.

## Qualität für Instagram

`--qualitaet max` (Standard) rendert in doppelter Auflösung und verkleinert dann. Dadurch werden die Kanten sauber. Kodiert wird mit H.264 High Profile, CRF 16, yuv420p und AAC 320 kbit/s bei 48 kHz. Das entspricht den Upload-Empfehlungen von Instagram. Instagram komprimiert danach selbst noch einmal, mehr Qualität geht also nicht.

Ein Reel mit 25 Sekunden braucht auf einem normalen Rechner etwa 5 bis 15 Minuten.

## Dateien

- `app.py` und `ui.html`: die Weboberfläche
- `Mac-App erstellen.command`: baut die Fotokugel.app
- `icons/`: App-Symbole
- `fotokugel.py`: liest die Fotos, schneidet die Kacheln zu, verteilt sie und startet das Rendern
- `scene.html`: die 3D-Szene (three.js)
- `render.js`: rendert die Szene Bild für Bild im Browser und gibt die Bilder direkt an ffmpeg
- `.arbeit/`: Zwischendateien, kann gelöscht werden
- `projekte/`: Projekte der Weboberfläche (Fotos, Musik, Videos)

## Probleme lösen

**„Executable doesn't exist … headless_shell“** oder `npx playwright install` hängt beim Entpacken: Chromium von Hand nachladen.

```bash
cd ~/Library/Caches/ms-playwright && rm -rf chromium_headless_shell-1194 && mkdir chromium_headless_shell-1194 && cd chromium_headless_shell-1194
curl -L -o hs.zip https://cdn.playwright.dev/dbazure/download/playwright/builds/chromium/1194/chromium-headless-shell-mac-arm64.zip && unzip -q hs.zip && rm hs.zip
```

**iPhone erreicht den Mac nicht:** Prüfen, ob beide im selben WLAN sind und ob macOS die eingehenden Verbindungen für Python erlaubt (Systemeinstellungen → Netzwerk → Firewall → Optionen).

**Protokoll der Mac-App:** `/tmp/fotokugel.log`
