"""
audit_rivalry_coverage.py
Reconciles the assembled rivalry_pairs_final.csv against the REAL FBS team
universe — every team name that actually appears in your pulled
games_{season}.csv files, 2014-2025. This is more rigorous than checking
against "official current FBS membership," since it's exactly the team-name
strings any downstream rivalry-matching code would need to work against.

Reports:
  - Total distinct FBS teams found in your data
  - How many have at least one rivalry pair
  - The exact list of teams with ZERO rivalry coverage
  - What fraction of team-seasons (not just teams) are affected, since a
    team with zero coverage matters more if it played many games

This does NOT decide whether Rivalry should be unblocked. It produces the
factual coverage numbers so that decision can be made on real evidence.

Usage:
    python audit_rivalry_coverage.py
    (place rivalry_pairs_final.csv in the same folder, and point
    --raw-dir at your data/raw folder if it's not in the default location)
"""

import argparse
import csv
import os


def load_rivalry_teams(path):
    teams = set()
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            teams.add(row["team_a"].strip())
            teams.add(row["team_b"].strip())
    return teams


def load_fbs_universe(raw_dir):
    """Every team name appearing in games_{season}.csv, 2014-2025, plus a
    count of how many team-season appearances each team has (for weighting
    the audit by real exposure, not just raw team count)."""
    team_appearances = {}
    for season in range(2014, 2026):
        path = os.path.join(raw_dir, "games", f"games_{season}.csv")
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                for team in (row.get("homeTeam"), row.get("awayTeam")):
                    if team:
                        team_appearances[team] = team_appearances.get(team, 0) + 1
    return team_appearances


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rivalry-file", default="rivalry_pairs_final.csv")
    parser.add_argument("--raw-dir", default=os.path.join("..", "..", "data", "raw"))
    args = parser.parse_args()

    if not os.path.exists(args.rivalry_file):
        print(f"ERROR: {args.rivalry_file} not found. Put it in this folder or use --rivalry-file.")
        return

    rivalry_teams = load_rivalry_teams(args.rivalry_file)
    fbs_appearances = load_fbs_universe(args.raw_dir)

    if not fbs_appearances:
        print(f"ERROR: no games_*.csv files found under {args.raw_dir}/games/. "
              f"Use --raw-dir to point at your actual data/raw folder.")
        return

    fbs_teams = set(fbs_appearances.keys())
    covered = fbs_teams & rivalry_teams
    uncovered = fbs_teams - rivalry_teams

    total_appearances = sum(fbs_appearances.values())
    uncovered_appearances = sum(fbs_appearances[t] for t in uncovered)

    print("=" * 60)
    print("RIVALRY COVERAGE AUDIT")
    print("=" * 60)
    print(f"Distinct FBS teams found in your actual pulled data (2014-2025): {len(fbs_teams)}")
    print(f"Teams with at least one rivalry pair: {len(covered)} ({len(covered)/len(fbs_teams)*100:.1f}%)")
    print(f"Teams with ZERO rivalry coverage: {len(uncovered)} ({len(uncovered)/len(fbs_teams)*100:.1f}%)")
    print()
    print(f"Total team-season game appearances: {total_appearances}")
    print(f"Appearances belonging to zero-coverage teams: {uncovered_appearances} "
          f"({uncovered_appearances/total_appearances*100:.1f}% of all team-games)")
    print()
    print("Teams with ZERO rivalry coverage, sorted by how many games they've played")
    print("(higher = more impactful gap if this team turns out to have a real, missed rivalry):")
    print("-" * 60)
    for team in sorted(uncovered, key=lambda t: -fbs_appearances[t]):
        print(f"  {team:<30} {fbs_appearances[team]} games")

    out_path = "uncovered_teams.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["team", "game_appearances_2014_2025"])
        for team in sorted(uncovered, key=lambda t: -fbs_appearances[t]):
            writer.writerow([team, fbs_appearances[team]])
    print(f"\nWrote {out_path} for further investigation.")
    print("\nNext: for teams high on this list, manually check whether Wikipedia documents")
    print("a recognized rivalry that just didn't surface in the search-based extraction.")


if __name__ == "__main__":
    main()
