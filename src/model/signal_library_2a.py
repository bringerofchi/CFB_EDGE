"""
signal_library_2a.py
Phase 2A — Evaluate the 9 frozen candidate signals from spec §16 against
TRAINING data only (2014-2021). Mirrors signal_library.py's structure and
discipline exactly: hardcoded training seasons (no --seasons argument,
so this can never accidentally be pointed at test data), Verified-only
headline population per §3.1, mechanical §6.2 application, permanent
unedited output.

Does NOT touch or reopen Signals 1-4's §15 results in any way — this is
purely additive, a separate permanent record for the 9 new candidates.

Usage:
    python src/model/signal_library_2a.py
"""

import csv
import os
import statistics

PROCESSED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed")
PROCESSED_DIR = os.path.abspath(PROCESSED_DIR)
RAW_DIR = os.path.abspath(os.path.join(PROCESSED_DIR, "..", "raw"))

TRAINING_SEASONS = list(range(2014, 2022))  # hardcoded, not a parameter

UNIT_WIN = 0.91
UNIT_LOSS = -1.00
UNIT_PUSH = 0.0

SURVIVAL_ATS_FLOOR = 52.4
SURVIVAL_SEASON_STABILITY_PCT = 50.0
SURVIVAL_STABLE_SEASONS_NEEDED = 6
SURVIVAL_MIN_GAMES_PRIMARY = 200
SURVIVAL_MIN_GAMES_SECONDARY = 100

POWER4 = {"SEC", "Big Ten", "ACC", "Big 12"}  # frozen exactly, per §16 — never expanded


