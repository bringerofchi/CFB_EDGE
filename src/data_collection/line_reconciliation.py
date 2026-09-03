"""
line_reconciliation.py
Phase 1A.2 Gate 2 — Market integrity.

Per CFB Edge Lab Project Specification v1.3 §3.1:
  - 2014-2022: cross-check SBRO (primary) against CFBD (secondary).
      Verified        = closing spreads agree within 2.0 pts (v1.4)
      Source variance = closing spreads disagree 2.0-7.0 pts — likely normal
                         book-to-book variance, retained for sensitivity analysis
      Source conflict = closing spreads disagree beyond 7.0 pts — likely
                         parsing error/bad row, excluded until reviewed
      Single source   = only one side has a usable spread
      Missing         = neither side has a usable spread
  - 2023-2025: CFBD only, no cross-check possible. Every game with a
      CFBD closing line is Single source by construction; games with
      no CFBD line at all are Missing.

Output:
  analysis/validation/market_quality_summary.csv
    season | total_games | verified | source_conflict | single_source | missing

  data/processed/lines_reconciled_<season>.csv (per-game detail, one row
    per CFBD game with whatever SBRO/CFBD spread values and flag were
    resolved for it) — this is the input games_master.csv construction
    will consume next.

READ BEFORE TRUSTING THE OUTPUT:
  Matching an SBRO row to a CFBD game requires matching on (date, team
  names), and the two sources spell team names differently — SBRO uses
  compressed/abbreviated forms ("TexSanAntonio", "NCState", "TennesseeU"),
  CFBD uses full official names ("UTSA", "NC State", "Tennessee"). This
  script normalizes both sides and applies a starter alias table, but
  that table is NOT exhaustive across 130+ FBS programs plus the FCS/G5
  opponents that show up in SBRO's archive. The script prints its own
  match rate per season so you can see the real number, not an assumed
  one. A match rate meaningfully below ~95% for a season means the alias
  table needs expansion before that season's Verified/Source conflict
  numbers can be trusted — treat a low match rate as a data problem to
  fix, not as evidence the games are actually "Missing".
"""

import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from datetime import date

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")
RAW_DIR = os.path.abspath(RAW_DIR)
PROCESSED_DIR = os.path.abspath(os.path.join(RAW_DIR, "..", "processed"))
VALIDATION_DIR = os.path.abspath(os.path.join(RAW_DIR, "..", "..", "analysis", "validation"))

SBRO_MIN_SEASON = 2014
SBRO_MAX_SEASON = 2022
ALL_SEASONS_MIN = 2014
ALL_SEASONS_MAX = 2025

VERIFIED_TOLERANCE = 2.0     # points, per spec §3.1 v1.4 — was 0.5, widened after Phase 1A.2 findings
SOURCE_VARIANCE_MAX = 7.0    # points — above this, treat as likely data corruption, not book variance

# Starter alias table: SBRO raw name (normalized) -> CFBD school name.
# NOT exhaustive. Expand this as match-rate diagnostics reveal gaps.
SBRO_TO_CFBD_ALIASES = {
    "texsanantonio": "UTSA",
    "ncstate": "NC State",
    "tennesseeu": "Tennessee",
    "middletennst": "Middle Tennessee",
    "soillinois": "Southern Illinois",
    "westvirginia": "West Virginia",
    "mississippistate": "Mississippi State",
    "miamiflorida": "Miami",
    "miamiohio": "Miami (OH)",
    "ullafayette": "Louisiana",
    "ulmonroe": "Louisiana Monroe",
    "southcarolinast": "South Carolina State",
    "kansasstate": "Kansas State",
    "oklahomastate": "Oklahoma State",
    "arizonastate": "Arizona State",
    "coloradostate": "Colorado State",
    "washingtonstate": "Washington State",
    "michiganstate": "Michigan State",
    "pennstate": "Penn State",
    "floridastate": "Florida State",
    "ohiostate": "Ohio State",
    "sanjosestate": "San Jose State",
    "sandiegostate": "San Diego State",
    "fresnostate": "Fresno State",
    "boisestate": "Boise State",
    "utahstate": "Utah State",
    "newmexicostate": "New Mexico State",
    "georgiastate": "Georgia State",
    "arkansasstate": "Arkansas State",
    "appalachianst": "App State",  # CFBD's official name is "App State", not "Appalachian State"
    "jacksonvillest": "Jacksonville State",
    "texasstate": "Texas State",
    "kentst": "Kent State",
    "ballstate": "Ball State",
    "iowastate": "Iowa State",
    "minnesotau": "Minnesota",
    "buffalou": "Buffalo",
    "cincinnatiu": "Cincinnati",
    "notredame": "Notre Dame",
    "texasa&m": "Texas A&M",
    "smu": "SMU",
    "tcu": "TCU",
    "usc": "USC",
    "ucla": "UCLA",
    "byu": "BYU",
    "utep": "UTEP",
    "unlv": "UNLV",
    "louisianatech": "Louisiana Tech",
    "centralflorida": "UCF",
    "connecticut": "UConn",
    "floridaintl": "Florida International",
    "houstonu": "Houston",
}


