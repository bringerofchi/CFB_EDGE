@echo off
title CFB Edge Lab - Market Features
color 0A

echo ============================================================
echo   Building market features: reputation gap, line movement
echo   Training period (2014-2021)
echo ============================================================
python src\features\market_features.py --seasons 2014-2021

echo.
echo ============================================================
echo   Done. Output: data\processed\market_features.csv
echo   NOTE: "model vs spread difference" is NOT included - it
echo   needs a design decision first (see script's printed note).
echo ============================================================
pause
