@echo off
cd /d "%~dp0"
if exist "dist\GIF-Workshop\GIF-Workshop.exe" (
    start "" "dist\GIF-Workshop\GIF-Workshop.exe"
    exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "app.py"
    exit /b
)
echo Run setup.cmd first.
pause
