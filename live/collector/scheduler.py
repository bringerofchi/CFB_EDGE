"""
scheduler.py
Long-running process implementing the LOCKED polling cadence (spec §24):
  - Off-peak: poll every 8 hours
  - Pregame: poll every 30 minutes, within 12 hours of any game's kickoff
  - Pregame REPLACES off-peak for that window - never both at once

Gameday detection uses CFBD's own /games schedule data as the clock
(design decision, spec §24) - this costs nothing against the Odds API
budget, since it's a completely separate, already-established data source
with its own ample call budget.

This process is meant to run continuously for the duration of a season.
Recommended: launch via Windows Task Scheduler set to start at logon,
restart on failure - see accompanying .bat file.

Usage:
    python scheduler.py
    (runs until interrupted - Ctrl+C or process termination)
"""

import csv
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

RAW_GAMES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "..", "data", "raw", "games")
RAW_GAMES_DIR = os.path.abspath(RAW_GAMES_DIR)
POLL_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "poll_odds.py")

OFFPEAK_INTERVAL_SECONDS = 8 * 60 * 60   # LOCKED, spec §24
PREGAME_INTERVAL_SECONDS = 30 * 60       # LOCKED, spec §24
PREGAME_WINDOW_HOURS = 12                # LOCKED, spec §24

CHECK_INTERVAL_SECONDS = 5 * 60  # how often the scheduler re-evaluates mode,
                                  # independent of the poll interval itself


def load_upcoming_kickoffs(season):
    """Reads CFBD's already-pulled schedule to find kickoff times. This is
    the clock - checking it costs nothing against the Odds API budget."""
    path = os.path.join(RAW_GAMES_DIR, f"games_{season}.csv")
    kickoffs = []
    if not os.path.exists(path):
        return kickoffs
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            date_str = row.get("startDate") or row.get("start_date")
            if not date_str:
                continue
            try:
                dt = datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                kickoffs.append(dt)
            except ValueError:
                continue
    return kickoffs


def in_pregame_window(kickoffs, now):
    """True if any known kickoff falls within PREGAME_WINDOW_HOURS from now
    (and hasn't already passed, since a game in progress isn't 'pregame')."""
    for k in kickoffs:
        delta = (k - now).total_seconds() / 3600.0
        if 0 <= delta <= PREGAME_WINDOW_HOURS:
            return True
    return False


def run_poll(mode):
    print(f"[{datetime.now(timezone.utc).isoformat()}] Running poll (mode={mode})...")
    try:
        result = subprocess.run([sys.executable, POLL_SCRIPT, "--mode", mode],
                                 capture_output=True, text=True, timeout=60)
        print(result.stdout.strip())
        if result.returncode != 0:
            print(f"  ** Poll exited non-zero: {result.stderr.strip()[:300]} **")
    except subprocess.TimeoutExpired:
        print("  ** Poll timed out after 60s **")


def main():
    current_season = datetime.now(timezone.utc).year
    print(f"Scheduler starting. Season: {current_season}")
    print(f"Off-peak interval: {OFFPEAK_INTERVAL_SECONDS/3600:.0f}hr | "
          f"Pregame interval: {PREGAME_INTERVAL_SECONDS/60:.0f}min | "
          f"Pregame window: {PREGAME_WINDOW_HOURS}hr before kickoff")

    last_poll_time = None
    kickoffs = load_upcoming_kickoffs(current_season)
    last_schedule_reload = datetime.now(timezone.utc)

    while True:
        now = datetime.now(timezone.utc)

        # Reload schedule daily - CFBD data doesn't need re-checking every
        # 5 minutes, just needs to stay reasonably current.
        if (now - last_schedule_reload).total_seconds() > 24 * 3600:
            kickoffs = load_upcoming_kickoffs(current_season)
            last_schedule_reload = now
            print(f"[{now.isoformat()}] Reloaded schedule: {len(kickoffs)} games found for {current_season}")

        pregame = in_pregame_window(kickoffs, now)
        mode = "pregame" if pregame else "offpeak"
        interval = PREGAME_INTERVAL_SECONDS if pregame else OFFPEAK_INTERVAL_SECONDS

        due = (last_poll_time is None or (now - last_poll_time).total_seconds() >= interval)
        if due:
            run_poll(mode)
            last_poll_time = now

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
