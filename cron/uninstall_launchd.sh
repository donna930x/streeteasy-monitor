#!/bin/bash
#
# Stop and remove the StreetEasy monitor LaunchAgent.
#
# Usage:  bash cron/uninstall_launchd.sh
#
set -uo pipefail

LABEL="com.donnya.streeteasy-monitor"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ -f "$PLIST" ]; then
  launchctl unload "$PLIST" 2>/dev/null && echo "Unloaded $LABEL" || echo "$LABEL was not loaded"
  rm -f "$PLIST" && echo "Removed $PLIST"
else
  echo "No LaunchAgent found at $PLIST"
fi
