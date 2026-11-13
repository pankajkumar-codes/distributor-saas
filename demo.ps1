<#
 .SYNOPSIS
  Runs the whole product on your own computer so you can try it. Needs only Docker Desktop.

 .DESCRIPTION
  .\demo.ps1            start the demo (about 5 minutes the first time) and show sign-up codes here
  .\demo.ps1 stop       stop it and forget everything it held
  .\demo.ps1 codes      show the sign-up codes again (Ctrl+C leaves the demo running)
  .\demo.ps1 status     list what the demo server made of your uploaded files
  .\demo.ps1 upload amazon demo\samples\demo-orders-good.csv    upload a file without the browser
  .\demo.ps1 tool <args>   other helper commands (see docs\LOCAL_DEMO.md)

  If Windows says scripts are disabled, start it like this instead:
      powershell -ExecutionPolicy Bypass -File .\demo.ps1
  Made-up data only. Nothing here touches AWS or real tax data. See docs\LOCAL_DEMO.md.
#>
param(
    [Parameter(Position = 0)][string]$Command = "start",
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rest
)

Set-Location -Path $PSScriptRoot
$Url = "http://localhost:5173"
$Compose = @("compose", "-f", "docker-compose.demo.yml")

function Say($text, $color = "White") { Write-Host $text -ForegroundColor $color }
function Stop-Here($what, $fix) {
    Write-Host ""
    Say "The demo could not start: $what" Red
    Say $fix Yellow
    Say "More help: docs\LOCAL_DEMO.md, section 'If it does not open'." Yellow
    exit 1
}
function Dc { & docker @Compose @args }

function Test-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Stop-Here "Docker is not installed." "Install Docker Desktop for Windows (https://www.docker.com/products/docker-desktop/), start it, then run this again."
    }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Stop-Here "Docker is installed but not running." "Open Docker Desktop and wait until it says 'Engine running' (the whale icon stops moving), then run this again."
    }
}

function Test-Port($port) {
    $busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return [bool]$busy
}

function Wait-Open {
    Say "Waiting for the web page to answer..." Gray
    for ($i = 0; $i -lt 90; $i++) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri "$Url/api/v1/health" -TimeoutSec 3
            if ($r.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Seconds 2
    }
    Stop-Here "The page did not answer within 3 minutes." "Run '.\demo.ps1 stop', then '.\demo.ps1' again. If it repeats, send us the output of: docker compose -f docker-compose.demo.yml logs api web"
}

switch ($Command.ToLower()) {
    "start" {
        Test-Docker
        Say "Starting the demo. The first time this downloads and builds things and can take 5 to 10 minutes." Cyan
        Dc down -v --remove-orphans *> $null   # every start is a clean one: sign-in lives in memory
        if (Test-Port 5173) {
            Stop-Here "Port 5173 is already used by another program on this computer." "Close the other program (often another 'npm run dev' or 'vite' window), or restart the computer, then run this again."
        }
        Dc up -d --build --wait api web codes
        if ($LASTEXITCODE -ne 0) {
            Stop-Here "Docker could not build or start the demo." "Look at the red lines above. Common causes: no internet while building, or Docker Desktop is out of disk space or memory. Then run '.\demo.ps1 stop' and try again."
        }
        Dc run --rm seed
        if ($LASTEXITCODE -ne 0) { Stop-Here "Setting up the demo business failed." "Run '.\demo.ps1 stop' and try again." }
        Wait-Open
        Write-Host ""
        Say "==================================================================" Green
        Say "  The demo is ready.  Open this in your browser:" Green
        Say ""
        Say "      $Url" White
        Say ""
        Say "  Ready-made account (a made-up business, Demo Traders):" Green
        Say "      email:     demo@example.com" White
        Say "      password:  seven lamps under a bridge" White
        Say ""
        Say "  Or sign up as yourself: the 6-digit code appears right here." Green
        Say "  Sample files to upload are in the folder:  demo\samples" Green
        Say "  Stop it with:  .\demo.ps1 stop      (Ctrl+C below only stops this code list)" Green
        Say "==================================================================" Green
        Write-Host ""
        Dc logs -f --no-log-prefix --tail 0 codes
    }
    "stop" { Test-Docker; Dc down -v --remove-orphans; Say "The demo is stopped and its data is gone." Green }
    "codes" { Test-Docker; Dc logs -f --no-log-prefix --tail 0 codes }
    "status" { Test-Docker; Dc run --rm tool status }
    "upload" { Test-Docker; $inside = $Rest | ForEach-Object { $_ -replace '\\', '/' }; Dc run --rm tool upload @inside }
    "tool" { Test-Docker; $inside = $Rest | ForEach-Object { $_ -replace '\\', '/' }; Dc run --rm tool @inside }
    default { Get-Help $PSCommandPath -Detailed }
}
