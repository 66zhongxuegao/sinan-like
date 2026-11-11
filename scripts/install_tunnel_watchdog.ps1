[CmdletBinding()]
param(
    [int]$IntervalMinutes = 20
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$watchdog = Join-Path $PSScriptRoot "tunnel_watchdog.ps1"
if (-not (Test-Path -LiteralPath $watchdog)) { throw "Watchdog script not found: $watchdog" }

$IntervalMinutes = [Math]::Max(1, $IntervalMinutes)
$taskName = "TripCraft Demo Tunnel Watchdog"
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -ProjectRoot "{1}"' -f $watchdog, $root

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $root
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$repeatTrigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 45) `

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger @($logonTrigger, $repeatTrigger) `
    -Principal $principal `
    -Settings $settings `
    -Description "Check the TripCraft temporary demo URL every $IntervalMinutes minutes and recreate it when unavailable." `
    -Force | Out-Null

# Remove the old startup-folder launcher so it cannot create a second long-running watchdog.
$oldStartup = Join-Path ([Environment]::GetFolderPath("Startup")) "TripCraft Demo Tunnel Watchdog.vbs"
if (Test-Path -LiteralPath $oldStartup) {
    Remove-Item -LiteralPath $oldStartup -Force
    Write-Output "Removed obsolete startup entry: $oldStartup"
}

# Stop any old loop-mode watchdog before handing control to Task Scheduler.
$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine -match "[\\/]tunnel_watchdog\.ps1" -and $_.CommandLine -match "-Loop"
}
foreach ($process in @($existing)) {
    try {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        Write-Output "Stopped old long-running watchdog pid=$($process.ProcessId)"
    } catch {}
}

Start-ScheduledTask -TaskName $taskName
Write-Output "Installed scheduled task: $taskName"
Write-Output "Runs at user logon and every $IntervalMinutes minutes; first check started now."

