#!/bin/bash
# Install (or update) VintedFind as a background service on this Mac.
# It starts at login, restarts if it crashes, and keeps the Mac awake while on the charger.
# Re-run after changing the code to update the installed copy.
#   ./install-mac-service.sh            install / update
#   ./install-mac-service.sh uninstall  remove the service (keeps your searches)
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
HOME_DIR="$HOME/.vintedfind"          # outside Google Drive: launchd may not read cloud folders
APP="$HOME_DIR/app"
DATA="$HOME_DIR/data"
LABEL="nl.vintedfind"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_N="$(id -u)"

if [[ "${1:-}" == "uninstall" ]]; then
  launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Service removed. Your data is still in $DATA"
  exit 0
fi

mkdir -p "$APP/static" "$DATA" "$HOME/Library/LaunchAgents"
cp "$SRC/server.py" "$APP/"
cp "$SRC/static/index.html" "$APP/static/"
# Carry over searches/settings from a manual run, only the first time.
if [[ ! -f "$DATA/state.json" && -f "$SRC/data/state.json" ]]; then
  cp "$SRC/data/state.json" "$DATA/state.json"
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <!-- caffeinate -s: prevent sleep while on AC power; normal sleep on battery -->
    <string>/usr/bin/caffeinate</string><string>-s</string>
    <string>/usr/bin/python3</string><string>-u</string><string>$APP/server.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>VINTEDFIND_DATA</key><string>$DATA</string></dict>
  <key>WorkingDirectory</key><string>$APP</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$HOME_DIR/vintedfind.log</string>
  <key>StandardErrorPath</key><string>$HOME_DIR/vintedfind.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || true
# bootout returns before the old instance is gone; bootstrapping too early fails with an I/O error.
for _ in $(seq 1 20); do
  launchctl print "gui/$UID_N/$LABEL" >/dev/null 2>&1 || break
  sleep 0.5
done
launchctl bootstrap "gui/$UID_N" "$PLIST"
echo "VintedFind service installed → http://localhost:8765"
echo "Log: $HOME_DIR/vintedfind.log"
