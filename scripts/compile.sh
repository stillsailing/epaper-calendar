#!/bin/bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "This script accepts no arguments and only compiles the firmware." >&2
  exit 2
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -n "${ARDUINO_CLI_BIN:-}" ]]; then
  arduino_cli_bin="$ARDUINO_CLI_BIN"
elif command -v arduino-cli >/dev/null 2>&1; then
  arduino_cli_bin="$(command -v arduino-cli)"
else
  arduino_cli_bin="/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli"
fi

if [[ ! -x "$arduino_cli_bin" ]]; then
  echo "Arduino CLI not found. Install Arduino IDE or set ARDUINO_CLI_BIN." >&2
  exit 1
fi

mkdir -p "$project_root/.build/epaper_calendar"
exec "$arduino_cli_bin" compile \
  --fqbn esp32:esp32:lolin32 \
  --build-path "$project_root/.build/epaper_calendar" \
  "$project_root/firmware/epaper_calendar"
