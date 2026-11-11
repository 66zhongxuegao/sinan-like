[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$Repo = "66zhongxuegao/tripcraft_lvyuan",
    [int]$FrontendPort = 15191,
    [int]$BackendPort = 18930,
    [int]$IntervalMinutes = 20,
    [switch]$Loop,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$script:LogDir = Join-Path $ProjectRoot "logs"
$script:LogFile = Join-Path $script:LogDir "tunnel-watchdog.log"
$script:StateFile = Join-Path $script:LogDir "demo_url.txt"
$script:StatusFile = Join-Path $script:LogDir "tunnel-watchdog-status.json"
New-Item -ItemType Directory -Force -Path $script:LogDir | Out-Null

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8
}

function Test-Http([string]$Url, [int]$TimeoutSec = 20) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $TimeoutSec
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400)
    } catch { return $false }
}

function Invoke-WithRetry {
    param([Parameter(Mandatory = $true)][scriptblock]$Action, [int]$Attempts = 5, [int]$DelaySeconds = 4)
    $last = $null
    for ($i = 1; $i -le $Attempts; $i++) {
        try { return & $Action } catch {
            $last = $_
            Write-Log ("retry {0}/{1}: {2}" -f $i, $Attempts, $_.Exception.Message)
            if ($i -lt $Attempts) { Start-Sleep -Seconds $DelaySeconds }
        }
    }
    throw $last
}

function Get-GitHubHeaders {
    $env:GIT_TERMINAL_PROMPT = "0"
    $env:GCM_INTERACTIVE = "never"
    $cred = "protocol=https`nhost=github.com`n`n" | git credential fill 2>$null
    $passwordLine = ($cred -split "`n" | Where-Object { $_ -like "password=*" } | Select-Object -First 1)
    if (-not $passwordLine) { throw "GitHub credential not found in Git Credential Manager" }
    $token = $passwordLine.Substring(9)
    return @{ Authorization = "Bearer $token"; Accept = "application/vnd.github+json"; "User-Agent" = "TripCraft-Tunnel-Watchdog" }
}

function Get-RemoteReadme {
    param([hashtable]$Headers)
    $api = "https://api.github.com/repos/$Repo/contents/README.md"
    return Invoke-WithRetry {
        $r = Invoke-RestMethod -Uri "${api}?ref=main" -Headers $Headers -TimeoutSec 45
        $text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(($r.content -replace "\s", "")))
        return @{ Text = $text; Sha = $r.sha; Api = $api }
    }
}

function Get-DemoUrlFromReadme([string]$Text) {
    if ($Text -match "(?s)<!-- LIVE-DEMO:START -->.*?(https://[a-z0-9-]+\.trycloudflare\.com).*?<!-- LIVE-DEMO:END -->") {
        return $Matches[1]
    }
    return ""
}

function Update-RemoteReadme([string]$Url) {
    $headers = Get-GitHubHeaders
    $remote = Get-RemoteReadme -Headers $headers
    if ($remote.Text.Contains($Url)) { Write-Log "README already contains $Url"; return $true }
    $start = $remote.Text.IndexOf("<!-- LIVE-DEMO:START -->")
    $end = $remote.Text.IndexOf("<!-- LIVE-DEMO:END -->", [Math]::Max(0, $start))
    if ($start -lt 0 -or $end -lt 0) { throw "README LIVE-DEMO block not found" }
    $before = $remote.Text.Substring(0, $start)
    $middle = $remote.Text.Substring($start, $end - $start)
    $after = $remote.Text.Substring($end)
    $updatedMiddle = [regex]::Replace($middle, "https://[a-z0-9-]+\.trycloudflare\.com", $Url)
    if ($updatedMiddle -eq $middle) { throw "README LIVE-DEMO block has no trycloudflare URL to replace" }
    $updated = $before + $updatedMiddle + $after
    $body = @{ message = "docs: refresh temporary live demo link"; content = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($updated)); sha = $remote.Sha; branch = "main" } | ConvertTo-Json
    Invoke-WithRetry {
        $result = Invoke-RestMethod -Method Put -Uri $remote.Api -Headers $headers -ContentType "application/json; charset=utf-8" -Body $body -TimeoutSec 60
        Write-Log "README updated: commit=$($result.commit.sha)"
        return $true
    } | Out-Null
    return $true
}

