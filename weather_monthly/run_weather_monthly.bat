@echo off
echo === Run Weather Monthly Script ===
set /p USERNAME=Enter username:
set /p PASSWORD=Enter password:
set /p YEAR=Enter year (e.g. 2025):
set /p MONTH=Enter month (e.g. 10):
set /p FILTER=Enter station filter (e.g. G1001):

echo Running command...
python weather_monthly.py --user %USERNAME% --pass %PASSWORD% --year %YEAR% --month %MONTH% --filter %FILTER% --outdir weather_data --csv --excel --debug

echo.
echo === Process Finished ===
pause
