@echo off
title CFB Edge Lab - Rivalry Coverage Audit
color 0A
echo ============================================================
echo   Auditing rivalry coverage against your ACTUAL FBS team
echo   universe (from your real pulled data, not assumptions)
echo ============================================================
cd src\model
python audit_rivalry_coverage.py --raw-dir ..\..\data\raw
cd ..\..
echo.
echo ============================================================
echo   Done. Check src\model\uncovered_teams.csv
echo   Paste the console output back to Claude.
echo ============================================================
pause