function Get-CloudflaredPath {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    foreach ($p in @("C:\Program Files (x86)\cloudflared\cloudflared.exe", "C:\Program Files\cloudflared\cloudflared.exe")) {
        if (Test-Path -LiteralPath $p) { return $p }
    }
    throw "cloudflared.exe not found"
}

function Stop-DemoTunnel {
    $pattern = "127\.0\.0\.1:$FrontendPort|localhost:$FrontendPort"
    $procs = Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern }
    foreach ($p in @($procs)) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Write-Log "stopped stale cloudflared pid=$($p.ProcessId)" }
        catch { Write-Log "failed to stop cloudflared pid=$($p.ProcessId): $($_.Exception.Message)" }
    }
    Start-Sleep -Seconds 2
}

function Start-DemoTunnel {
    $cloudflared = Get-CloudflaredPath
    $maxAttempts = 5
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        $out = Join-Path $script:LogDir "cloudflared-watchdog.out.log"
        $err = Join-Path $script:LogDir "cloudflared-watchdog.err.log"
        Remove-Item -LiteralPath $out, $err -ErrorAction SilentlyContinue
        $args = @("tunnel", "--url", "http://127.0.0.1:$FrontendPort", "--protocol", "http2", "--no-autoupdate")
        $p = Start-Process -FilePath $cloudflared -ArgumentList $args -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
        Write-Log "started cloudflared pid=$($p.Id) attempt=$attempt/$maxAttempts"

        $url = ""
        for ($i = 0; $i -lt 50; $i++) {
            Start-Sleep -Seconds 1
            if (Test-Path -LiteralPath $err) {
                try {
                    $m = Select-String -Path $err -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
                    if ($m) { $url = $m.Matches[0].Value; break }
                    if (Select-String -Path $err -Pattern "429|Tunnelstore request failed" -Quiet) { break }
                } catch {}
            }
            try { if ($p.HasExited) { break } } catch {}
        }

        if (-not $url) {
            $rateLimited = $false
            try { $rateLimited = Select-String -Path $err -Pattern "429|Tunnelstore request failed" -Quiet } catch {}
            if ($rateLimited) { Write-Log "cloudflare quick tunnel rate-limited (429) on attempt $attempt" }
            else { Write-Log "cloudflared did not report a quick tunnel URL on attempt $attempt" }
            try { if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction Stop } } catch {}
            if ($attempt -lt $maxAttempts) {
                $delay = 30 * $attempt
                Write-Log "retrying tunnel creation in $delay seconds"
                Start-Sleep -Seconds $delay
                continue
            }
            throw "cloudflared could not create a quick tunnel after $maxAttempts attempts"
        }

        Write-Log "tunnel URL: $url"
        $registered = $false
        for ($i = 0; $i -lt 60; $i++) {
            if (Test-Path -LiteralPath $err) {
                try { if (Select-String -Path $err -Pattern "Registered tunnel connection" -Quiet) { $registered = $true; break } } catch {}
            }
            Start-Sleep -Seconds 1
        }
        if (-not $registered) {
            Write-Log "tunnel did not register on attempt $attempt"
            try { if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction Stop } } catch {}
            if ($attempt -lt $maxAttempts) { Start-Sleep -Seconds (30 * $attempt); continue }
            throw "cloudflared did not register the tunnel connection"
        }

        for ($i = 0; $i -lt 20; $i++) {
            if (Test-Http $url 20) { return $url }
            Start-Sleep -Seconds 3
        }
        Write-Log "tunnel URL is not publicly reachable on attempt $attempt"
        try { if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction Stop } } catch {}
        if ($attempt -lt $maxAttempts) { Start-Sleep -Seconds (30 * $attempt); continue }
    }
    throw "tunnel URL is not publicly reachable after $maxAttempts attempts"
}

