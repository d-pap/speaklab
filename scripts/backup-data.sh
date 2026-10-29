#!/usr/bin/env bash
# Run as root inside the dedicated PC distro when no practice is in progress.
# Usage: backup-data.sh [destination]; defaults to the Windows D: drive.
set -euo pipefail
test "$(id -u)" = 0 || { echo 'Run as root inside SpeakLab.' >&2; exit 1; }
backup_dir="${1:-/mnt/d/SpeakLabBackups}"
test -d "$(dirname "$backup_dir")" || { echo "Backup location is unavailable: $backup_dir" >&2; exit 1; }
mkdir -p "$backup_dir"
archive="$backup_dir/speaklab-$(date -u +%Y%m%dT%H%M%SZ)-$$.tar.gz"
test ! -e "$archive" || { echo 'Backup already exists.' >&2; exit 1; }
was_active=false
systemctl is-active --quiet speaklab && was_active=true
restart_app() {
  if "$was_active"; then
    systemctl start speaklab
    for attempt in $(seq 1 30); do
      if curl -fsS -o /dev/null http://127.0.0.1:8765/api/health 2>/dev/null; then return; fi
      sleep 1
    done
    echo 'Backup finished, but app startup needs inspection: systemctl status speaklab' >&2
    return 1
  fi
}
trap restart_app EXIT
if "$was_active"; then systemctl stop speaklab; fi
tar -czf "$archive" -C /var/lib/speaklab .
tar -tzf "$archive" >/dev/null
sha256sum "$archive" > "$archive.sha256"
printf 'Verified archive: %s\n' "$archive"
