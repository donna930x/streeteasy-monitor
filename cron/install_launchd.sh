#!/bin/bash
#
# Install the StreetEasy monitor as a macOS LaunchAgent that runs every
# 20 minutes (and once on wake if the Mac was asleep at a scheduled time).
#
# Usage:  bash cron/install_launchd.sh
#
set -euo pipefail

LABEL="com.donnya.streeteasy-monitor"
REPO="$(cd "$(dirname "$0")/.." && pwd)"          # repo root
PY="$(command -v python3 || command -v python || true)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ -z "$PY" ]; then
  echo "ERROR: no python3/python on PATH. Install Python or fix your PATH." >&2
  exit 1
fi
if [ ! -f "$REPO/.env" ]; then
  echo "WARNING: $REPO/.env not found — the run will fail to email / write the"
  echo "         sheet until you create it (copy .env.example to .env)."
fi

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$REPO/main.py</string>
  </array>

  <!-- CWD = repo root so config.read_env() finds .env and 'import src' works -->
  <key>WorkingDirectory</key>
  <string>$REPO</string>

  <!-- every 20 minutes; if asleep at the mark, runs once on wake -->
  <key>StartInterval</key>
  <integer>1200</integer>

  <!-- run once immediately when (re)loaded, handy for testing -->
  <key>RunAtLoad</key>
  <true/>

  <key>StandardOutPath</key>
  <string>$REPO/cron/launchd.log</string>
  <key>StandardErrorPath</key>
  <string>$REPO/cron/launchd.log</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
EOF

# Reload cleanly (ignore "not loaded" on first install)
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "Installed and loaded: $LABEL"
echo "  Schedule : every 20 minutes (StartInterval 1200s), runs on wake if missed"
echo "  Python   : $PY"
echo "  Logs     : $REPO/cron/launchd.log"
echo
echo "It just ran once (RunAtLoad). Check the log:"
echo "  tail -n 40 $REPO/cron/launchd.log"
echo "To stop it:  bash cron/uninstall_launchd.sh"
