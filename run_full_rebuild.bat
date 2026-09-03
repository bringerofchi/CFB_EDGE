@echo off
setlocal enabledelayedexpansion
title CFB Edge Lab - FULL REBUILD
color 0A

echo ============================================================
echo   CFB Edge Lab - Full Pipeline Rebuild
echo   This runs EVERYTHING from raw data through final signals.
echo   It will take a while (real API calls, real web scraping).
echo   You can walk away and check back periodically.
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python not found. Install it from python.org first,
    echo checking "Add Python to PATH" during install, then run this again.
    pause
    exit /b 1
)

echo Step 0: Installing dependencies...
python -m pip install -r requirements.txt --break-system-packages --quiet 2>nul
python -m pip install requests beautifulsoup4 lxml --break-system-packages --quiet

if "%CFBD_API_KEY%"=="" (
    echo.
    echo Need your CFBD API key - free at https://collegefootballdata.com/key
    set /p CFBD_API_KEY="Paste it here and press Enter: "
)

echo.
echo ============================================================
echo   Step 1 of 12: CFBD raw data pull (games, lines, ppa,
echo   advanced, roster, recruiting, coaches, venues)
echo   This uses your monthly API call budget - script tracks
echo   and stops safely if it gets close to the limit.
echo ============================================================
python src\data_collection\cfbd_pull.py --seasons 2014-2025 --endpoints games,lines,ppa,advanced,roster,recruiting,coaches,venues

echo.
echo ============================================================
echo   Step 2 of 12: SBRO closing lines (2014-2022, web scrape)
echo ============================================================
python src\data_collection\line_import.py --seasons 2014-2022

echo.
echo ============================================================
echo   Step 3 of 12: Line reconciliation
echo ============================================================
python src\data_collection\line_reconciliation.py --seasons 2014-2025

echo.
echo ============================================================
echo   Step 4 of 12: Game universe validation
echo ============================================================
python src\data_collection\game_universe_validation.py --seasons 2014-2025

echo.
echo ============================================================
echo   Step 5 of 12: Build games_master.csv
echo ============================================================
python src\data_collection\build_games_master.py --seasons 2014-2025

echo.
echo ============================================================
echo   Step 6 of 12: QB start history (real API calls, ~120,
echo   takes a few minutes - league-wide weekly pulls)
echo ============================================================
python src\data_collection\qb_start_history.py --seasons 2014-2021

echo.
echo ============================================================
echo   Step 7 of 12: Efficiency features
echo ============================================================
python src\features\efficiency_features.py --seasons 2014-2021

echo.
echo ============================================================
echo   Step 8 of 12: Situational features
echo ============================================================
python src\features\situational_features.py --seasons 2014-2021

echo.
echo ============================================================
echo   Step 9 of 12: Personnel features
echo ============================================================
python src\features\personnel_features.py --seasons 2014-2021

echo.
echo ============================================================
echo   Step 10 of 12: Market features
echo ============================================================
python src\features\market_features.py --seasons 2014-2021

echo.
echo ============================================================
echo   Step 11 of 12: Data quality report
echo   NOTE: this will show "DO NOT PROCEED - spot check not
echo   reviewed" - that's expected. See message at the end.
echo ============================================================
python src\data_collection\data_quality_report.py --seasons 2014-2025

echo.
echo ============================================================
echo   Step 12 of 12: Signal evaluation (all three libraries)
echo ============================================================
python src\model\signal_library.py
python src\model\signal_library_2a.py
python src\model\model_vs_spread_signal.py

echo.
echo ============================================================
echo   REBUILD COMPLETE.
echo.
echo   One manual step remains: the spot check (60 games, ATS
echo   result verification) needs your review before the data
echo   quality gate fully clears. Given this is a rebuild of
echo   data we already validated once before, tell Claude you've
echo   completed the rebuild and it can help you decide how much
echo   re-verification is actually needed this time.
echo.
echo   Paste the console output (or scroll up and copy key
echo   sections) back to Claude, especially any ERROR or WARNING
echo   lines, and the final signal evaluation results.
echo ============================================================
pause
