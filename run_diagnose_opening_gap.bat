@echo off
title CFB Edge Lab - Diagnose Opening Spread Gap
color 0A

echo ============================================================
echo   Checking whether the 2014-2020 opening-spread gap is a
echo   real CFBD data limitation or a bug in extraction code
echo ============================================================
python src\data_collection\diagnose_opening_spread_gap.py --seasons 2014-2021

echo.
echo ============================================================
echo   Done. Read the output for each season - especially any
echo   "CONFIRMED" lines and the sample game JSON shown.
echo   Paste the full output back to Claude.
echo ============================================================
pause
