"""
wifi_monitor_gui.py
Desktop GUI for monitoring Wi-Fi uptime and outage history.

Usage:
    python wifi_monitor_gui.py

Requires only the Python standard library (tkinter is built-in).
Logs are shared with wifi_tracker.py via wifi_log.csv.
"""

import csv
import os
import subprocess
import threading
import time
import tkinter as tk
from datetime import datetime, date
from tkinter import ttk
from typing import Optional

# ── Configuration ──────────────────────────────────────────────────────────────
CHECK_HOST = "8.8.8.8"
CHECK_INTERVAL = 10          # Seconds between connectivity checks
PING_TIMEOUT = 3
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wifi_log.csv")
CSV_HEADERS = ["timestamp", "event", "duration_down_seconds", "duration_down_human", "notes"]
MAX_LOG_ROWS = 200           # Max rows shown in the table
# ──────────────────────────────────────────────────────────────────────────────

# ── Colours ────────────────────────────────────────────────────────────────────
BG         = "#1e1e2e"
PANEL      = "#2a2a3d"
GREEN      = "#4ade80"
RED        = "#f87171"
YELLOW     = "#facc15"
TEXT       = "#e2e8f0"
SUBTEXT    = "#94a3b8"
ACCENT     = "#818cf8"
ROW_EVEN   = "#252537"
ROW_ODD    = "#2a2a3d"
# ──────────────────────────────────────────────────────────────────────────────


def is_connected() -> bool:
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", str(PING_TIMEOUT * 1000), CHECK_HOST],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except Exception:
        return False


def seconds_to_human(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def ensure_log():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADERS).writeheader()


def append_log(event: str, duration_down: Optional[float] = None, notes: str = ""):
    ensure_log()
    dur_secs  = round(duration_down, 1) if duration_down is not None else ""
    dur_human = seconds_to_human(duration_down) if duration_down is not None else ""
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=CSV_HEADERS).writerow({
            "timestamp":             datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event":                 event,
            "duration_down_seconds": dur_secs,
            "duration_down_human":   dur_human,
            "notes":                 notes,
        })


def load_log_rows() -> list[dict]:
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def compute_avg_downtime() -> tuple[float, float, float]:
    """Return (avg_day_secs, avg_week_secs, avg_month_secs) from log history."""
    from collections import defaultdict
    rows = load_log_rows()
    daily: dict[str, float] = defaultdict(float)

    for row in rows:
        if row.get("event") == "WIFI_RESTORED":
            dur = row.get("duration_down_seconds", "")
            ts  = row.get("timestamp", "")
            if dur and len(ts) >= 10:
                try:
                    daily[ts[:10]] += float(dur)
                except (ValueError, TypeError):
                    pass

    # Add the current live outage to today if one is active
    with state.lock:
        if not state.connected and state.outage_start:
            today = date.today().isoformat()
            daily[today] += (datetime.now() - state.outage_start).total_seconds()

    if not daily:
        return 0.0, 0.0, 0.0

    avg_day = sum(daily.values()) / len(daily)

    weekly: dict[str, float] = defaultdict(float)
    monthly: dict[str, float] = defaultdict(float)
    for day_str, secs in daily.items():
        try:
            d = date.fromisoformat(day_str)
            iso = d.isocalendar()
            weekly[f"{iso[0]}-W{iso[1]:02d}"] += secs
            monthly[day_str[:7]] += secs
        except ValueError:
            pass

    avg_week  = sum(weekly.values())  / len(weekly)  if weekly  else 0.0
    avg_month = sum(monthly.values()) / len(monthly) if monthly else 0.0
    return avg_day, avg_week, avg_month


# ── Monitor thread state ───────────────────────────────────────────────────────
class MonitorState:
    def __init__(self):
        self.lock                       = threading.Lock()
        self.connected                  = True
        self.outage_start: Optional[datetime] = None   # datetime when outage began
        self.session_start = datetime.now()
        self.outages_today = 0
        self.total_down    = 0.0       # seconds down today
        self.running       = False


state = MonitorState()


def monitor_loop():
    state.running = True
    append_log("TRACKER_STARTED", notes=f"GUI monitor started — pinging {CHECK_HOST}")

    first = True
    was_connected = True

    while state.running:
        connected = is_connected()

        with state.lock:
            if first:
                state.connected = connected
                if not connected:
                    state.outage_start = datetime.now()
                    append_log("WIFI_DOWN", notes="Already down at startup")
                first = False

            elif was_connected and not connected:
                state.connected   = False
                state.outage_start = datetime.now()
                state.outages_today += 1
                append_log("WIFI_DOWN")

            elif not was_connected and connected:
                state.connected = True
                if state.outage_start:
                    dur = (datetime.now() - state.outage_start).total_seconds()
                    state.total_down += dur
                    append_log("WIFI_RESTORED", duration_down=dur)
                state.outage_start = None

        was_connected = connected

        for _ in range(CHECK_INTERVAL * 2):
            if not state.running:
                break
            time.sleep(0.5)

    # Log shutdown
    with state.lock:
        if not state.connected and state.outage_start:
            dur = (datetime.now() - state.outage_start).total_seconds()
            append_log("TRACKER_STOPPED", duration_down=dur, notes="Stopped during outage")
        else:
            append_log("TRACKER_STOPPED")


