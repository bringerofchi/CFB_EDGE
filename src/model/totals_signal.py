"""
totals_signal.py
Evaluates the FULLY FROZEN Candidate A (Totals Market Inefficiency, spec
§20) against TRAINING data only (2014-2021). Same discipline as every
other evaluation script in this project: hardcoded training seasons,
Verified-only headline population, mechanical §6.2 application, permanent
unedited output.

Frozen chain (spec §20):
  implied_total = [(TeamA_scored_avg + TeamB_allowed_avg)/2]
                + [(TeamB_scored_avg + TeamA_allowed_avg)/2]
  discrepancy = implied_total - market_total (Verified only)
  |discrepancy| >= 5.59 qualifies (equality included)
  discrepancy >= +5.59 -> bet Over
  discrepancy <= -5.59 -> bet Under

Usage:
    python totals_signal.py
    (no arguments - training period hardcoded, same safety design as
    signal_library.py, signal_library_2a.py, model_vs_spread_signal.py)
"""

import csv
import os
from datetime import date as _date

PROCESSED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed")
PROCESSED_DIR = os.path.abspath(PROCESSED_DIR)
RAW_DIR = os.path.abspath(os.path.join(PROCESSED_DIR, "..", "raw"))

TRAINING_SEASONS = list(range(2014, 2022))  # hardcoded, not a parameter
MIN_PRIOR_GAMES = 2
THRESHOLD = 5.59  # LOCKED, spec §20 — equality included, not a strict inequality

UNIT_WIN = 0.91
UNIT_LOSS = -1.00
UNIT_PUSH = 0.0

SURVIVAL_ATS_FLOOR = 52.4
SURVIVAL_SEASON_STABILITY_PCT = 50.0
SURVIVAL_STABLE_SEASONS_NEEDED = 6
SURVIVAL_MIN_GAMES = 200


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
    path = "totals_reconciliation_detail.csv"
    if not os.path.exists(path):
        print(f"ERROR: {path} not found. Run totals_reconciliation_audit.py first, "
              f"copy the output into this folder.")
        return {}
    market = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if int(r["season"]) not in TRAINING_SEASONS:
                continue
            if r["totals_market_quality_flag"] != "verified":
                continue  # LOCKED per §20
            cfbd_t, sbro_t = to_float(r["cfbd_total"]), to_float(r["sbro_total"])
            market_total = sbro_t if sbro_t is not None else cfbd_t
            if market_total is not None:
                market[(r["season"], r["game_id"])] = market_total
    return market


def load_games():
    games_by_season = {}
    for season in TRAINING_SEASONS:
        path = os.path.join(RAW_DIR, "games", f"games_{season}.csv")
        if not os.path.exists(path):
            continue
        rows = []
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                home_pts, away_pts = to_float(r.get("homePoints")), to_float(r.get("awayPoints"))
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
    implied = {}
    for season, games in games_by_season.items():
        scored, allowed = {}, {}
        for g in games:
            home, away = g["home"], g["away"]

            def avg_or_none(d, team):
                vals = d.get(team, [])
                return (sum(vals) / len(vals)) if len(vals) >= MIN_PRIOR_GAMES else None

            hs, ha = avg_or_none(scored, home), avg_or_none(allowed, home)
            aws, awa = avg_or_none(scored, away), avg_or_none(allowed, away)

            if None not in (hs, ha, aws, awa):
                implied[(str(season), str(g["game_id"]))] = (hs + awa) / 2 + (aws + ha) / 2

            scored.setdefault(home, []).append(g["home_pts"])
            scored.setdefault(away, []).append(g["away_pts"])
            allowed.setdefault(home, []).append(g["away_pts"])
            allowed.setdefault(away, []).append(g["home_pts"])
    return implied


def bet_result(bet_side, actual_total, market_total):
    if bet_side == "Over":
        if actual_total > market_total:
            return "win"
        elif actual_total < market_total:
            return "loss"
        return "push"
    else:  # Under
        if actual_total < market_total:
            return "win"
        elif actual_total > market_total:
            return "loss"
        return "push"