function Ensure-LocalServices {
    $front = "http://127.0.0.1:$FrontendPort/"
    $back = "http://127.0.0.1:$BackendPort/"
    if ((Test-Http $front 8) -and (Test-Http $back 8)) { return $true }
    Write-Log "local services are down; starting demo instance"
    $launcher = Join-Path $ProjectRoot "scripts\desktop_launch.ps1"
    if (-not (Test-Path -LiteralPath $launcher)) { throw "desktop_launch.ps1 not found: $launcher" }
    $out = Join-Path $script:LogDir "watchdog-launch.out.log"
    $err = Join-Path $script:LogDir "watchdog-launch.err.log"
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcher, "-Mode", "Demo", "-WebOnly") -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err | Out-Null
    for ($i = 0; $i -lt 45; $i++) {
        Start-Sleep -Seconds 2
        if ((Test-Http $front 5) -and (Test-Http $back 5)) { Write-Log "local services are ready"; return $true }
    }
    throw "local services did not become ready"
}

function Invoke-OneCheck {
    param([switch]$ForceRun)
    $url = ""
    $action = "none"
    $healthy = $false

    Ensure-LocalServices | Out-Null

    if (-not $ForceRun -and (Test-Path -LiteralPath $script:StateFile)) {
        $url = (Get-Content -LiteralPath $script:StateFile -Raw -Encoding UTF8).Trim()
    }
    if (-not $url) {
        $headers = Get-GitHubHeaders
        $remote = Get-RemoteReadme -Headers $headers
        $url = Get-DemoUrlFromReadme $remote.Text
    }

    if (-not $ForceRun -and $url -and (Test-Http $url 20)) {
        $healthy = $true
        $action = "none"
        Write-Log "link healthy: $url"
    } else {
        if ($ForceRun) { $action = "forced-recreate" } else { $action = "recreate" }
        Write-Log "link unavailable; recreating tunnel (was: $url)"
        Stop-DemoTunnel
        $url = Start-DemoTunnel
        Update-RemoteReadme $url | Out-Null
        Set-Content -LiteralPath $script:StateFile -Value $url -Encoding UTF8
        $healthy = $true
        Write-Log "link repaired: $url"
    }

    $status = [ordered]@{
        checked_at = (Get-Date).ToString("o")
        url = $url
        healthy = $healthy
        action = $action
        pid = $PID
    }
    $status | ConvertTo-Json | Set-Content -LiteralPath $script:StatusFile -Encoding UTF8
    return $status
}

$mutex = $null
try {
    $mutex = New-Object System.Threading.Mutex($false, "Local\TripCraftDemoTunnelWatchdog")
    if (-not $mutex.WaitOne(0)) {
        Write-Log "another watchdog instance is already running"
        exit 0
    }

    $forceThisRun = [bool]$Force
    do {
        try {
            $status = Invoke-OneCheck -ForceRun:$forceThisRun
        } catch {
            $message = $_.Exception.Message
            Write-Log "ERROR: $message"
            $status = [ordered]@{
                checked_at = (Get-Date).ToString("o")
                url = ""
                healthy = $false
                action = "error"
                error = $message
                pid = $PID
            }
            $status | ConvertTo-Json | Set-Content -LiteralPath $script:StatusFile -Encoding UTF8
        }

        $forceThisRun = $false
        if (-not $Loop) {
            if ($status.healthy) { exit 0 }
            exit 1
        }
        $sleepMinutes = [Math]::Max(1, $IntervalMinutes)
        Write-Log "next check in $sleepMinutes minutes"
        Start-Sleep -Seconds ($sleepMinutes * 60)
    } while ($true)
} finally {
    if ($mutex) { try { $mutex.ReleaseMutex() } catch {}; $mutex.Dispose() }
}
