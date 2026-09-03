"""
market_features.py
Phase 2 — Market features (§5.3 of the spec): reputation gap, line movement.

Builds two of the three components listed under the Market Mispricing
Edge Score category (§7):
  1. Line movement — re-exposed from games_master.csv's line_movement_signed,
     reframed per-team (positive = market moved toward this team being more
     favored, regardless of home/away side)
  2. Reputation gap — team_efficiency_pct (from efficiency_features.py) minus
     a reputation proxy built from recruiting class rank (recruiting_teams
     data, already pulled in Phase 1A). Lower recruiting rank number = more
     hyped/better class = inverted to a percentile where higher = more hyped.
     Positive gap = team performing better than their recruiting pedigree
     suggests ("underrated"); negative = hype exceeds performance.

NOT BUILT HERE — "model vs. spread difference": this needs a genuine
modeling decision (how many points does an efficiency percentile edge
translate to?) that has never been specified anywhere in the spec. Building
this now would mean inventing a percentile-to-points conversion formula
unilaterally, which is exactly the kind of undocumented methodology choice
this project has been careful to avoid elsewhere. Flagged as an open item,
not implemented as a guess.

REPUTATION PROXY SIMPLIFICATION: uses the CURRENT season's recruiting class
rank only, not a trailing multi-year average of the roster's recruiting
pedigree. A team's actual roster reflects 4+ years of recruiting classes,
not just this year's — this is a real simplification, not a claim that
single-year rank is the "correct" reputation measure. Worth revisiting if
this feature doesn't perform well later, before assuming the underlying
idea is flawed rather than the proxy being too narrow.

Usage:
    python src/features/market_features.py --seasons 2014-2021
"""

import argparse
import csv
import json
import os

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")
RAW_DIR = os.path.abspath(RAW_DIR)
PROCESSED_DIR = os.path.abspath(os.path.join(RAW_DIR, "..", "processed"))

TRAINING_SEASONS = set(range(2014, 2022))


def _get(d, *paths, default=None):
    for path in paths:
        cur = d
        try:
            for key in path.split("."):
                cur = cur[key]
            if cur is not None:
                return cur
        except (KeyError, TypeError):
            continue
    return default


def load_recruiting(season):
    path = os.path.join(RAW_DIR, "roster", f"recruiting_{season}.csv")
    if not os.path.exists(path):
        return {}
    ranks = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            team = row.get("team")
            rank = row.get("rank")
            if team and rank not in (None, ""):
                try:
                    ranks[team] = int(rank)
                except ValueError:
                    pass
    return ranks


def load_games_master():
    path = os.path.join(PROCESSED_DIR, "games_master.csv")
    if not os.path.exists(path):
        print("  ** ERROR: games_master.csv not found. Run build_games_master.py first. **")
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def load_efficiency(season):
    path = os.path.join(PROCESSED_DIR, "team_performance_snapshot.csv")
    if not os.path.exists(path):
        print("  ** ERROR: team_performance_snapshot.csv not found. Run efficiency_features.py first. **")
        return {}
    lookup = {}  # (season, team, game_id) -> team_efficiency_pct
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            if int(row["season"]) != season:
                continue
            pct = row.get("team_efficiency_pct")
            if pct:
                lookup[(row["team"], row["game_id"])] = float(pct)
    return lookup


def recruiting_to_percentile(recruiting_ranks):
    """Convert recruiting class RANK (1 = best) into a percentile where
    HIGHER percentile = more hyped/better recruited, for consistency with
    team_efficiency_pct's convention (higher = better)."""
    if not recruiting_ranks:
        return {}
    teams_sorted = sorted(recruiting_ranks.items(), key=lambda x: -x[1])  # worst rank number first
    n = len(teams_sorted)
    percentiles = {}
    for i, (team, rank) in enumerate(teams_sorted):
        percentiles[team] = (i / (n - 1) * 100) if n > 1 else 50.0
    return percentiles


def build_season(season):
    games = [g for g in load_games_master() if int(g["season"]) == season]
    if not games:
        return []

    recruiting_ranks = load_recruiting(season)
    reputation_pct = recruiting_to_percentile(recruiting_ranks)
    efficiency_lookup = load_efficiency(season)

    if not recruiting_ranks:
        print(f"  ** NOTE: no recruiting data found for {season} — reputation_gap will be null "
              f"for this season. **")

    output = []
    for g in games:
        game_id = g["game_id"]
        home, away = g["home_team"], g["away_team"]
        line_movement_signed = g.get("line_movement_signed")

        for team, opponent, is_home in [(home, away, True), (away, home, False)]:
            # Reframe movement per-team: positive = market moved toward THIS
            # team being more favored. Signed convention in games_master is
            # negative=home favored, so for the home team a NEGATIVE raw
            # movement (line moving more negative = more home-favored) is
            # actually a POSITIVE move toward them — flip sign for home.
            team_movement = None
            if line_movement_signed not in (None, ""):
                lm = float(line_movement_signed)
                team_movement = -lm if is_home else lm

            eff_pct = efficiency_lookup.get((team, game_id))
            rep_pct = reputation_pct.get(team)
            reputation_gap = round(eff_pct - rep_pct, 2) if (eff_pct is not None and rep_pct is not None) else None

            output.append({
                "season": season,
                "game_id": game_id,
                "team": team,
                "opponent": opponent,
                "is_home": is_home,
                "line_movement_toward_team": team_movement,
                "team_efficiency_pct": eff_pct,
                "reputation_pct_recruiting": round(rep_pct, 2) if rep_pct is not None else None,
                "reputation_gap": reputation_gap,
            })

    return output


def main():
    parser = argparse.ArgumentParser(description="Build market features (reputation gap, line movement).")
    parser.add_argument("--seasons", default="2014-2021")
    args = parser.parse_args()

    if "-" in args.seasons:
        start, end = args.seasons.split("-")
        seasons = list(range(int(start), int(end) + 1))
    else:
        seasons = [int(x) for x in args.seasons.split(",")]

    touching_test = [s for s in seasons if s not in TRAINING_SEASONS]
    if touching_test:
        print(f"** WARNING: seasons {touching_test} are OUTSIDE the training period (2014-2021). **")

    all_rows = []
    for season in seasons:
        print(f"Season {season}: building market features...")
        rows = build_season(season)
        all_rows.extend(rows)
        with_gap = sum(1 for r in rows if r["reputation_gap"] is not None)
        with_movement = sum(1 for r in rows if r["line_movement_toward_team"] is not None)
        print(f"  {len(rows)} team-game rows. {with_gap} with reputation_gap, "
              f"{with_movement} with line_movement_toward_team.")

    if not all_rows:
        print("No output produced.")
        return

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    out_path = os.path.join(PROCESSED_DIR, "market_features.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"\nWrote {len(all_rows)} rows to {out_path}")
    print("Spot-check: find a blue-blood program with an elite recruiting class but a rough season "
          "— reputation_gap should be strongly negative for them. Find an overachieving mid-major "
          "with modest recruiting — should be strongly positive.")
    print("\nNOTE: 'model vs. spread difference' is NOT in this output — needs a percentile-to-points "
          "conversion decision before it can be built. Flagged, not implemented.")


if __name__ == "__main__":
    main()
