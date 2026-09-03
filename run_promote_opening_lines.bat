@echo off
title CFB Edge Lab - Promote Opening Lines to Production
color 0A

echo ============================================================
echo   Rebuilding games_master.csv with validated SBRO opening
echo   spread promoted to production (2014-2022), CFBD as
echo   fallback only (2023-2025)
echo ============================================================
python src\data_collection\build_games_master.py --seasons 2014-2025

echo.
echo ============================================================
echo   Done. games_master.csv now has:
echo   opening_spread_source, line_movement_source columns
echo   showing exactly where each value came from.
echo   Signal 3 (Market Movement Confirmation) is now buildable
echo   with real training-period data, not just 2021.
echo ============================================================
pause