# ── GUI ────────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Wi-Fi Monitor")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(640, 480)
        self.geometry("780x560")

        # Keep window on top option
        self._always_on_top = tk.BooleanVar(value=False)

        self._build_ui()
        self._start_monitor()
        self._refresh()

    # ── Build UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Title bar row ──
        title_row = tk.Frame(self, bg=BG)
        title_row.pack(fill="x", padx=16, pady=(14, 0))

        tk.Label(title_row, text="Wi-Fi Monitor", font=("Segoe UI", 16, "bold"),
                 bg=BG, fg=TEXT).pack(side="left")

        pin_cb = tk.Checkbutton(title_row, text="Always on top",
                                variable=self._always_on_top,
                                command=self._toggle_on_top,
                                bg=BG, fg=SUBTEXT, selectcolor=PANEL,
                                activebackground=BG, activeforeground=TEXT,
                                font=("Segoe UI", 9))
        pin_cb.pack(side="right")

        # ── Status card ──
        card = tk.Frame(self, bg=PANEL, bd=0, relief="flat")
        card.pack(fill="x", padx=16, pady=10)

        # Big status dot + label
        dot_col = tk.Frame(card, bg=PANEL)
        dot_col.pack(side="left", padx=18, pady=14)

        self._dot = tk.Canvas(dot_col, width=28, height=28, bg=PANEL,
                              highlightthickness=0)
        self._dot.pack()
        self._dot_id = self._dot.create_oval(2, 2, 26, 26, fill=GREEN, outline="")

        self._status_lbl = tk.Label(card, text="CONNECTED",
                                    font=("Segoe UI", 22, "bold"),
                                    bg=PANEL, fg=GREEN)
        self._status_lbl.pack(side="left", pady=14)

        # Stats on the right of card
        stats = tk.Frame(card, bg=PANEL)
        stats.pack(side="right", padx=18, pady=10)

        self._stat_uptime  = self._stat_row(stats, "Session uptime",  "—")
        self._stat_outages = self._stat_row(stats, "Outages today",    "0")
        self._stat_downfor = self._stat_row(stats, "Currently down for", "—")

        # ── Average downtime panel ──
        avg_card = tk.Frame(self, bg=PANEL, bd=0, relief="flat")
        avg_card.pack(fill="x", padx=16, pady=(0, 6))

        tk.Label(avg_card, text="Avg Downtime",
                 font=("Segoe UI", 9, "bold"),
                 bg=PANEL, fg=ACCENT).pack(side="left", padx=14, pady=8)

        avg_cols_frame = tk.Frame(avg_card, bg=PANEL)
        avg_cols_frame.pack(side="right", padx=14, pady=6)

        def _avg_col(parent, label):
            col = tk.Frame(parent, bg=PANEL)
            col.pack(side="left", padx=18)
            tk.Label(col, text=label, font=("Segoe UI", 8),
                     bg=PANEL, fg=SUBTEXT).pack()
            val = tk.Label(col, text="—", font=("Segoe UI", 10, "bold"),
                           bg=PANEL, fg=TEXT)
            val.pack()
            return val

        self._avg_day_lbl   = _avg_col(avg_cols_frame, "Per Day")
        self._avg_week_lbl  = _avg_col(avg_cols_frame, "Per Week")
        self._avg_month_lbl = _avg_col(avg_cols_frame, "Per Month")

        # ── Separator ──
        sep = tk.Frame(self, bg=ACCENT, height=1)
        sep.pack(fill="x", padx=16)

        # ── Log table ──
        table_frame = tk.Frame(self, bg=BG)
        table_frame.pack(fill="both", expand=True, padx=16, pady=10)

        cols = ("timestamp", "event", "duration_down_human", "notes")
        self._tree = ttk.Treeview(table_frame, columns=cols, show="headings",
                                   height=16)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview",
                        background=ROW_EVEN, foreground=TEXT,
                        rowheight=24, fieldbackground=ROW_EVEN,
                        borderwidth=0, font=("Segoe UI", 9))
        style.configure("Treeview.Heading",
                        background=PANEL, foreground=ACCENT,
                        font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", ACCENT)])

        headings = {"timestamp": ("Timestamp", 155),
                    "event":     ("Event", 130),
                    "duration_down_human": ("Down Duration", 110),
                    "notes":     ("Notes", 240)}

        for col, (label, width) in headings.items():
            self._tree.heading(col, text=label)
            self._tree.column(col, width=width, anchor="w", stretch=col == "notes")

        self._tree.tag_configure("down",     background="#3d1f1f", foreground=RED)
        self._tree.tag_configure("restored", background="#1f3d28", foreground=GREEN)
        self._tree.tag_configure("info",     background=ROW_ODD,   foreground=SUBTEXT)
        self._tree.tag_configure("even",     background=ROW_EVEN,  foreground=TEXT)

        vsb = ttk.Scrollbar(table_frame, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)

        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        # ── Footer ──
        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x", padx=16, pady=(0, 10))

        self._footer_lbl = tk.Label(footer, text="", font=("Segoe UI", 8),
                                    bg=BG, fg=SUBTEXT)
        self._footer_lbl.pack(side="left")

        tk.Label(footer, text=f"Log: {LOG_FILE}", font=("Segoe UI", 8),
                 bg=BG, fg=SUBTEXT).pack(side="right")

    def _stat_row(self, parent, label: str, value: str):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(anchor="e", pady=1)
        tk.Label(row, text=label + ":", font=("Segoe UI", 9),
                 bg=PANEL, fg=SUBTEXT).pack(side="left", padx=(0, 6))
        val_lbl = tk.Label(row, text=value, font=("Segoe UI", 9, "bold"),
                           bg=PANEL, fg=TEXT)
        val_lbl.pack(side="left")
        return val_lbl

    # ── Monitor thread ─────────────────────────────────────────────────────────
    def _start_monitor(self):
        ensure_log()
        t = threading.Thread(target=monitor_loop, daemon=True)
        t.start()

    # ── Periodic refresh ───────────────────────────────────────────────────────
    def _refresh(self):
        self._update_status()
        self._update_table()
        self._update_averages()
        self._footer_lbl.config(
            text=f"Last checked: {datetime.now().strftime('%H:%M:%S')}  |  "
                 f"Checking every {CHECK_INTERVAL}s"
        )
        self.after(CHECK_INTERVAL * 1000, self._refresh)

    def _update_averages(self):
        avg_day, avg_week, avg_month = compute_avg_downtime()
        na = "—"
        self._avg_day_lbl.config(
            text=seconds_to_human(avg_day)   if avg_day   else na)
        self._avg_week_lbl.config(
            text=seconds_to_human(avg_week)  if avg_week  else na)
        self._avg_month_lbl.config(
            text=seconds_to_human(avg_month) if avg_month else na)

    def _update_status(self):
        with state.lock:
            connected     = state.connected
            outage_start  = state.outage_start
            session_start = state.session_start
            outages       = state.outages_today
            total_down    = state.total_down

        now = datetime.now()

        if connected:
            self._dot.itemconfig(self._dot_id, fill=GREEN)
            self._status_lbl.config(text="CONNECTED", fg=GREEN)
            self._stat_downfor.config(text="—", fg=SUBTEXT)
        else:
            # Pulse colour between red and yellow when down
            pulse = RED if int(time.time()) % 2 == 0 else YELLOW
            self._dot.itemconfig(self._dot_id, fill=pulse)
            self._status_lbl.config(text="DISCONNECTED", fg=RED)
            if outage_start:
                secs = (now - outage_start).total_seconds()
                self._stat_downfor.config(
                    text=seconds_to_human(secs), fg=RED)

        # Session uptime (exclude current outage time)
        session_secs = (now - session_start).total_seconds()
        current_down = (now - outage_start).total_seconds() if (not connected and outage_start) else 0
        up_secs = max(0, session_secs - total_down - current_down)
        self._stat_uptime.config(text=seconds_to_human(up_secs))
        self._stat_outages.config(text=str(outages))

    def _update_table(self):
        rows = load_log_rows()
        rows_rev = list(reversed(rows[-MAX_LOG_ROWS:]))

        # Only repopulate when row count changes to avoid flicker
        existing = len(self._tree.get_children())
        if existing == len(rows_rev):
            return

        self._tree.delete(*self._tree.get_children())
        for i, row in enumerate(rows_rev):
            event = row.get("event", "")
            if "DOWN" in event:
                tag = "down"
            elif "RESTORED" in event:
                tag = "restored"
            elif event in ("TRACKER_STARTED", "TRACKER_STOPPED"):
                tag = "info"
            else:
                tag = "even" if i % 2 == 0 else "info"

            self._tree.insert("", "end", values=(
                row.get("timestamp", ""),
                event,
                row.get("duration_down_human", ""),
                row.get("notes", ""),
            ), tags=(tag,))

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _toggle_on_top(self):
        self.wm_attributes("-topmost", self._always_on_top.get())

    def on_close(self):
        state.running = False
        self.after(600, self.destroy)


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
