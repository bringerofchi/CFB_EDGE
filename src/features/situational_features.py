"""
situational_features.py
Phase 2 — Situational features (travel, rest, bye weeks, timezone changes).

Uses data already on hand: venues.json (lat/long/timezone per venue) and
games_{season}.csv, which — confirmed by inspection — already carries
venueId, venue name, and neutralSite per game. This means travel distance
is computed against the ACTUAL game venue, correctly handling neutral-site
and bowl games automatically, rather than assuming both teams always play
at the home team's usual stadium.

HOME VENUE DERIVATION: CFBD doesn't give a direct "this is team X's home
stadium" field independent of games, so each team's home venue is derived
as the most common venueId among their non-neutral-site home games that
season (the modal venue). A team using a temporary venue for 1-2 games
(e.g. stadium construction) would still correctly resolve to their primary
stadium as long as most games were played there.

TRAVEL DISTANCE: haversine (great-circle) distance between the away team's
derived home venue and the actual game venue. This is straight-line
distance, not actual travel distance — a reasonable industry-standard
approximation, not a precise measure of flight/drive distance.

NOT INCLUDED: rivalry game flag. No clean API source; still an open
decision from the Phase 2 scoping doc, not addressed here.

Output: data/processed/situational_factors.csv

Usage:
    python src/features/situational_features.py --seasons 2014-2021
"""

import argparse
import csv
import json
import math
import os
from datetime import date as _date

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")
RAW_DIR = os.path.abspath(RAW_DIR)
PROCESSED_DIR = os.path.abspath(os.path.join(RAW_DIR, "..", "processed"))

TRAINING_SEASONS = set(range(2014, 2022))


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0  # Earth radius, km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def load_venues():
    path = os.path.join(RAW_DIR, "venues", "venues.json")
    if not os.path.exists(path):
        print("  ** ERROR: venues.json not found. Run cfbd_pull.py --endpoints venues first. **")
        return {}
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    data = payload.get("data", payload)
    return {str(v["id"]): v for v in data if v.get("id") is not None}


def load_games(season):
    path = os.path.join(RAW_DIR, "games", f"games_{season}.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def derive_home_venues(games):
    """For each team, the modal venueId among their non-neutral home games."""
    venue_counts = {}
    for g in games:
        if (g.get("neutralSite") or "False").lower() == "true":
            continue
        home = g.get("homeTeam")
        vid = g.get("venueId")
        if not home or not vid:
            continue
        venue_counts.setdefault(home, {})
        venue_counts[home][vid] = venue_counts[home].get(vid, 0) + 1

    home_venue = {}
    for team, counts in venue_counts.items():
        home_venue[team] = max(counts, key=counts.get)
    return home_venue


def parse_date(s):
    try:
        y, m, d = s[:10].split("-")
        return _date(int(y), int(m), int(d))
    except (ValueError, AttributeError, TypeError):
        return None


def build_season(season, venues):
    games = load_games(season)
    if not games:
        return []

    home_venue_by_team = derive_home_venues(games)
    games.sort(key=lambda g: (g.get("startDate") or ""))
    last_game_date = {}

    output = []
    for g in games:
        game_id = g.get("id")
        game_date = parse_date(g.get("startDate", ""))
        venue_id = str(g.get("venueId")) if g.get("venueId") else None
        neutral = (g.get("neutralSite") or "False").lower() == "true"
        venue_info = venues.get(venue_id, {}) if venue_id else {}
        game_lat, game_lon = venue_info.get("latitude"), venue_info.get("longitude")
        game_tz = venue_info.get("timezone")

        for team, opponent, is_home in [(g.get("homeTeam"), g.get("awayTeam"), True),
                                         (g.get("awayTeam"), g.get("homeTeam"), False)]:
            if not team:
                continue

            rest_days = None
            if game_date and team in last_game_date and last_game_date[team]:
                rest_days = (game_date - last_game_date[team]).days
            bye_week = rest_days is not None and rest_days > 10

            travel_km = None
            team_home_venue_id = home_venue_by_team.get(team)
            team_home_venue_info = venues.get(team_home_venue_id, {}) if team_home_venue_id else {}
            team_lat, team_lon = team_home_venue_info.get("latitude"), team_home_venue_info.get("longitude")

            if is_home and not neutral and venue_id == team_home_venue_id:
                travel_km = 0.0
            elif game_lat is not None and game_lon is not None and team_lat is not None and team_lon is not None:
                travel_km = round(haversine_km(team_lat, team_lon, game_lat, game_lon), 1)

            timezone_change = (team_home_venue_info.get("timezone") != game_tz
                                if team_home_venue_info.get("timezone") and game_tz else None)

            output.append({
                "season": season,
                "game_id": game_id,
                "date": (g.get("startDate") or "")[:10],
                "team": team,
                "opponent": opponent,
                "is_home": is_home,
                "neutral_site": neutral,
                "rest_days": rest_days,
                "bye_week": bye_week,
                "travel_km": travel_km,
                "timezone_change": timezone_change,
                "conference_game": g.get("conferenceGame", ""),
            })

            if game_date:
                last_game_date[team] = game_date

    return output


def main():
    parser = argparse.ArgumentParser(description="Build situational features (travel, rest, bye weeks).")
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

    venues = load_venues()
    if not venues:
        return
    print(f"Loaded {len(venues)} venues.")

    all_rows = []
    for season in seasons:
        print(f"Season {season}: building situational features...")
        rows = build_season(season, venues)
        all_rows.extend(rows)
        missing_travel = sum(1 for r in rows if r["travel_km"] is None)
        print(f"  {len(rows)} team-game rows. {missing_travel} with missing travel_km "
              f"(likely a venue not in venues.json or a team with no derivable home venue).")

    if not all_rows:
        print("No output produced.")
        return

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    out_path = os.path.join(PROCESSED_DIR, "situational_factors.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"\nWrote {len(all_rows)} rows to {out_path}")
    print("Spot-check: find a team you know travels far for a specific game (e.g. a Hawaii road "
          "trip) and confirm travel_km is large; find a normal home game and confirm it's ~0.")


if __name__ == "__main__":
    main()