def _expand_state_variants(aliases):
    """SBRO may write '___ State' schools as either '...St' (e.g. 'ArizonaSt')
    or spelled out ('ArizonaState') — the exact convention wasn't confirmed
    from a live re-scrape, so generate both key forms for every alias whose
    CFBD value ends in 'State', pointing at the same name. Never overwrites
    an existing explicit entry, so manual corrections above always win."""
    expanded = dict(aliases)
    for key, value in list(aliases.items()):
        if not value.endswith("State"):
            continue
        stem = key[:-5] if key.endswith("state") else (key[:-2] if key.endswith("st") else key)
        for variant in (stem + "st", stem + "state"):
            expanded.setdefault(variant, value)
    return expanded


SBRO_TO_CFBD_ALIASES = _expand_state_variants(SBRO_TO_CFBD_ALIASES)


def _strip_to_alnum(name):
    """Lowercase, strip accents (é -> e, not dropped), remove all non-alnum."""
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_name = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", ascii_name.lower())


def normalize(name):
    """Lowercase, strip punctuation/whitespace/accents, apply alias table.
    BUG FIX (v1.4.1): previously the alias table's substituted value was only
    .lower()'d, not re-stripped of spaces/punctuation — so e.g. 'arizonastate'
    correctly matched the alias key, but the returned alias VALUE 'Arizona
    State' became 'arizona state' (space intact), which then could never
    match CFBD's fully-stripped 'arizonastate'. This broke matching for every
    multi-word aliased school. Now the alias output goes through the same
    stripping function as everything else, guaranteeing a consistent format."""
    n = _strip_to_alnum(name)
    if n in SBRO_TO_CFBD_ALIASES:
        return _strip_to_alnum(SBRO_TO_CFBD_ALIASES[n])
    return n


def normalize_cfbd(name):
    return _strip_to_alnum(name)


def sbro_date_to_iso(date_raw, season):
    """
    SBRO dates are MMDD with no year (e.g. '828' = Aug 28, '105' = Jan 5).
    Regular season runs Aug-Dec of `season`; bowl games in Jan belong to
    `season + 1` on the calendar despite being part of the `season`
    campaign.
    """
    date_raw = date_raw.strip()
    if len(date_raw) == 3:
        month, day = int(date_raw[0]), int(date_raw[1:])
    elif len(date_raw) == 4:
        month, day = int(date_raw[:2]), int(date_raw[2:])
    else:
        return None
    year = season if month >= 6 else season + 1
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def load_sbro(season):
    path = os.path.join(RAW_DIR, "lines", "sbro", f"sbro_{season}.csv")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            iso_date = sbro_date_to_iso(row["date_raw"], season)
            rows.append({
                "iso_date": iso_date,
                "home_norm": normalize(row["home_team_raw"]),
                "away_norm": normalize(row["away_team_raw"]),
                "closing_spread": _safe_float(row.get("closing_spread_parsed")),
                "opening_spread": _safe_float(row.get("opening_spread_parsed")),
                "ambiguous": row.get("spread_ambiguous_flag") == "True",
                # Raw, undisambiguated values — kept so reconciliation can pick
                # whichever is actually closer to CFBD's spread instead of
                # trusting line_import.py's "smaller number = spread" guess,
                # which is confirmed to fail on lopsided/blowout games.
                "raw_home_close": _safe_float(row.get("home_close_raw")),
                "raw_away_close": _safe_float(row.get("away_close_raw")),
                "raw_home_open": _safe_float(row.get("home_open_raw")),
                "raw_away_open": _safe_float(row.get("away_open_raw")),
            })
    return rows


