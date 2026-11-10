#!/bin/bash
# Write packed calendar pages to the "calendar" partition of a connected board.
# This programs hardware; scripts/compile.sh stays build-only.
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 /dev/cu.usbserial-XXXX [calendar-data.bin]" >&2
  exit 2
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port="$1"
data="${2:-$project_root/.build/calendar-data.bin}"
partitions="$project_root/firmware/epaper_calendar/partitions.csv"

if [[ ! -f "$data" ]]; then
  echo "Data file not found: $data (run scripts/pack_calendar.py first)" >&2
  exit 1
fi

read -r offset size < <(awk -F, '$1 ~ /^calendar[[:space:]]*$/ {gsub(/[[:space:]]/, ""); print $4, $5}' "$partitions")
if [[ -z "${offset:-}" ]]; then
  echo "No calendar partition in $partitions" >&2
  exit 1
fi
data_size=$(stat -f %z "$data")
if (( data_size > size )); then
  echo "Data is $data_size bytes; the calendar partition holds $((size))" >&2
  exit 1
fi

if [[ -n "${ESPTOOL_BIN:-}" ]]; then
  esptool_bin="$ESPTOOL_BIN"
else
  esptool_bin="$(ls -d "$HOME"/Library/Arduino15/packages/esp32/tools/esptool_py/*/esptool 2>/dev/null | sort -V | tail -1)"
fi
if [[ -z "$esptool_bin" || ! -x "$esptool_bin" ]]; then
  echo "esptool not found. Install the ESP32 core in Arduino IDE or set ESPTOOL_BIN." >&2
  exit 1
fi

echo "Writing $data ($data_size bytes) to $port at $offset"
exec "$esptool_bin" --chip esp32 --port "$port" --baud 460800 write-flash "$offset" "$data"
