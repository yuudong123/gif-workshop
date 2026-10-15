@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto failure
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failure
echo Ready. Open the launch file to start.
pause
exit /b 0
:failure
echo Setup failed. Check Python and your internet connection.
pause
exit /b 1