def to_float(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None


def to_bool(v):
    if v in ("True", "true", "1", True):
        return True
    if v in ("False", "false", "0", False):
        return False
    return None


def load_games_master():
    path = os.path.join(PROCESSED_DIR, "games_master.csv")
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return [r for r in csv.DictReader(f) if int(r["season"]) in TRAINING_SEASONS]


def load_conferences():
    """games_master.csv doesn't carry conference — pull from raw games_{season}.csv,
    which has historical per-season conference membership (never today's realignment)."""
    lookup = {}
    for season in TRAINING_SEASONS:
        path = os.path.join(RAW_DIR, "games", f"games_{season}.csv")
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                gid = r.get("id") or r.get("gameId")
                lookup[(str(season), str(gid), r.get("homeTeam"))] = r.get("homeConference")
                lookup[(str(season), str(gid), r.get("awayTeam"))] = r.get("awayConference")
    return lookup


def load_efficiency():
    path = os.path.join(PROCESSED_DIR, "team_performance_snapshot.csv")
    off_expl, def_epa = {}, {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if int(r["season"]) not in TRAINING_SEASONS:
                continue
            key = (r["season"], r["team"], r["game_id"])
            v1 = to_float(r.get("off_explosiveness_pct"))
            v2 = to_float(r.get("def_epa_allowed_pct_inverted"))
            if v1 is not None:
                off_expl[key] = v1
            if v2 is not None:
                def_epa[key] = v2
    return off_expl, def_epa


def load_personnel():
    path = os.path.join(PROCESSED_DIR, "personnel_features.csv")
    returning_pct, continuity = {}, {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if int(r["season"]) not in TRAINING_SEASONS:
                continue
            key = (r["season"], r["team"], r["game_id"])
            rp = to_float(r.get("returning_pct"))
            cc = to_bool(r.get("coaching_continuity"))
            if rp is not None:
                returning_pct[key] = rp
            if cc is not None:
                continuity[key] = cc
    return returning_pct, continuity


def load_market():
    path = os.path.join(PROCESSED_DIR, "market_features.csv")
    lookup = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if int(r["season"]) not in TRAINING_SEASONS:
                continue
            v = to_float(r.get("reputation_gap"))
            if v is not None:
                lookup[(r["season"], r["team"], r["game_id"])] = v
    return lookup


def load_situational():
    path = os.path.join(PROCESSED_DIR, "situational_factors.csv")
    rest, travel, tz = {}, {}, {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if int(r["season"]) not in TRAINING_SEASONS:
                continue
            key = (r["season"], r["team"], r["game_id"])
            rd = to_float(r.get("rest_days"))
            tk = to_float(r.get("travel_km"))
            tzc = to_bool(r.get("timezone_change"))
            if rd is not None:
                rest[key] = rd
            if tk is not None:
                travel[key] = tk
            if tzc is not None:
                tz[key] = tzc
    return rest, travel, tz


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


def evaluate(name, results):
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
    season_detail = {}
    qualifying_seasons = 0
    for season in TRAINING_SEASONS:
        s = by_season.get(season, {"win": 0, "loss": 0, "push": 0})
        s_dec = s["win"] + s["loss"]
        s_pct = (s["win"] / s_dec * 100) if s_dec else None
        season_detail[season] = s_pct
        if s_dec > 0:
            qualifying_seasons += 1
        if s_pct is not None and s_pct > SURVIVAL_SEASON_STABILITY_PCT:
            stable_seasons += 1

    reasons = []
    if n < SURVIVAL_MIN_GAMES_SECONDARY:
        keep = False
        reasons.append(f"sample size {n} below secondary floor {SURVIVAL_MIN_GAMES_SECONDARY}")
    elif n < SURVIVAL_MIN_GAMES_PRIMARY:
        keep = False
        reasons.append(f"sample size {n} below primary floor {SURVIVAL_MIN_GAMES_PRIMARY}")
    else:
        keep = True
    if keep and ats_pct < SURVIVAL_ATS_FLOOR:
        keep = False
        reasons.append(f"ATS% {ats_pct:.1f} below {SURVIVAL_ATS_FLOOR}% floor")
    if keep and stable_seasons < SURVIVAL_STABLE_SEASONS_NEEDED:
        keep = False
        reasons.append(f"only {stable_seasons}/8 seasons above {SURVIVAL_SEASON_STABILITY_PCT}%")

    return {
        "signal": name, "n": n, "wins": wins, "losses": losses, "pushes": pushes,
        "ats_pct": round(ats_pct, 2), "units": round(units, 2), "roi_pct": round(roi, 2),
        "qualifying_seasons": qualifying_seasons, "stable_seasons_of_8": stable_seasons,
        "survives_6_2": keep, "reason_if_cut": "; ".join(reasons) if reasons else "PASSES",
        "season_detail": season_detail,
    }


def main():
    print("Loading training-period data (2014-2021 only)...")
    games = load_games_master()
    verified = [g for g in games if g.get("market_data_quality_flag") == "verified"]
    print(f"  {len(games)} total, {len(verified)} Verified (headline population)")

    conferences = load_conferences()
    off_expl, def_epa = load_efficiency()
    returning_pct, continuity = load_personnel()
    reputation_gap = load_market()
    rest, travel, tz = load_situational()

    results = {f"C{i}": [] for i in range(1, 10)}

    for g in verified:
        season, gid = g["season"], g["game_id"]
        home, away = g["home_team"], g["away_team"]
        favorite, underdog = g.get("favorite"), g.get("underdog")
        ats = g.get("ats_result")
        if not favorite or not underdog:
            continue

        def r_for(team):
            return bet_result(team, favorite, underdog, ats)

        # C1: Explosive Offense Underdog
        v = off_expl.get((season, underdog, gid))
        if v is not None and v >= 80.0:
            res = r_for(underdog)
            if res:
                results["C1"].append((int(season), res))

        # C2: Elite Defense Favorite
        v = def_epa.get((season, favorite, gid))
        if v is not None and v >= 80.0:
            res = r_for(favorite)
            if res:
                results["C2"].append((int(season), res))

        # C3: Returning Production Mismatch (directional differential)
        u_rp = returning_pct.get((season, underdog, gid))
        f_rp = returning_pct.get((season, favorite, gid))
        if u_rp is not None and f_rp is not None and (u_rp - f_rp) >= 20.0:
            res = r_for(underdog)
            if res:
                results["C3"].append((int(season), res))

        # C4: New Coach Fade
        cc = continuity.get((season, favorite, gid))
        if cc is False:
            res = r_for(underdog)
            if res:
                results["C4"].append((int(season), res))

        # C5: Recruiting-Reputation Mismatch
        rg = reputation_gap.get((season, underdog, gid))
        if rg is not None and rg >= 30.0:
            res = r_for(underdog)
            if res:
                results["C5"].append((int(season), res))

        # C6: Rest Advantage (symmetric)
        h_rest = rest.get((season, home, gid))
        a_rest = rest.get((season, away, gid))
        if h_rest is not None and a_rest is not None:
            diff = h_rest - a_rest
            if diff >= 4.0:
                res = r_for(home)
                if res:
                    results["C6"].append((int(season), res))
            elif diff <= -4.0:
                res = r_for(away)
                if res:
                    results["C6"].append((int(season), res))

        # C7: Travel Fade
        v = travel.get((season, favorite, gid))
        if v is not None and v >= 2000.0:
            res = r_for(underdog)
            if res:
                results["C7"].append((int(season), res))

        # C8: Timezone Disruption Fade
        v = tz.get((season, favorite, gid))
        if v is True:
            res = r_for(underdog)
            if res:
                results["C8"].append((int(season), res))

        # C9: Power-Conference Overreach (historical conference membership)
        fav_conf = conferences.get((season, gid, favorite))
        dog_conf = conferences.get((season, gid, underdog))
        if fav_conf in POWER4 and dog_conf is not None and dog_conf not in POWER4:
            res = r_for(underdog)
            if res:
                results["C9"].append((int(season), res))

    names = {
        "C1": "Candidate1_ExplosiveOffenseUnderdog",
        "C2": "Candidate2_EliteDefenseFavorite",
        "C3": "Candidate3_ReturningProductionMismatch",
        "C4": "Candidate4_NewCoachFade",
        "C5": "Candidate5_RecruitingReputationMismatch",
        "C6": "Candidate6_RestAdvantage",
        "C7": "Candidate7_TravelFade",
        "C8": "Candidate8_TimezoneDisruptionFade",
        "C9": "Candidate9_PowerConferenceOverreach",
    }

    summary = [evaluate(names[k], v) for k, v in results.items()]

    print(f"\n{'Signal':<42}{'N':<7}{'ATS%':<8}{'Units':<9}{'ROI%':<8}{'Stable':<9}{'Survives'}")
    for s in summary:
        print(f"{s['signal']:<42}{s['n']:<7}{s['ats_pct']:<8}{s['units']:<9}{s['roi_pct']:<8}"
              f"{s['stable_seasons_of_8']}/8      {s['survives_6_2']}")
        if not s["survives_6_2"]:
            print(f"    -> CUT: {s['reason_if_cut']}")

    summary_path = os.path.join(PROCESSED_DIR, "signal_evaluation_summary_2a.csv")
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["signal", "n", "wins", "losses", "pushes", "ats_pct", "units", "roi_pct",
                      "qualifying_seasons", "stable_seasons_of_8", "survives_6_2", "reason_if_cut"] + \
                     [f"season_{s}_ats_pct" for s in TRAINING_SEASONS]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for s in summary:
            row = {k: v for k, v in s.items() if k != "season_detail"}
            for season in TRAINING_SEASONS:
                row[f"season_{season}_ats_pct"] = s["season_detail"].get(season)
            writer.writerow(row)
    print(f"\nWrote {summary_path}")
    print("\nThis is a permanent record, same discipline as §15 — not to be re-run with adjusted "
          "thresholds after seeing these results.")


if __name__ == "__main__":
    main()
