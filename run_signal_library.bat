@echo off
title CFB Edge Lab - Build Signal Library
color 0A
echo ============================================================
echo   Evaluating all 4 frozen signals against training data
echo   (2014-2021 ONLY - hardcoded, not a parameter)
echo ============================================================
python src\model\signal_library.py
echo.
echo ============================================================
echo   Done. Two files written:
echo   data\processed\signal_evaluation_summary.csv (per-signal stats)
echo   data\processed\signal_library.csv (per-game qualifying flags)
echo   Review the survives_6_2 column carefully - this is the real
echo   payoff of everything frozen in the spec.
echo ============================================================
pause
