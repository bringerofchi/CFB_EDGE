@echo off
title CFB Edge Lab - Personnel Features
color 0A
echo Building personnel features: QB experience, coaching continuity, roster turnover
python src\features\personnel_features.py --seasons 2014-2021
echo.
echo Done. Output: data\processed\personnel_features.csv
pause
