"""
personnel_features.py
Phase 2 — Personnel/NIL features (§5.2): QB experience, returning
production, coaching continuity, transfer volatility.

Uses data already built/validated this project:
  - qb_start_history.csv (career starts entering each game, transfer-aware)
  - coaches.json (year-by-year coach per team, nested seasons array)
  - roster_{season}.csv (year-over-year roster diff, proxy for returning
    production / transfers — already flagged unreliable per spec §3.3)

COACHING CONTINUITY: same head coach as prior season = True. Does NOT
detect in-season/interim coaching changes — flagged as a known
simplification (Phase 2 scoping doc open item #3), not fixed here.

RETURNING PRODUCTION / TRANSFER VOLATILITY: derived via roster-diff
(player IDs present in both consecutive seasons = returning; present only
in the later season = incoming/transfer; present only in the earlier
season = departed). This is a PROXY, not a verified transfer feed — CFBD
has no clean "transfer" flag, per spec §3.3. Treat accordingly: retained
for signal evaluation, but not to be over-weighted given known unreliability.

Output: data/processed/personnel_features.csv

Usage:
    python src/features/personnel_features.py --seasons 2014-2021
"""

import argparse
import csv
import json
import os

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")
RAW_DIR = os.path.abspath(RAW_DIR)
PROCESSED_DIR = os.path.abspath(os.path.join(RAW_DIR, "..", "processed"))

TRAINING_SEASONS = set(range(2014, 2022))


def load_coaches():
    path = os.path.join(RAW_DIR, "coaches", "coaches.json")
    if not os.path.exists(path):
        print("  ** ERROR: coaches.json not found. **")
        return {}
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    data = payload.get("data", payload)
    # Build (team, year) -> coach name, from the nested seasons array
    coach_by_team_year = {}
    for coach in data:
        name = f"{coach.get('firstName', coach.get('first_name', ''))} {coach.get('lastName', coach.get('last_name', ''))}".strip()
        for season_rec in coach.get("seasons", []):
            team = season_rec.get("school")
            year = season_rec.get("year")
            if team and year:
                coach_by_team_year[(team, year)] = name
    return coach_by_team_year


def load_qb_starts(season):
    path = os.path.join(PROCESSED_DIR, "qb_start_history.csv")
    if not os.path.exists(path):
        print("  ** ERROR: qb_start_history.csv not found. Run qb_start_history.py first. **")
        return {}
    lookup = {}  # (team, game_id) -> career_starts_entering_this_game
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            if int(row["season"]) != season:
                continue
            lookup[(row["team"], row["game_id"])] = int(row["career_starts_entering_this_game"])
    return lookup


def load_roster_ids(season):
    path = os.path.join(RAW_DIR, "roster", f"roster_{season}.csv")
    if not os.path.exists(path):
        return {}
    by_team = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            team = row.get("team")
            player_id = row.get("id") or row.get("playerId")
            if team and player_id:
                by_team.setdefault(team, set()).add(player_id)
    return by_team


def compute_roster_turnover(season):
    """Returning / incoming / departed player counts per team, comparing
    this season's roster to last season's. Proxy only — see module docstring."""
    prior_roster = load_roster_ids(season - 1)
    current_roster = load_roster_ids(season)
    turnover = {}
    for team, current_ids in current_roster.items():
        prior_ids = prior_roster.get(team, set())
        if not prior_ids:
            turnover[team] = None  # no prior-season data to compare — don't fabricate a 0
            continue
        returning = len(current_ids & prior_ids)
        incoming = len(current_ids - prior_ids)
        departed = len(prior_ids - current_ids)
        turnover[team] = {
            "returning": returning,
            "incoming": incoming,
            "departed": departed,
            "returning_pct": round(returning / len(prior_ids) * 100, 1) if prior_ids else None,
            "net_transfer_movement": incoming - departed,
        }
    return turnover


def load_games(season):
    path = os.path.join(RAW_DIR, "games", f"games_{season}.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def build_season(season, coach_lookup):
    games = load_games(season)
    if not games:
        return []

    qb_starts = load_qb_starts(season)
    turnover = compute_roster_turnover(season)

    output = []
    for g in games:
        game_id = g.get("id")
        home, away = g.get("homeTeam"), g.get("awayTeam")

        for team, opponent in [(home, away), (away, home)]:
            if not team:
                continue

            # Coaching continuity: same HC as prior season?
            this_year_coach = coach_lookup.get((team, season))
            last_year_coach = coach_lookup.get((team, season - 1))
            coaching_continuity = (
                this_year_coach == last_year_coach if this_year_coach and last_year_coach else None
            )

            qb_career_starts = qb_starts.get((team, game_id))
            team_turnover = turnover.get(team)

            row = {
                "season": season,
                "game_id": game_id,
                "team": team,
                "opponent": opponent,
                "qb_career_starts_entering_game": qb_career_starts,
                "head_coach": this_year_coach,
                "coaching_continuity": coaching_continuity,
            }
            if team_turnover:
                row.update({
                    "returning_players": team_turnover["returning"],
                    "incoming_players": team_turnover["incoming"],
                    "departed_players": team_turnover["departed"],
                    "returning_pct": team_turnover["returning_pct"],
                    "net_transfer_movement": team_turnover["net_transfer_movement"],
                })
            else:
                row.update({
                    "returning_players": None, "incoming_players": None, "departed_players": None,
                    "returning_pct": None, "net_transfer_movement": None,
                })
            output.append(row)

    return output


def main():
    parser = argparse.ArgumentParser(description="Build personnel features (QB experience, continuity, roster turnover).")
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

    coach_lookup = load_coaches()
    if not coach_lookup:
        return
    print(f"Loaded {len(coach_lookup)} team-year coach records.")

    all_rows = []
    for season in seasons:
        print(f"Season {season}: building personnel features...")
        rows = build_season(season, coach_lookup)
        all_rows.extend(rows)
        with_qb = sum(1 for r in rows if r["qb_career_starts_entering_game"] is not None)
        with_turnover = sum(1 for r in rows if r["returning_pct"] is not None)
        print(f"  {len(rows)} team-game rows. {with_qb} with QB start data, "
              f"{with_turnover} with roster turnover data.")

    if not all_rows:
        print("No output produced.")
        return

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    out_path = os.path.join(PROCESSED_DIR, "personnel_features.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"\nWrote {len(all_rows)} rows to {out_path}")
    print("Spot-check: find a team you know had a coaching change and confirm "
          "coaching_continuity=False that season; find a team with a long-tenured "
          "coach and confirm continuity=True across consecutive years.")


if __name__ == "__main__":
    main()
