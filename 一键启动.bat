@echo off
REM TripCraft launcher. No process killing here: only scripts\start.ps1 does that,
REM and it only stops PIDs recorded in .runtime\pids.json by a previous start.
cd /d "%~dp0"
where pwsh >nul 2>nul
if %errorlevel%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "scripts\start.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start.ps1"
)
