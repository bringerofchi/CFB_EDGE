@echo off
title CFB Edge Lab - Coaches and Venues Pull
color 0A

echo ============================================================
echo   Pulling coaches and venues data (one-time, cheap - 2 calls)
echo ============================================================

if "%CFBD_API_KEY%"=="" (
    set /p CFBD_API_KEY="Paste your CFBD API key and press Enter: "
)

python src\data_collection\cfbd_pull.py --seasons 2014 --endpoints coaches,venues

echo.
echo ============================================================
echo   Done. Output:
echo   data\raw\coaches\coaches.json
echo   data\raw\venues\venues.json
echo ============================================================
pause
