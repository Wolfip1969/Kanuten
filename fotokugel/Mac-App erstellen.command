#!/bin/bash
# Erzeugt "Fotokugel.app" im Programme-Ordner des Benutzers. Einmal per Doppelklick ausführen.
# Die App startet die Fotokugel im Hintergrund (falls sie nicht schon läuft) und öffnet die Oberfläche.
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
APP="$HOME/Applications/Fotokugel.app"
mkdir -p "$HOME/Applications"

PY="$(command -v python3)"
SCRIPT="export PATH=/opt/homebrew/bin:/usr/local/bin:\$PATH
cd '$DIR'
if ! curl -s -o /dev/null --max-time 1 http://127.0.0.1:8777/; then
  FOTOKUGEL_KEIN_BROWSER=1 nohup '$PY' app.py --wach > /tmp/fotokugel.log 2>&1 &
  for i in 1 2 3 4 5 6 7 8 9 10; do sleep 0.5; curl -s -o /dev/null --max-time 1 http://127.0.0.1:8777/ && break; done
fi
open http://127.0.0.1:8777/"

# AppleScript-Hülle bauen
ESCAPED=$(printf '%s' "$SCRIPT" | sed 's/\\/\\\\/g; s/"/\\"/g')
rm -rf "$APP"
osacompile -o "$APP" -e "do shell script \"$ESCAPED\""

# Symbol setzen
ICONSET="$(mktemp -d)/Fotokugel.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s icons/icon-512.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2)); [ $d -le 512 ] && sips -z $d $d icons/icon-512.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/applet.icns"
touch "$APP"

echo ""
echo "Fertig: $APP"
echo "Tipp: Die App ins Dock ziehen. Beenden über den Knopf „Beenden“ in der Oberfläche."
open -R "$APP"
