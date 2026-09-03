"""
trapgame_signal.py
Evaluates the FULLY FROZEN Candidate B (Trap Game/Schedule-Context Effect,
spec §21) against TRAINING data only (2014-2021). Same discipline as every
other evaluation script in this project.

Frozen chain (spec §21):
  Team X qualifies if: closing favorite in game T; has an immediately-next
  regular-season game T+1 vs Opponent B; OpponentB_pct - OpponentA_pct >= 31.00
  (equality included). Bet: Opponent A (fade Team X).

Usage:
    python trapgame_signal.py
    (no arguments - training period hardcoded)
"""

import csv
import os
from datetime import date as _date

PROCESSED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed")
PROCESSED_DIR = os.path.abspath(PROCESSED_DIR)

TRAINING_SEASONS = list(range(2014, 2022))  # hardcoded, not a parameter
THRESHOLD = 31.00  # LOCKED, spec §21 — equality included

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


def load_games_master():
    path = os.path.join(PROCESSED_DIR, "games_master.csv")
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return [r for r in csv.DictReader(f) if int(r["season"]) in TRAINING_SEASONS]


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
    by_season_team = {}
    for g in games:
        date = parse_date(g.get("date", ""))
        if date is None:
            continue
        for team, opponent in [(g["home_team"], g["away_team"]), (g["away_team"], g["home_team"])]:
            key = (g["season"], team)
            by_season_team.setdefault(key, []).append({
                "game_id": g["game_id"], "date": date, "opponent": opponent,
            })
    for key in by_season_team:
        by_season_team[key].sort(key=lambda x: x["date"])
    return by_season_team


def bet_result(bet_team, favorite, underdog, ats_result):
    if ats_result in ("no_line", "no_score", None, ""):
        return None
    is_favorite_bet = (bet_team == favorite)
    is_underdog_bet = (bet_team == underdog)
    if not is_favorite_bet and not is_underdog_bet:
        return None
    if ats_result == "push":
        return "push"
    if ats_result == "favorite_cover":
        return "win" if is_favorite_bet else "loss"
    if ats_result == "underdog_cover":
        return "win" if is_underdog_bet else "loss"
    return None


def main():
    print("Loading training-period games and building team schedules...")
    games = load_games_master()
    verified = [g for g in games if g.get("market_data_quality_flag") == "verified"]
    schedules = build_team_schedules(games)
    efficiency = load_efficiency()
    print(f"  {len(games)} total, {len(verified)} Verified")

    results = []
    qualifying = 0

    for g in verified:
        season, gid = g["season"], g["game_id"]
        favorite, underdog = g.get("favorite"), g.get("underdog")
        ats_result = g.get("ats_result")
        if not favorite or not underdog:
            continue

        team_x, opponent_a = favorite, underdog
        team_schedule = schedules.get((season, team_x), [])
        idx = next((i for i, gm in enumerate(team_schedule) if gm["game_id"] == gid), None)
        if idx is None or idx + 1 >= len(team_schedule):
            continue  # final regular-season game — excluded per §21

        opponent_b = team_schedule[idx + 1]["opponent"]
        game_t_date = team_schedule[idx]["date"]

        a_pct = efficiency.get((season, opponent_a, gid))
        b_schedule = schedules.get((season, opponent_b), [])
        b_pct = None
        for bg in reversed(b_schedule):
            if bg["date"] < game_t_date:
                b_pct = efficiency.get((season, opponent_b, bg["game_id"]))
                if b_pct is not None:
                    break

        if a_pct is None or b_pct is None:
            continue

        gap = b_pct - a_pct
        if gap < THRESHOLD:
            continue

        qualifying += 1
        r = bet_result(opponent_a, favorite, underdog, ats_result)  # bet Opponent A
        if r:
            results.append((int(season), r))

    print(f"\n{qualifying} games qualify (gap >= {THRESHOLD})")

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

    print(f"\n=== CANDIDATE B (Trap Game/Schedule-Context Effect) — EVALUATION RESULT ===")
    print(f"N={n}, Wins={wins}, Losses={losses}, Pushes={pushes}")
    print(f"ATS%={ats_pct:.2f}, Units={units:.2f}, ROI={roi:.2f}%, Stable seasons={stable_seasons}/8")
    print(f"Survives §6.2: {survives}")
    if not survives:
        print(f"  -> CUT: {reason}")

    with open("trapgame_candidate_b_result.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["signal", "n", "wins", "losses", "pushes", "ats_pct", "units",
                          "roi_pct", "stable_seasons_of_8", "survives_6_2", "reason"])
        writer.writerow(["CandidateB_TrapGame", n, wins, losses, pushes,
                          round(ats_pct, 2), round(units, 2), round(roi, 2), stable_seasons,
                          survives, reason])
    print(f"\nWrote trapgame_candidate_b_result.csv")
    print("Permanent record — not to be re-run with adjusted thresholds after seeing this result.")


if __name__ == "__main__":
    main()
