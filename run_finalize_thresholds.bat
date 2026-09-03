@echo off
title CFB Edge Lab - Finalize Signal 3/4 Thresholds
color 0A
echo Computing real feature distributions (training data only, no outcomes touched)
python src\data_collection\finalize_signal_thresholds.py --seasons 2014-2021
echo.
echo Review the proposed thresholds above and decide - paste output back to Claude.
pause
