"""
efficiency_features.py
Phase 2, Step 2 — Team Efficiency features (§5.1 of the spec).

Processes the PPA and advanced-stats JSON already pulled in Phase 1A
(data/raw/stats/ppa/, data/raw/stats/advanced/) into ROLLING, WITHIN-SEASON
PERCENTILE features per team per game — computed using only games played
BEFORE the game being evaluated, per spec §5.1. This is not a full-season
hindsight percentile; a team's week-3 percentile only reflects weeks 1-2.

Output: data/processed/team_performance_snapshot.csv
  One row per (season, team, game_id): rolling pre-game averages and
  percentiles for offensive/defensive EPA, success rate, explosiveness,
  plus the composite "team efficiency percentile" used by Signal 1
  (Hidden Efficiency Underdog, frozen definition per spec §6).

MINIMUM SAMPLE RULE (Phase 2 scoping open item, resolved here): a team's
first game of the season has ZERO prior games to average, so no rolling
percentile can be computed. Per spec's missing-data-handling principle
(exclude, don't default), games before a team has at least MIN_GAMES prior
games in that season get a null percentile, not a synthetic one. MIN_GAMES
defaults to 2 (percentile requires at least 2 prior games) — a genuinely
debatable choice, not a certainty; revisit if week-1/2 exclusion turns out
to matter more than expected once real signal evaluation starts.

READ BEFORE TRUSTING THE FIELD NAMES: CFBD's /ppa/games and
/stats/game/advanced responses nest metrics under "offense"/"defense"
objects (e.g. offense.overall, defense.overall for PPA; offense.successRate,
offense.explosiveness for advanced stats) — confirmed against CFBD API
consumer library documentation, not against a live pull, since this
environment can't reach the CFBD API directly. This script tries the
nested structure first and falls back to flat/camelCase variants, and
PRINTS A LOUD WARNING if it can't find expected fields in your actual
files rather than silently producing zeros — if you see that warning,
tell me and I'll adjust the field-name handling to match reality.

Usage:
    python src/data_collection/efficiency_features.py --seasons 2014-2021
    (training period only by default — see --seasons to override, but
    doing so touches the test period and should not happen casually)
"""

import argparse
import csv
import json
import os
import sys

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")
RAW_DIR = os.path.abspath(RAW_DIR)
PROCESSED_DIR = os.path.abspath(os.path.join(RAW_DIR, "..", "processed"))

MIN_PRIOR_GAMES = 2  # see MINIMUM SAMPLE RULE docstring above
TRAINING_SEASONS = set(range(2014, 2022))  # 2014-2021 per spec §4


def _get(d, *paths, default=None):
    """Try several possible field-name shapes, nested or flat, before giving up."""
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


