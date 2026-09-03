@echo off
title CFB Edge Lab - Finalize Trap Game Threshold
color 0A
echo ============================================================
echo   Computing the real gap distribution for Candidate B
echo   (Trap Game/Schedule-Context Effect) - training data only
echo ============================================================
python src\model\finalize_trapgame_threshold.py
echo.
echo ============================================================
echo   Done. Paste console output back to Claude for review
echo   before this threshold gets frozen.
echo ============================================================
pause
