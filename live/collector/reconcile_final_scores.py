"""
reconcile_final_scores.py
Standalone job, separate from poll_odds.py and scheduler.py entirely.
Fills in final_home_score/final_away_score for games in the live database
once they're actually final, by matching against CFBD's already-refreshed
local schedule data (data/raw/games/games_{season}.csv - the same file
scheduler.py already keeps current via its weekly auto-refresh, so this
job makes NO new API calls of its own).

MATCHING METHOD - stated honestly, not overstated: the-odds-api.com and
CFBD are independent systems with their own internal IDs; there is no
shared stable identifier between them. Matching is done by date + 
normalized home/away team names, using the SAME normalization already
validated throughout this project's historical pipeline
(line_reconciliation.py's _strip_to_alnum), not a fallback from something
stronger - this IS the primary and only matching method.

IDEMPOTENT BY CONSTRUCTION: only ever UPDATEs rows where
final_home_score IS NULL. A game already settled is never touched again,
so repeated runs cannot corrupt or duplicate anything - this isn't a
manually-checked guard, it's a property of the SQL itself.

Usage:
    python reconcile_final_scores.py
"""

import csv
import os
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "live_odds.db")
DB_PATH = os.path.abspath(DB_PATH)
RAW_GAMES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "..", "data", "raw", "games")
RAW_GAMES_DIR = os.path.abspath(RAW_GAMES_DIR)


def _strip_to_alnum(name):
    """Same normalization already validated in line_reconciliation.py -
    reused for consistency, not reimplemented differently."""
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_name = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", ascii_name.lower())


def load_cfbd_final_scores(season):
    """Reads the LOCAL games_{season}.csv - already kept current by
    scheduler.py's weekly refresh. No new API call happens here."""
    path = os.path.join(RAW_GAMES_DIR, f"games_{season}.csv")
    if not os.path.exists(path):
        return {}
    finals = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            home_pts = row.get("homePoints")
            away_pts = row.get("awayPoints")
            if home_pts in (None, "", "None") or away_pts in (None, "", "None"):
                continue  # not final yet - CFBD leaves these blank until the game completes
            date = (row.get("startDate") or row.get("start_date") or "")[:10]
            home_norm = _strip_to_alnum(row.get("homeTeam") or row.get("home_team") or "")
            away_norm = _strip_to_alnum(row.get("awayTeam") or row.get("away_team") or "")
            finals[(date, home_norm, away_norm)] = (int(float(home_pts)), int(float(away_pts)))
    return finals


def reconcile(season):
    if not os.path.exists(DB_PATH):
        print("ERROR: live database not found. Run db_schema.py first.")
        sys.exit(1)

    finals = load_cfbd_final_scores(season)
    print(f"Loaded {len(finals)} final scores from local CFBD schedule data for {season}.")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Only unsettled games are candidates at all - this is the idempotency
    # guarantee, not a separate check bolted on afterward.
    cur.execute("SELECT game_id, commence_time_utc, home_team, away_team FROM games "
                "WHERE final_home_score IS NULL")
    unsettled = cur.fetchall()
    print(f"{len(unsettled)} unsettled games in the live database to check.")

    matched, unmatched = 0, 0
    for game_id, commence_time, home_team, away_team in unsettled:
        if not commence_time:
            unmatched += 1
            continue
        date = commence_time[:10]
        home_norm = _strip_to_alnum(home_team)
        away_norm = _strip_to_alnum(away_team)

        key = (date, home_norm, away_norm)
        if key not in finals:
            unmatched += 1
            continue

        home_score, away_score = finals[key]
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # WHERE final_home_score IS NULL again here, not just in the SELECT
        # above - this is what makes the operation genuinely idempotent at
        # the SQL level, not just "probably fine because we checked earlier."
        cur.execute("""
            UPDATE games
            SET final_home_score = ?, final_away_score = ?, result_recorded_utc = ?
            WHERE game_id = ? AND final_home_score IS NULL
        """, (home_score, away_score, now_iso, game_id))
        if cur.rowcount > 0:
            matched += 1

    conn.commit()
    conn.close()

    print(f"\nMatched and recorded: {matched}")
    print(f"Still unmatched (game not yet final, or no CFBD schedule match): {unmatched}")
    print("\nRun again anytime - already-settled games are never re-touched.")


if __name__ == "__main__":
    current_season = datetime.now(timezone.utc).year
    reconcile(current_season)
