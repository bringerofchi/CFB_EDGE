"""
finalize_trapgame_threshold.py
Computes the real (OpponentB_pct - OpponentA_pct) distribution for
Candidate B (Trap Game/Schedule-Context Effect, spec §21) across the
qualifying Verified training population, and proposes a threshold —
mechanically, before any outcome data is touched. No code path in this
script reads ats_result or any score/outcome column.

Uses: games_master.csv (favorite/underdog, Verified flag, schedule dates)
and team_performance_snapshot.csv (team_efficiency_pct, already built and
validated).

Usage:
    python finalize_trapgame_threshold.py
    (training seasons hardcoded, no --seasons argument)
"""

import csv
import os
import statistics
from datetime import date as _date

PROCESSED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed")
PROCESSED_DIR = os.path.abspath(PROCESSED_DIR)

TRAINING_SEASONS = list(range(2014, 2022))  # hardcoded, not a parameter


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


def load_games_master():
    path = os.path.join(PROCESSED_DIR, "games_master.csv")
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rows = [r for r in csv.DictReader(f) if int(r["season"]) in TRAINING_SEASONS]
    return rows


def load_efficiency():
    path = os.path.join(PROCESSED_DIR, "team_performance_snapshot.csv")
    lookup = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if int(r["season"]) not in TRAINING_SEASONS:
                continue
            pct = to_float(r.get("team_efficiency_pct"))
            if pct is not None:
                lookup[(r["season"], r["team"], r["game_id"])] = pct
    return lookup


def build_team_schedules(games):
    """Every team's own chronological (by date) sequence of games that
    season, needed to find each game's T+1 opponent — pure schedule
    information, not outcome-derived."""
    by_season_team = {}
    for g in games:
        date = parse_date(g.get("date", ""))
        if date is None:
            continue
        for team, opponent in [(g["home_team"], g["away_team"]), (g["away_team"], g["home_team"])]:
            key = (g["season"], team)
            by_season_team.setdefault(key, []).append({
                "game_id": g["game_id"], "date": date, "opponent": opponent,
                "favorite": g.get("favorite"), "underdog": g.get("underdog"),
                "flag": g.get("market_data_quality_flag"),
            })
    for key in by_season_team:
        by_season_team[key].sort(key=lambda x: x["date"])
    return by_season_team


def main():
    print("Loading training-period games and building team schedules...")
    games = load_games_master()
    verified = [g for g in games if g.get("market_data_quality_flag") == "verified"]
    print(f"  {len(games)} total, {len(verified)} Verified")

    schedules = build_team_schedules(games)  # uses ALL games (any flag) for schedule sequencing —
                                              # schedule position isn't flag-dependent, only the
                                              # QUALIFYING game T itself needs to be Verified
    efficiency = load_efficiency()
    print(f"  Loaded efficiency for {len(efficiency)} team-games")

    gaps = []
    excluded_final_game = 0
    excluded_missing_efficiency = 0
    excluded_not_favorite = 0

    for g in verified:
        season, gid = g["season"], g["game_id"]
        home, away = g["home_team"], g["away_team"]
        favorite, underdog = g.get("favorite"), g.get("underdog")
        if not favorite or not underdog:
            continue

        team_x = favorite  # qualifying condition: Team X is the closing favorite
        opponent_a = underdog

        team_schedule = schedules.get((season, team_x), [])
        idx = next((i for i, gm in enumerate(team_schedule) if gm["game_id"] == gid), None)
        if idx is None or idx + 1 >= len(team_schedule):
            excluded_final_game += 1
            continue  # final regular-season game — excluded per §21 (bowl uncertainty)

        opponent_b = team_schedule[idx + 1]["opponent"]

        a_pct = efficiency.get((season, opponent_a, gid))
        # Opponent B's rating "as of before game T" = their most recent
        # team_performance_snapshot entry strictly before game T's date.
        b_schedule = schedules.get((season, opponent_b), [])
        b_pct = None
        game_t_date = next((gm["date"] for gm in team_schedule if gm["game_id"] == gid), None)
        for bg in reversed(b_schedule):
            if bg["date"] < game_t_date:
                b_pct = efficiency.get((season, opponent_b, bg["game_id"]))
                if b_pct is not None:
                    break

        if a_pct is None or b_pct is None:
            excluded_missing_efficiency += 1
            continue

        gap = b_pct - a_pct
        gaps.append(gap)

    print(f"\nExclusions: {excluded_final_game} final-regular-season-game, "
          f"{excluded_missing_efficiency} missing efficiency data")
    print(f"\n{len(gaps)} games in the qualifying construction population "
          f"(Team X favored, has a next game, both opponents' ratings available)")

    if len(gaps) < 200:
        print(f"\n** WARNING: population ({len(gaps)}) is below the 200-game floor used "
              f"elsewhere in this project. Flag before proceeding. **")

    gaps.sort()
    n = len(gaps)
    print(f"\nDistribution of (OpponentB_pct - OpponentA_pct):")
    print(f"  Mean: {statistics.mean(gaps):.2f}, Median: {statistics.median(gaps):.2f}")
    print(f"  Min: {gaps[0]:.2f}, Max: {gaps[-1]:.2f}")
    for pct in (50, 60, 70, 75, 80, 90, 95):
        idx = min(int(n * pct / 100), n - 1)
        print(f"  {pct}th percentile: {gaps[idx]:.2f}")

    print(f"\nThis is a distribution, not a decision. Threshold choice requires explicit review "
          f"and freeze, same as every other threshold in this project — no percentile is "
          f"pre-selected by this script.")


if __name__ == "__main__":
    main()