def load_ppa(season):
    path = os.path.join(RAW_DIR, "stats", "ppa", f"ppa_{season}.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("data", payload)


def load_advanced(season):
    path = os.path.join(RAW_DIR, "stats", "advanced", f"advanced_{season}.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("data", payload)


def load_games(season):
    """For chronological ordering — date, not week number. week is kept only
    for display; date is what actually determines processing order (see
    BUG FIX note in extract_team_game_records/compute_rolling_percentiles)."""
    path = os.path.join(RAW_DIR, "games", f"games_{season}.csv")
    if not os.path.exists(path):
        return {}
    lookup = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            gid = row.get("id") or row.get("gameId")
            if gid:
                lookup[str(gid)] = {
                    "week": row.get("week"),
                    "date": (row.get("startDate") or row.get("start_date") or "")[:10],
                    "home_team": row.get("homeTeam") or row.get("home_team"),
                    "away_team": row.get("awayTeam") or row.get("away_team"),
                }
    return lookup


def extract_team_game_records(season):
    """Flatten PPA + advanced JSON into one row per (team, game) with the
    raw metrics needed, regardless of which of the two files supplied which field."""
    games_lookup = load_games(season)
    records = {}  # (team, game_id) -> dict of raw metrics

    missing_field_warnings = set()

    for row in load_ppa(season):
        game_id = str(_get(row, "gameId", "game_id", default=""))
        team = _get(row, "team", default="")
        if not game_id or not team:
            continue
        off_epa = _get(row, "offense.overall", "offenseOverall", "off_overall")
        def_epa = _get(row, "defense.overall", "defenseOverall", "def_overall")
        if off_epa is None or def_epa is None:
            missing_field_warnings.add("PPA offense.overall/defense.overall")
        key = (team, game_id)
        records.setdefault(key, {})
        records[key]["off_epa"] = off_epa
        records[key]["def_epa_allowed"] = def_epa  # lower = better defense

    for row in load_advanced(season):
        game_id = str(_get(row, "gameId", "game_id", default=""))
        team = _get(row, "team", default="")
        if not game_id or not team:
            continue
        off_sr = _get(row, "offense.successRate", "offenseSuccessRate")
        def_sr = _get(row, "defense.successRate", "defenseSuccessRate")
        off_expl = _get(row, "offense.explosiveness", "offenseExplosiveness")
        def_expl = _get(row, "defense.explosiveness", "defenseExplosiveness")
        if off_sr is None:
            missing_field_warnings.add("advanced offense.successRate")
        key = (team, game_id)
        records.setdefault(key, {})
        records[key]["off_success_rate"] = off_sr
        records[key]["def_success_rate_allowed"] = def_sr
        records[key]["off_explosiveness"] = off_expl
        records[key]["def_explosiveness_allowed"] = def_expl

    if missing_field_warnings:
        print(f"  ** WARNING season {season}: could not find expected field(s): "
              f"{', '.join(missing_field_warnings)}. Check raw JSON structure — "
              f"this script may be reading the wrong keys. Not silently defaulting to 0. **")

    # BUG FIX: attach both week (display only) and date (actual ordering key).
    # week alone caused two real corruptions: (1) sorted as text not integers,
    # so "11" < "2" lexicographically, scrambling any season with 10+ weeks;
    # (2) postseason games (conference championship, bowls, playoff) often
    # get their own week-numbering that collides with regular-season week 1-3,
    # so a team's bowl game could be processed as if it happened before their
    # September opener. Date sidesteps both — it's unambiguous and naturally
    # places postseason games at the true end of the season.
    out = []
    skipped_no_date = 0
    for (team, game_id), metrics in records.items():
        g = games_lookup.get(game_id)
        week = g.get("week") if g else None
        date = g.get("date") if g else None
        if not date:
            skipped_no_date += 1
            continue  # can't chronologically order a game with no date — exclude, don't guess
        out.append({"team": team, "game_id": game_id, "week": week, "date": date, **metrics})
    if skipped_no_date:
        print(f"  ** NOTE season {season}: {skipped_no_date} team-game record(s) had no matching "
              f"date in games_{season}.csv and were excluded (can't chronologically order them). **")
    return out


def compute_rolling_percentiles(season_records):
    """For each team-game, compute the team's rolling pre-game average for
    each metric (using only strictly-prior games that season), then rank
    that average as a percentile against all other teams' rolling averages
    at the same point in the season. Returns rows ready for CSV output.

    BUG FIX: this used to group/order by "week", which (a) sorted as text
    not integers ("11" < "2" lexicographically) and (b) collided between
    regular-season and postseason week-numbering (a bowl game and a week-1
    opener can both be labeled week 1). Both silently scrambled chronological
    order for every season with 10+ weeks. Now ordered by actual game date."""
    # Group by team, sort by ACTUAL DATE, not week number
    by_team = {}
    for r in season_records:
        by_team.setdefault(r["team"], []).append(r)
    for team in by_team:
        by_team[team].sort(key=lambda r: r["date"])

    metrics = ["off_epa", "def_epa_allowed", "off_success_rate",
               "def_success_rate_allowed", "off_explosiveness", "def_explosiveness_allowed"]

    output_rows = []
    running = {team: {m: [] for m in metrics} for team in by_team}

    # Process date by date across ALL teams so percentiles compare same-point-in-time state
    all_dates = sorted({r["date"] for recs in by_team.values() for r in recs})

    for dt in all_dates:
        # Snapshot: each team's rolling average BEFORE this date's game(s)
        snapshot = {}
        for team, recs in by_team.items():
            avgs = {}
            for m in metrics:
                vals = [v for v in running[team][m] if v is not None]
                avgs[m] = (sum(vals) / len(vals)) if len(vals) >= MIN_PRIOR_GAMES else None
            snapshot[team] = avgs

        # Percentile rank each team's snapshot average against the full league snapshot at this date
        percentiles = {}
        for m in metrics:
            valid = [(t, snapshot[t][m]) for t in snapshot if snapshot[t][m] is not None]
            valid.sort(key=lambda x: x[1])
            n = len(valid)
            ranks = {t: (i / (n - 1) * 100 if n > 1 else 50.0) for i, (t, v) in enumerate(valid)}
            percentiles[m] = ranks

        # Emit rows for every team playing on this date, then update running averages
        for team, recs in by_team.items():
            this_date_recs = [r for r in recs if r["date"] == dt]
            for r in this_date_recs:
                off_pct = percentiles["off_epa"].get(team)
                def_pct_raw = percentiles["def_epa_allowed"].get(team)
                def_pct_inverted = (100 - def_pct_raw) if def_pct_raw is not None else None
                team_efficiency_pct = None
                if off_pct is not None and def_pct_inverted is not None:
                    team_efficiency_pct = round((off_pct + def_pct_inverted) / 2, 2)

                output_rows.append({
                    "season": None,  # filled in by caller
                    "team": team,
                    "game_id": r["game_id"],
                    "week": r.get("week"),  # display only — date is the real ordering key now
                    "date": dt,
                    "prior_games_this_season": len([v for v in running[team]["off_epa"] if v is not None]),
                    "off_epa_pct": round(off_pct, 2) if off_pct is not None else None,
                    "def_epa_allowed_pct_inverted": round(def_pct_inverted, 2) if def_pct_inverted is not None else None,
                    "off_success_rate_pct": round(percentiles["off_success_rate"].get(team), 2) if percentiles["off_success_rate"].get(team) is not None else None,
                    "off_explosiveness_pct": round(percentiles["off_explosiveness"].get(team), 2) if percentiles["off_explosiveness"].get(team) is not None else None,
                    "team_efficiency_pct": team_efficiency_pct,
                })
            # Now update running averages with this date's actual results (for the NEXT date's snapshot)
            for r in this_date_recs:
                for m in metrics:
                    running[team][m].append(r.get(m))

    return output_rows


def main():
    parser = argparse.ArgumentParser(description="Build rolling efficiency percentile features.")
    parser.add_argument("--seasons", default="2014-2021",
                         help="Default is training period only (2014-2021). "
                              "Overriding this touches the test period — do not do so casually.")
    args = parser.parse_args()

    if "-" in args.seasons:
        start, end = args.seasons.split("-")
        seasons = list(range(int(start), int(end) + 1))
    else:
        seasons = [int(x) for x in args.seasons.split(",")]

    touching_test = [s for s in seasons if s not in TRAINING_SEASONS]
    if touching_test:
        print(f"** WARNING: seasons {touching_test} are OUTSIDE the training period (2014-2021). **")
        print("** Per spec §4, building features on test-period data before the test phase begins **")
        print("** risks contaminating the test window. Confirm this is intentional. **")

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    all_rows = []
    for season in seasons:
        print(f"Season {season}: extracting raw team-game records...")
        records = extract_team_game_records(season)
        if not records:
            print(f"  No PPA/advanced data found for {season} — skipping.")
            continue
        print(f"  {len(records)} team-game records found. Computing rolling percentiles...")
        rows = compute_rolling_percentiles(records)
        for r in rows:
            r["season"] = season
        all_rows.extend(rows)
        print(f"  {len(rows)} feature rows produced.")

    if not all_rows:
        print("No output produced — check that ppa_*.json / advanced_*.json exist in data/raw/stats/.")
        return

    out_path = os.path.join(PROCESSED_DIR, "team_performance_snapshot.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"\nWrote {len(all_rows)} rows to {out_path}")
    print("Spot-check a few rows before trusting this: does a team you know was good in week 5 "
          "show a high team_efficiency_pct using only weeks 1-4? That's the real test.")


if __name__ == "__main__":
    main()
