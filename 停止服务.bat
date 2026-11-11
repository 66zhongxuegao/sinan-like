@echo off
REM TripCraft stop entry. It delegates to scripts\stop.ps1, which stops ONLY the
REM PIDs recorded in .runtime\pids.json (verified by start time + executable path).
REM It never kills by command line pattern or by port owner.
cd /d "%~dp0"
where pwsh >nul 2>nul
if %errorlevel%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "scripts\stop.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\stop.ps1"
)
