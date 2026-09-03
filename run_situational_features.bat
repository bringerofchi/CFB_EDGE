@echo off
title CFB Edge Lab - Situational Features
color 0A

echo ============================================================
echo   Building travel distance, rest days, bye weeks, timezone
echo   changes - training period (2014-2021)
echo ============================================================
python src\features\situational_features.py --seasons 2014-2021

echo.
echo ============================================================
echo   Done. Output: data\processed\situational_factors.csv
echo   Spot-check: find a team's long road trip (e.g. a Hawaii
echo   game) and confirm travel_km is large; confirm home games
echo   show ~0.
echo ============================================================
pause