def load_cfbd_games(season):
    path = os.path.join(RAW_DIR, "games", f"games_{season}.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def load_cfbd_lines(season):
    path = os.path.join(RAW_DIR, "lines", "cfbd", f"lines_{season}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    games = payload.get("data", payload)  # tolerate un-enveloped files
    by_id = {}
    for g in games:
        game_id = g.get("id") or g.get("gameId")
        lines = g.get("lines", [])
        closing, opening = None, None
        # Prefer a consensus-style line if present; else average whatever exists.
        preferred = [l for l in lines if (l.get("provider") or "").lower() in
                     ("consensus", "draftkings", "bovada")]
        pool = preferred if preferred else lines
        closes = [_safe_float(l.get("spread")) for l in pool if l.get("spread") is not None]
        opens = [_safe_float(l.get("spreadOpen")) for l in pool if l.get("spreadOpen") is not None]
        closes = [c for c in closes if c is not None]
        opens = [o for o in opens if o is not None]
        if closes:
            closing = sum(closes) / len(closes)
        if opens:
            opening = sum(opens) / len(opens)
        by_id[game_id] = {
            "closing_spread": closing,
            "opening_spread": opening,
            "home_team": g.get("homeTeam") or g.get("home_team"),
            "away_team": g.get("awayTeam") or g.get("away_team"),
            "start_date": (g.get("startDate") or g.get("start_date") or "")[:10],
        }
    return by_id


def _safe_float(v):
    try:
        return abs(float(v))  # magnitude only; sign convention differs across sources
    except (TypeError, ValueError):
        return None


def load_fbs_game_ids(season):
    """Restrict the lines universe to actual FBS games, per games_{season}.csv.
    The /lines endpoint is NOT classification-filtered by CFBD and includes
    many non-FBS games, especially from 2022 onward when odds coverage
    expanded — without this filter, total_games gets badly inflated."""
    games = load_cfbd_games(season)
    ids = set()
    for g in games:
        gid = g.get("id") or g.get("game_id")
        if gid:
            ids.add(gid)
    return ids


def resolve_line(raw_candidates, reference_value, fallback_value=None, max_plausible_distance=20.0):
    """Shared disambiguation engine for BOTH opening and closing spreads.
    Per the confirmed blowout-game bug (spec §11, SMU/Baylor 2015), SBRO's
    raw spread/total pairing can't be trusted blindly. When a reference value
    exists (from CFBD), pick whichever raw candidate is closer to it — that's
    strictly better than a guess. When no reference exists (most of the
    dataset, since CFBD's opening-line coverage is itself sparse — see
    spec §11's opening-spread coverage gap), fall back to the pre-computed
    heuristic value. Using ONE function for both open and close means any
    future improvement to the disambiguation logic benefits both instead of
    risking the two silently diverging.

    BUG FIX (found via opening-line validation): when only ONE raw candidate
    exists — common for opening lines, scraped less reliably than closing
    lines — the old logic blindly trusted it even when wildly far from the
    reference (confirmed cases up to 64.5 points off: a pick'em game's true
    ~1-point opener replaced by a stray ~65-point value, almost certainly a
    mis-scraped total). Picking "closest of two real candidates" is safe;
    picking "the only candidate, no matter how implausible" is not. A lone
    candidate is now only trusted within max_plausible_distance of the
    reference; otherwise treated as no reliable value, not a wrong one."""
    candidates = [v for v in raw_candidates if v is not None]
    if reference_value is not None and candidates:
        best = min(candidates, key=lambda v: abs(v - reference_value))
        if abs(best - reference_value) <= max_plausible_distance:
            return best
        return None  # even the closest candidate is implausibly far — don't guess
    if fallback_value is not None:
        return fallback_value
    return None


def reconcile_season(season):
    cfbd_lines = load_cfbd_lines(season)
    fbs_ids = load_fbs_game_ids(season)
    if fbs_ids:
        # Coerce both sides to string for comparison — IDs may come through
        # as int from one source and str from the other depending on JSON/CSV parsing.
        fbs_ids_str = {str(i) for i in fbs_ids}
        cfbd_lines = {gid: v for gid, v in cfbd_lines.items() if str(gid) in fbs_ids_str}
    sbro_rows = load_sbro(season) if SBRO_MIN_SEASON <= season <= SBRO_MAX_SEASON else []

    # Build an index of SBRO rows by normalized team name -> list of rows,
    # since matching purely on exact calendar date fails whenever a game's
    # local kickoff date differs from CFBD's UTC-stored date (very common
    # for evening kickoffs — a 7pm ET game is already past midnight UTC).
    from datetime import date as _date, timedelta as _timedelta

    def _parse_iso(s):
        try:
            y, m, d = (int(x) for x in s.split("-"))
            return _date(y, m, d)
        except (ValueError, AttributeError):
            return None

    sbro_by_team = {}
    for r in sbro_rows:
        d = _parse_iso(r["iso_date"])
        if d is None:
            continue
        r["_date_obj"] = d
        sbro_by_team.setdefault(r["home_norm"], []).append(r)
        sbro_by_team.setdefault(r["away_norm"], []).append(r)

    def find_sbro_match(home_norm, away_norm, cfbd_date_str):
        """Match by home team name + date (within 1 day, handles timezone
        rollover), THEN verify the away team also matches when possible.

        BUG FIX: previously only checked home team + date, never
        cross-verified the away team at all — meaning a same-home-team
        doubleheader-adjacent scheduling quirk (rare, but real) could
        produce a false match with no cross-check at all. Fixed as a
        PREFERENCE, not a strict requirement: if a candidate's away team
        also matches, prefer it; if the best date-matched candidate's away
        team does NOT match, still return it (rather than reject and lose
        the match entirely) but flag it — this avoids silently reducing
        the already-validated match rate due to alias-table gaps on the
        away-team side specifically, while still surfacing genuine
        mismatches for review instead of accepting them silently."""
        candidates = sbro_by_team.get(home_norm, [])
        if not candidates:
            return None, False
        cfbd_d = _parse_iso(cfbd_date_str)
        if cfbd_d is None:
            if len(candidates) == 1:
                c = candidates[0]
                away_ok = away_norm in (c["home_norm"], c["away_norm"]) if away_norm else None
                return c, away_ok
            return None, False

        # Collect all date-window candidates, then prefer away-verified ones
        in_window = [(r, abs((r["_date_obj"] - cfbd_d).days)) for r in candidates]
        in_window = [(r, d) for r, d in in_window if d <= 1]
        if not in_window:
            return None, False

        def away_matches(r):
            # Robust check: both CFBD's home and away teams should appear
            # somewhere in this SBRO row's two normalized team fields,
            # regardless of which side SBRO happened to list them on.
            return away_norm is not None and away_norm in (r["home_norm"], r["away_norm"])

        away_verified = [(r, d) for r, d in in_window if away_matches(r)]
        pool = away_verified if away_verified else in_window
        best = min(pool, key=lambda x: x[1])[0]
        return best, bool(away_verified)

    counts = {"verified": 0, "source_variance": 0, "source_conflict": 0, "single_source": 0, "missing": 0}
    matched_sbro = 0
    away_unverified_matches = 0
    detail_rows = []
    unmatched_cfbd_teams = {}  # normalized name -> original name, for games with no SBRO match

    for game_id, cfbd in cfbd_lines.items():
        home_norm = normalize_cfbd(cfbd["home_team"])
        away_norm = normalize_cfbd(cfbd.get("away_team", ""))
        cfbd_date = cfbd["start_date"]

        sbro_match, away_verified = find_sbro_match(home_norm, away_norm, cfbd_date)
        if sbro_match:
            matched_sbro += 1
            if not away_verified:
                away_unverified_matches += 1
        elif season <= SBRO_MAX_SEASON and sbro_rows:
            unmatched_cfbd_teams[home_norm] = cfbd["home_team"]

        cfbd_close = cfbd["closing_spread"]
        cfbd_open = cfbd.get("opening_spread")  # was extracted by load_cfbd_lines but previously unused downstream

        sbro_close_fallback = sbro_match.get("closing_spread") if sbro_match else None
        sbro_open_fallback = sbro_match.get("opening_spread") if sbro_match else None

        sbro_close = None
        sbro_open = None
        opening_confidence = None
        if sbro_match:
            close_candidates = (sbro_match.get("raw_home_close"), sbro_match.get("raw_away_close"))
            sbro_close = resolve_line(close_candidates, cfbd_close, sbro_close_fallback)

            open_candidates = (sbro_match.get("raw_home_open"), sbro_match.get("raw_away_open"))
            sbro_open = resolve_line(open_candidates, cfbd_open, sbro_open_fallback)
            # Confidence: was this resolved against a real CFBD reference, or
            # just the unvalidated fallback heuristic? Per this session's
            # decision, opening-line data is NOT promoted to games_master.csv
            # until a dedicated validation pass (validate_opening_lines.py)
            # confirms accuracy — this field records which situation applied,
            # so that validation can be done honestly per-confidence-tier.
            if cfbd_open is not None and any(v is not None for v in open_candidates):
                opening_confidence = "cross_validated_vs_cfbd"
            elif sbro_open is not None:
                opening_confidence = "sbro_heuristic_only_unvalidated"

        difference = None

        if season > SBRO_MAX_SEASON:
            # No SBRO coverage at all for this season — single source by construction.
            flag = "single_source" if cfbd_close is not None else "missing"
        else:
            if cfbd_close is not None and sbro_close is not None:
                difference = round(abs(cfbd_close - sbro_close), 2)
                if difference <= VERIFIED_TOLERANCE:
                    flag = "verified"
                elif difference <= SOURCE_VARIANCE_MAX:
                    flag = "source_variance"
                else:
                    flag = "source_conflict"
            elif cfbd_close is not None or sbro_close is not None:
                flag = "single_source"
            else:
                flag = "missing"

        opening_difference = None
        if cfbd_open is not None and sbro_open is not None:
            opening_difference = round(abs(cfbd_open - sbro_open), 2)

        counts[flag] += 1
        detail_rows.append({
            "game_id": game_id,
            "season": season,
            "home_team": cfbd["home_team"],
            "away_team": cfbd["away_team"],
            "date": cfbd_date,
            "cfbd_closing_spread": cfbd_close,
            "sbro_closing_spread": sbro_close,
            "closing_spread_difference": difference,
            "market_data_quality_flag": flag,
            # Opening-line fields — EXPOSED FOR VALIDATION ONLY. Not yet a
            # production field consumed by games_master.csv or any feature
            # script, per this session's explicit decision: validate first,
            # promote only after accuracy is demonstrated (see
            # validate_opening_lines.py and spec §11's opening-spread note).
            "cfbd_opening_spread": cfbd_open,
            "sbro_opening_spread": sbro_open,
            "opening_spread_difference": opening_difference,
            "opening_line_confidence": opening_confidence,
        })

    total_games = len(cfbd_lines)
    conflict_samples = [r for r in detail_rows if r["market_data_quality_flag"] == "source_conflict"][:8]

    # Name-set diagnostic: SBRO team names that don't correspond to any CFBD
    # team name at all (a real alias gap), vs. ones that exist on both sides
    # but never landed within the 1-day match window (likely a date/timing issue).
    cfbd_team_norms = {normalize_cfbd(cfbd["home_team"]) for cfbd in cfbd_lines.values()} | \
                       {normalize_cfbd(cfbd["away_team"]) for cfbd in cfbd_lines.values()}
    sbro_team_norms = set(sbro_by_team.keys())
    name_gap = sorted(sbro_team_norms - cfbd_team_norms)[:30]

    # Match-rate denominator fix (v1.4.2): SBRO's own site documentation
    # states it began including ALL FCS games starting in 2019, not just
    # FBS ones. Dividing by the raw SBRO row count understates the real
    # match rate for 2019+, since many of those rows are FCS-vs-FCS games
    # that were never going to match anything in our FBS-only CFBD set.
    # Restrict the denominator to SBRO rows where at least one team is
    # recognizable as FBS (exists in cfbd_team_norms) instead.
    relevant_sbro_rows = [r for r in sbro_rows
                           if r["home_norm"] in cfbd_team_norms or r["away_norm"] in cfbd_team_norms]
    sbro_match_rate = (matched_sbro / len(relevant_sbro_rows) * 100) if relevant_sbro_rows else None

    if away_unverified_matches > 0:
        print(f"  ** NOTE season {season}: {away_unverified_matches} of {matched_sbro} SBRO matches "
              f"had a home+date match but the away team could not be cross-verified (likely an "
              f"alias-table gap on the away side, not necessarily a wrong match) — see away-team "
              f"verification fix in reconcile_season(). **")

    return counts, total_games, sbro_match_rate, detail_rows, conflict_samples, unmatched_cfbd_teams, name_gap


def write_detail_csv(detail_rows, season):
    if not detail_rows:
        return
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    path = os.path.join(PROCESSED_DIR, f"lines_reconciled_{season}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(detail_rows[0].keys()))
        writer.writeheader()
        writer.writerows(detail_rows)


def main():
    parser = argparse.ArgumentParser(description="Reconcile SBRO + CFBD lines into market_data_quality_flag.")
    parser.add_argument("--seasons", default=f"{ALL_SEASONS_MIN}-{ALL_SEASONS_MAX}")
    args = parser.parse_args()

    if "-" in args.seasons:
        start, end = args.seasons.split("-")
        seasons = list(range(int(start), int(end) + 1))
    else:
        seasons = [int(x) for x in args.seasons.split(",")]

    os.makedirs(VALIDATION_DIR, exist_ok=True)
    summary_path = os.path.join(VALIDATION_DIR, "market_quality_summary.csv")

    summary_rows = []
    all_conflict_samples = []
    all_unmatched_teams = {}
    all_name_gaps = set()
    print(f"{'Season':<8}{'Games':<8}{'Verified':<10}{'Variance':<10}{'Conflict':<10}{'Single':<8}{'Missing':<9}{'SBRO match %':<14}")
    for season in seasons:
        counts, total, match_rate, detail_rows, conflict_samples, unmatched_cfbd_teams, name_gap = reconcile_season(season)
        write_detail_csv(detail_rows, season)
        all_conflict_samples.extend(conflict_samples)
        for norm, orig in unmatched_cfbd_teams.items():
            all_unmatched_teams.setdefault(norm, orig)
        all_name_gaps.update(name_gap)
        summary_rows.append({
            "season": season,
            "total_games": total,
            "verified": counts["verified"],
            "source_variance": counts["source_variance"],
            "source_conflict": counts["source_conflict"],
            "single_source": counts["single_source"],
            "missing": counts["missing"],
        })
        match_str = f"{match_rate:.1f}%" if match_rate is not None else "n/a (no SBRO)"
        print(f"{season:<8}{total:<8}{counts['verified']:<10}{counts['source_variance']:<10}"
              f"{counts['source_conflict']:<10}{counts['single_source']:<8}{counts['missing']:<9}{match_str:<14}")
        if match_rate is not None and match_rate < 95.0:
            print(f"  ** WARNING: {season} SBRO match rate is {match_rate:.1f}%, below the 95% "
                  f"reliability threshold. Expand SBRO_TO_CFBD_ALIASES before trusting this "
                  f"season's Verified/Source conflict split. **")
        if total > 0 and counts["source_conflict"] / total > 0.10:
            print(f"  ** GATE 2 STOP: {season} source_conflict rate is "
                  f"{counts['source_conflict']/total*100:.1f}%, above the 10% threshold. "
                  f"Do not proceed to games_master.csv for this season until investigated. **")

    if all_unmatched_teams or all_name_gaps:
        unmatched_path = os.path.join(VALIDATION_DIR, "unmatched_teams_diagnostic.csv")
        with open(unmatched_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["category", "normalized_name", "example_original_name"])
            for norm, orig in sorted(all_unmatched_teams.items()):
                writer.writerow(["cfbd_team_never_matched", norm, orig])
            for norm in sorted(all_name_gaps):
                writer.writerow(["sbro_name_not_in_cfbd_at_all", norm, ""])
        print(f"\nWrote {unmatched_path}")
        print("  'cfbd_team_never_matched' = this CFBD team's games never found an SBRO match at all "
              "(check date/timing or a completely different name spelling)")
        print("  'sbro_name_not_in_cfbd_at_all' = SBRO uses this exact name and it doesn't exist as any "
              "CFBD team name — these are the real alias-table gaps to fix first")


    if all_conflict_samples:
        diag_path = os.path.join(VALIDATION_DIR, "conflict_diagnostics_sample.csv")
        with open(diag_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_conflict_samples[0].keys()))
            writer.writeheader()
            writer.writerows(all_conflict_samples)
        print(f"\nWrote {len(all_conflict_samples)} example conflicting games to {diag_path}")
        print("Review this file to diagnose whether conflicts are real book disagreement or a parsing bug.")

    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["season", "total_games", "verified", "source_variance",
                                                "source_conflict", "single_source", "missing"])
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"\nWrote {summary_path}")
    print(f"Wrote per-game detail to {PROCESSED_DIR}/lines_reconciled_<season>.csv")
    print("\nNext: review any match-rate or conflict-rate warnings above before building games_master.csv.")


if __name__ == "__main__":
    main()
