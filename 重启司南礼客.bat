@echo off
setlocal
set "LAUNCHER=%~dp0scripts\desktop_launch.ps1"
if not exist "%LAUNCHER%" (
  echo [TripCraft] Launcher not found: %LAUNCHER%
  pause
  exit /b 1
)
echo [TripCraft] Finish any active call before applying updates.
powershell -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%" -Mode Normal -RestartBackend
if errorlevel 1 (
  echo [TripCraft] Restart failed. See the message above.
  pause
  exit /b 1
)
endlocal
