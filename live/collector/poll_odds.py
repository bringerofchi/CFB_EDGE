"""
poll_odds.py
Performs ONE poll of the-odds-api.com for current NCAAF spreads+totals
(FanDuel specifically), writes new odds_snapshot rows (never overwriting
prior snapshots, per §14.6), and logs the attempt (success or failure)
to collector_log regardless of outcome.

Markets: spreads + totals only (locked, spec §24)
Region: US only (locked)
Retry: maximum 1 retry per failed poll (locked)

This script does ONE poll and exits — scheduling (off-peak vs. pregame
cadence) is scheduler.py's job, not this script's. Keeping poll logic and
scheduling logic separate, per §14.6's "decoupled from the model pipeline"
principle extended to the collector's own internal structure.

Usage:
    python poll_odds.py --mode offpeak
    python poll_odds.py --mode pregame
    (mode is recorded in collector_log for later analysis, doesn't change
    poll behavior itself - the caller/scheduler decides cadence, this
    script just executes one poll)
"""

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("Missing dependency: pip install requests --break-system-packages")
    sys.exit(1)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "live_odds.db")
DB_PATH = os.path.abspath(DB_PATH)

API_BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY = "americanfootball_ncaaf"
MARKETS = "spreads,totals"  # LOCKED, spec §24 - no moneyline/h2h
REGION = "us"  # LOCKED
BOOKMAKER_KEY = "fanduel"  # LOCKED, spec §14.3

MAX_RETRIES = 1  # LOCKED, spec §24


def get_api_key():
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("ERROR: Set ODDS_API_KEY first (set ODDS_API_KEY=your_key_here)")
        sys.exit(1)
    return key


def utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_odds(api_key):
    """One call. Returns (data, raw_text, error, retries_used). Retries once
    on failure, per the locked retry policy - never more, to keep the
    stress-tested budget assumption (10% retry overhead) honest."""
    url = f"{API_BASE}/sports/{SPORT_KEY}/odds"
    params = {
        "apiKey": api_key,
        "regions": REGION,
        "markets": MARKETS,
        "bookmakers": BOOKMAKER_KEY,
        "oddsFormat": "american",
    }
    attempt = 0
    last_error = None
    while attempt <= MAX_RETRIES:
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json(), resp.text, None, attempt
            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except requests.RequestException as e:
            last_error = str(e)
        attempt += 1
        if attempt <= MAX_RETRIES:
            time.sleep(5)  # brief pause before the single retry
    return None, None, last_error, attempt - 1


def parse_and_store(data, poll_timestamp, mode, retry_used, raw_json_text):
    """Writes raw_responses FIRST (raw-data-first discipline, same as every
    historical script in this project), THEN games (upsert) and
    odds_snapshots (always INSERT, never UPDATE), each linked back to the
    exact raw response it came from."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Raw payload saved BEFORE any extraction - if parsing logic is ever
    # found to have a bug later, the original data is still recoverable,
    # not lost to a parse-and-discard step.
    cur.execute("""
        INSERT INTO raw_responses (poll_timestamp_utc, raw_json)
        VALUES (?, ?)
    """, (poll_timestamp, raw_json_text))
    raw_id = cur.lastrowid

    games_returned = len(data) if data else 0
    snapshots_written = 0

    for game in data or []:
        game_id = game.get("id")
        commence_time = game.get("commence_time")
        home_team = game.get("home_team")
        away_team = game.get("away_team")

        # games: upsert on game_id (games themselves change - e.g. score
        # gets added later - but this is NOT the append-only snapshot
        # table, so an upsert here is correct, not a violation of §14.6)
        cur.execute("""
            INSERT INTO games (game_id, commence_time_utc, home_team, away_team)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(game_id) DO UPDATE SET
                commence_time_utc = excluded.commence_time_utc,
                home_team = excluded.home_team,
                away_team = excluded.away_team
        """, (game_id, commence_time, home_team, away_team))

        for bookmaker in game.get("bookmakers", []):
            if bookmaker.get("key") != BOOKMAKER_KEY:
                continue  # LOCKED to FanDuel only, per §14.3
            book_last_update = bookmaker.get("last_update")

            spread_home, spread_away, total = None, None, None
            for market in bookmaker.get("markets", []):
                if market.get("key") == "spreads":
                    for outcome in market.get("outcomes", []):
                        if outcome.get("name") == home_team:
                            spread_home = outcome.get("point")
                        elif outcome.get("name") == away_team:
                            spread_away = outcome.get("point")
                elif market.get("key") == "totals":
                    outcomes = market.get("outcomes", [])
                    if outcomes:
                        total = outcomes[0].get("point")  # Over/Under share the same point value

            # ALWAYS INSERT - never UPDATE an existing snapshot. This is the
            # entire point of the table (§14.1/§14.6) - reconstructing
            # movement over time requires every poll to be its own row.
            # Linked to raw_id so the exact source payload is always traceable.
            cur.execute("""
                INSERT INTO odds_snapshots
                (game_id, raw_id, source_provider, sportsbook, poll_timestamp_utc,
                 book_last_update_utc, spread_home, spread_away, total, quality_flag)
                VALUES (?, ?, 'the-odds-api.com', 'fanduel', ?, ?, ?, ?, ?, ?)
            """, (game_id, raw_id, poll_timestamp, book_last_update, spread_home, spread_away,
                  total, "collected"))
            snapshots_written += 1

    cur.execute("""
        INSERT INTO collector_log
        (poll_timestamp_utc, poll_mode, status, games_returned, snapshots_written, retry_used)
        VALUES (?, ?, 'success', ?, ?, ?)
    """, (poll_timestamp, mode, games_returned, snapshots_written, retry_used))

    conn.commit()
    conn.close()
    return games_returned, snapshots_written


def log_failure(poll_timestamp, mode, error_message, retry_used):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO collector_log
        (poll_timestamp_utc, poll_mode, status, games_returned, snapshots_written,
         retry_used, error_message)
        VALUES (?, ?, 'failure', 0, 0, ?, ?)
    """, (poll_timestamp, mode, retry_used, error_message))
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="One poll of the-odds-api.com for NCAAF FanDuel odds.")
    parser.add_argument("--mode", choices=["offpeak", "pregame"], default="offpeak")
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print("ERROR: Database not found. Run db_schema.py first.")
        sys.exit(1)

    api_key = get_api_key()
    poll_timestamp = utc_now_iso()

    data, raw_text, error, retry_used = fetch_odds(api_key)

    if error:
        print(f"POLL FAILED after {retry_used} retr{'y' if retry_used == 1 else 'ies'}: {error}")
        log_failure(poll_timestamp, args.mode, error, retry_used)
        sys.exit(1)

    games_returned, snapshots_written = parse_and_store(data, poll_timestamp, args.mode,
                                                          retry_used, raw_text)
    print(f"Poll succeeded ({args.mode}): {games_returned} games returned, "
          f"{snapshots_written} FanDuel snapshots written.")


if __name__ == "__main__":
    main()