def main():
    print("Loading Verified-only market totals (training seasons only)...")
    market = load_totals_reconciliation()
    if not market:
        return

    print("Computing rolling implied totals (pregame only, MIN_PRIOR_GAMES=2)...")
    games_by_season = load_games()
    implied = compute_implied_totals(games_by_season)

    # Need actual final scores for win/loss determination
    actual_totals = {}
    for season, games in games_by_season.items():
        for g in games:
            actual_totals[(str(season), str(g["game_id"]))] = g["home_pts"] + g["away_pts"]

    results = []
    qualifying = 0
    for key, market_total in market.items():
        if key not in implied:
            continue
        discrepancy = implied[key] - market_total
        if abs(discrepancy) < THRESHOLD:
            continue  # does not qualify
        qualifying += 1
        bet_side = "Over" if discrepancy >= THRESHOLD else "Under"
        actual_total = actual_totals.get(key)
        if actual_total is None:
            continue
        r = bet_result(bet_side, actual_total, market_total)
        results.append((int(key[0]), r))

    print(f"\n{qualifying} games qualify (|discrepancy| >= {THRESHOLD})")

    n = len(results)
    wins = sum(1 for _, r in results if r == "win")
    losses = sum(1 for _, r in results if r == "loss")
    pushes = sum(1 for _, r in results if r == "push")
    decisions = wins + losses
    ats_pct = (wins / decisions * 100) if decisions else 0
    units = wins * UNIT_WIN + losses * UNIT_LOSS + pushes * UNIT_PUSH
    roi = (units / decisions * 100) if decisions else 0

    by_season = {}
    for season, r in results:
        by_season.setdefault(season, {"win": 0, "loss": 0, "push": 0})
        by_season[season][r] += 1
    stable_seasons = 0
    for season in TRAINING_SEASONS:
        s = by_season.get(season, {"win": 0, "loss": 0, "push": 0})
        s_dec = s["win"] + s["loss"]
        s_pct = (s["win"] / s_dec * 100) if s_dec else None
        if s_pct is not None and s_pct > SURVIVAL_SEASON_STABILITY_PCT:
            stable_seasons += 1

    survives = (n >= SURVIVAL_MIN_GAMES and ats_pct >= SURVIVAL_ATS_FLOOR and
                stable_seasons >= SURVIVAL_STABLE_SEASONS_NEEDED)
    if n < SURVIVAL_MIN_GAMES:
        reason = f"sample size {n} below {SURVIVAL_MIN_GAMES}-game floor"
    elif ats_pct < SURVIVAL_ATS_FLOOR:
        reason = f"ATS% {ats_pct:.1f} below {SURVIVAL_ATS_FLOOR}% floor"
    elif stable_seasons < SURVIVAL_STABLE_SEASONS_NEEDED:
        reason = f"only {stable_seasons}/8 seasons above {SURVIVAL_SEASON_STABILITY_PCT}%"
    else:
        reason = "PASSES all §6.2 criteria"

    print(f"\n=== CANDIDATE A (Totals Market Inefficiency) — EVALUATION RESULT ===")
    print(f"N={n}, Wins={wins}, Losses={losses}, Pushes={pushes}")
    print(f"ATS%={ats_pct:.2f}, Units={units:.2f}, ROI={roi:.2f}%, Stable seasons={stable_seasons}/8")
    print(f"Survives §6.2: {survives}")
    if not survives:
        print(f"  -> CUT: {reason}")

    with open("totals_candidate_a_result.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["signal", "n", "wins", "losses", "pushes", "ats_pct", "units",
                          "roi_pct", "stable_seasons_of_8", "survives_6_2", "reason"])
        writer.writerow(["CandidateA_TotalsMarketInefficiency", n, wins, losses, pushes,
                          round(ats_pct, 2), round(units, 2), round(roi, 2), stable_seasons,
                          survives, reason])
    print(f"\nWrote totals_candidate_a_result.csv")
    print("Permanent record, same discipline as every other signal in this project — "
          "not to be re-run with adjusted thresholds after seeing this result.")


if __name__ == "__main__":
    main()
