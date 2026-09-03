"""
finalize_totals_threshold.py
Computes the real |discrepancy| distribution for Candidate A (Totals Market
Inefficiency, spec §20) across the Verified-only training population, and
proposes a single fixed threshold — mechanically, before any outcome data
is touched. This script has NO code path that reads any ATS or totals-
outcome column; it cannot be used to threshold-hunt even accidentally.

Uses: totals_reconciliation_detail.csv (§19, already produced) for the
market side, and games_master.csv + a fresh points-scored/allowed rolling
computation for the model side (implied_total).

Usage:
    python finalize_totals_threshold.py
    (training seasons hardcoded — no --seasons argument, same safety
    pattern as every other threshold/evaluation script in this project)
"""

import csv
import os
import statistics
from datetime import date as _date

PROCESSED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed")
PROCESSED_DIR = os.path.abspath(PROCESSED_DIR)
RAW_DIR = os.path.abspath(os.path.join(PROCESSED_DIR, "..", "raw"))

TRAINING_SEASONS = list(range(2014, 2022))  # hardcoded, not a parameter
MIN_PRIOR_GAMES = 2  # same floor as efficiency_features.py


def to_float(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None


def parse_date(s):
    try:
        y, m, d = s[:10].split("-")
        return _date(int(y), int(m), int(d))
    except (ValueError, AttributeError, TypeError):
        return None


def load_totals_reconciliation():
    """From §19's audit output — market_total (Verified only) per game."""
    path = "totals_reconciliation_detail.csv"
    if not os.path.exists(path):
        print(f"ERROR: {path} not found. Run totals_reconciliation_audit.py first, "
              f"in this same folder.")
        return {}
    market = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if int(r["season"]) not in TRAINING_SEASONS:
                continue
            if r["totals_market_quality_flag"] != "verified":
                continue  # LOCKED per §20: Verified-only headline population
            cfbd_t = to_float(r["cfbd_total"])
            sbro_t = to_float(r["sbro_total"])
            # Verified means both exist and agree within tolerance — use SBRO
            # as primary per the source hierarchy already established (§19).
            market_total = sbro_t if sbro_t is not None else cfbd_t
            if market_total is not None:
                market[(r["season"], r["game_id"])] = market_total
    return market


def load_games_for_rolling_scoring():
    """Points scored/allowed per team per game, chronologically ordered by
    DATE (not week — learned that lesson the hard way earlier this project;
    week numbers collide between regular season and postseason)."""
    games_by_season = {}
    for season in TRAINING_SEASONS:
        path = os.path.join(RAW_DIR, "games", f"games_{season}.csv")
        if not os.path.exists(path):
            continue
        rows = []
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                home_pts = to_float(r.get("homePoints"))
                away_pts = to_float(r.get("awayPoints"))
                date = parse_date(r.get("startDate", ""))
                if home_pts is None or away_pts is None or date is None:
                    continue
                rows.append({
                    "game_id": r.get("id") or r.get("gameId"),
                    "home": r.get("homeTeam"), "away": r.get("awayTeam"),
                    "home_pts": home_pts, "away_pts": away_pts, "date": date,
                })
        rows.sort(key=lambda x: x["date"])
        games_by_season[season] = rows
    return games_by_season


def compute_implied_totals(games_by_season):
    """implied_total = avg(TeamA_scored, TeamB_allowed) + avg(TeamB_scored, TeamA_allowed),
    using rolling pregame averages only, MIN_PRIOR_GAMES floor applied."""
    implied = {}  # (season, game_id) -> implied_total
    for season, games in games_by_season.items():
        scored = {}  # team -> [points scored in each prior game]
        allowed = {}  # team -> [points allowed in each prior game]

        for g in games:
            home, away = g["home"], g["away"]

            def avg_or_none(d, team):
                vals = d.get(team, [])
                return (sum(vals) / len(vals)) if len(vals) >= MIN_PRIOR_GAMES else None

            home_scored_avg = avg_or_none(scored, home)
            home_allowed_avg = avg_or_none(allowed, home)
            away_scored_avg = avg_or_none(scored, away)
            away_allowed_avg = avg_or_none(allowed, away)

            if None not in (home_scored_avg, home_allowed_avg, away_scored_avg, away_allowed_avg):
                home_proj = (home_scored_avg + away_allowed_avg) / 2
                away_proj = (away_scored_avg + home_allowed_avg) / 2
                implied[(str(season), str(g["game_id"]))] = home_proj + away_proj

            # Update running history AFTER computing this game's projection
            scored.setdefault(home, []).append(g["home_pts"])
            scored.setdefault(away, []).append(g["away_pts"])
            allowed.setdefault(home, []).append(g["away_pts"])
            allowed.setdefault(away, []).append(g["home_pts"])

    return implied


def main():
    print("Loading Verified-only market totals (training seasons only)...")
    market = load_totals_reconciliation()
    if not market:
        return
    print(f"  {len(market)} Verified games with a market total")

    print("Computing rolling implied totals (pregame only, MIN_PRIOR_GAMES=2)...")
    games_by_season = load_games_for_rolling_scoring()
    implied = compute_implied_totals(games_by_season)
    print(f"  {len(implied)} games with a computable implied_total")

    discrepancies = []
    for key, market_total in market.items():
        if key in implied:
            discrepancies.append(abs(implied[key] - market_total))

    print(f"\n{len(discrepancies)} games with BOTH a Verified market total AND a computable "
          f"implied_total — this is the real construction population for the threshold.")

    if len(discrepancies) < 200:
        print(f"\n** WARNING: population ({len(discrepancies)}) is below the 200-game floor "
              f"already used elsewhere in this project (e.g. §18's Model-vs-Spread). "
              f"A threshold computed from this may not be trustworthy — flag before proceeding. **")

    discrepancies.sort()
    n = len(discrepancies)
    print(f"\nDistribution of |discrepancy|:")
    print(f"  Mean: {statistics.mean(discrepancies):.2f}, Median: {statistics.median(discrepancies):.2f}")
    for pct in (50, 60, 70, 75, 80, 90, 95):
        idx = min(int(n * pct / 100), n - 1)
        print(f"  {pct}th percentile: {discrepancies[idx]:.2f} points")

    print(f"\nProposed threshold (75th percentile, consistent with this project's established "
          f"convention for Signal 3 and Model-vs-Spread): {discrepancies[min(int(n*0.75), n-1)]:.2f} points")
    print("\nThis is a proposal only — review and explicit freeze required before evaluation, "
          "same as every other threshold in this project.")


if __name__ == "__main__":
    main()
