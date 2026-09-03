"""
db_schema.py
Creates the SQLite database and tables per spec §14.1, adapted for the
live collector. Idempotent - safe to run multiple times, never drops
existing data.

Tables (subset of §14.1's full target architecture - team_stats/features/
experiments deferred until live data actually exists to populate them):
  - games: one row per tracked game
  - odds_snapshots: one row per poll per game - NEVER overwritten, per §14.6
  - collector_log: one row per poll attempt (success or failure), per §14.6

Usage:
    python db_schema.py
    (creates live_odds.db in the same folder if it doesn't exist)
"""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "live_odds.db")
DB_PATH = os.path.abspath(DB_PATH)


def create_schema():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS games (
            game_id TEXT PRIMARY KEY,
            season INTEGER,
            commence_time_utc TEXT,
            home_team TEXT,
            away_team TEXT,
            final_home_score INTEGER,
            final_away_score INTEGER,
            result_recorded_utc TEXT
        )
    """)

    # odds_snapshots: snapshot_id is an autoincrement surrogate key -
    # (game_id, poll_timestamp_utc) is never unique-constrained, since the
    # entire point is that every poll creates a NEW row, never an update.
    # raw_responses: the ENTIRE unparsed API response, saved BEFORE any
    # extraction happens - same raw-data-first discipline already used
    # throughout this project's historical pipeline (CFBD JSON, SBRO CSVs
    # are always saved raw before parsing). This is what lets a later
    # investigation answer "exactly where did this number come from?"
    # without trusting the parsing logic was correct at collection time.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS raw_responses (
            raw_id INTEGER PRIMARY KEY AUTOINCREMENT,
            poll_timestamp_utc TEXT NOT NULL,
            raw_json TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            raw_id INTEGER,
            source_provider TEXT NOT NULL DEFAULT 'the-odds-api.com',
            sportsbook TEXT NOT NULL DEFAULT 'fanduel',
            poll_timestamp_utc TEXT NOT NULL,
            book_last_update_utc TEXT,
            spread_home REAL,
            spread_away REAL,
            total REAL,
            quality_flag TEXT,
            FOREIGN KEY (game_id) REFERENCES games(game_id),
            FOREIGN KEY (raw_id) REFERENCES raw_responses(raw_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_game ON odds_snapshots(game_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_time ON odds_snapshots(poll_timestamp_utc)")

    # collector_log: per §14.6, both successes AND failures logged, so a gap
    # in odds_snapshots can be distinguished from "line didn't move" vs
    # "collector was down."
    cur.execute("""
        CREATE TABLE IF NOT EXISTS collector_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            poll_timestamp_utc TEXT NOT NULL,
            poll_mode TEXT,
            status TEXT NOT NULL,
            games_returned INTEGER,
            snapshots_written INTEGER,
            retry_used INTEGER DEFAULT 0,
            error_message TEXT
        )
    """)

    conn.commit()
    conn.close()
    print(f"Schema created/verified at {DB_PATH}")


if __name__ == "__main__":
    create_schema()
