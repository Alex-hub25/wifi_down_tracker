"""
wifi_tracker.py
Monitors Wi-Fi connectivity and logs outages to a CSV file.
"""

import subprocess
import platform
import time
import csv
import os
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────────────────
CHECK_HOST      = "8.8.8.8"
CHECK_INTERVAL  = 10          # Seconds between checks
PING_TIMEOUT    = 3           # Seconds before a ping is considered failed
LOG_FILE        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wifi_log.csv")
# ─────────────────────────────────────────────────────────────────────────────

CSV_HEADERS = ["timestamp", "event", "duration_down_seconds", "duration_down_human", "notes"]


def is_connected() -> bool:
    """Return True if the host responds to a ping."""
    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", "1", "-w", str(PING_TIMEOUT * 1000), CHECK_HOST]
    else:
        cmd = ["ping", "-c", "1", "-W", str(PING_TIMEOUT), CHECK_HOST]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=PING_TIMEOUT + 2,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def seconds_to_human(seconds: float) -> str:
    """Convert a duration in seconds to a human-readable string."""
    s = int(seconds)
    hours, remainder = divmod(s, 3600)
    minutes, secs   = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def ensure_log_file():
    """Create the CSV file with headers if it doesn't exist."""
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
        print(f"[+] Created log file: {LOG_FILE}")


def write_event(event: str, duration_down: float = 0.0, notes: str = ""):
    """Append a row to the CSV log."""
    now       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    has_dur   = duration_down > 0.0
    dur_secs  = round(duration_down, 1) if has_dur else ""
    dur_human = seconds_to_human(duration_down) if has_dur else ""

    row = {
        "timestamp":             now,
        "event":                 event,
        "duration_down_seconds": dur_secs,
        "duration_down_human":   dur_human,
        "notes":                 notes,
    }

    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=CSV_HEADERS).writerow(row)

    print(f"[{now}] {event}"
          + (f" | Down for {dur_human}" if dur_human else "")
          + (f" | {notes}"             if notes     else ""))


def main():
    ensure_log_file()
    write_event("TRACKER_STARTED", notes=f"Checking {CHECK_HOST} every {CHECK_INTERVAL}s")

    was_connected: bool  = True
    down_since:    float = 0.0

    print(f"Wi-Fi tracker running. Logging to: {LOG_FILE}")
    

if __name__ == "__main__":
    main()
