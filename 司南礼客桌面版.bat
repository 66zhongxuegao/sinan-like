@echo off
REM ============================================================================
REM TripCraft / Lvyuan DESKTOP entry (double-click this file once).
REM   NORMAL mode: random tourists + real model path (default for everyone).
REM   It calls the ONE shared launcher at a FIXED ASCII path:
REM       scripts\desktop_launch.ps1 -Mode Normal
REM   That launcher safely reuses-or-starts backend 18020 / frontend 5190 with
REM   .dsh-run\normal\preview.sqlite and its own desktop session, then opens the
REM   real Electron window. It never resets data, never restarts DSH, never kills
REM   services that are already running, and never touches the demo instance.
REM   Internal demo mode is started by staff via the Chinese-named demo launcher
REM   (which calls the same script with -Mode Demo).
REM   NOTE: this file is intentionally ASCII-only: cmd.exe decodes .bat files with
REM   the OEM code page, so non-ASCII text here would corrupt parsing.
REM ============================================================================
setlocal
set "LAUNCHER=%~dp0scripts\desktop_launch.ps1"
if not exist "%LAUNCHER%" (
  echo [TripCraft] Launcher not found: %LAUNCHER%
  echo [TripCraft] Cannot open the desktop app.
  echo.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%" -Mode Normal
if errorlevel 1 (
  echo.
  echo [TripCraft] Desktop start failed - see the message above.
  echo [TripCraft] Fix the reported problem and double-click this file again.
  echo.
  pause
)
endlocal
