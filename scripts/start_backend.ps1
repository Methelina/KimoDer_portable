param(
    [string]$PreloadDataset = "RP",
    [ValidateSet("llama","fallback")]
    [string]$TextEncoderProfile = "llama",
    [int]$WatchWindowsPid = 0,
    [int]$Port = 9552,
    [string]$HostAddr = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

$ScriptPath = $PSScriptRoot
if (-not $ScriptPath) { $ScriptPath = "." }
$RepoRoot = (Get-Item -Path $ScriptPath).Parent.FullName

$EnvDir = Join-Path $RepoRoot "kimodo_env"
$PythonExe = Join-Path $EnvDir "Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = Join-Path $EnvDir "python.exe"
}
if (-not (Test-Path $PythonExe)) {
    Write-Host "[ERROR] Python not found in $EnvDir. Run the installer first." -ForegroundColor Red
    exit 1
}

. "$ScriptPath\backend_env.ps1"

if ($TextEncoderProfile -eq "fallback") {
    $env:TEXT_ENCODER = "hash"
} else {
    Remove-Item Env:TEXT_ENCODER -ErrorAction SilentlyContinue
}

function Write-StatusLine {
    param([string]$Prefix, [string]$Message)
    $line = "${Prefix}: ${Message}"
    Write-Host $line -ForegroundColor Cyan
    Write-Output $line
}

$BackendScript = Join-Path $ScriptPath "cascadeur_backend_service.py"
if (-not (Test-Path $BackendScript)) {
    Write-Host "[ERROR] Backend script not found: $BackendScript" -ForegroundColor Red
    exit 1
}

$BackendLog = Join-Path $env:KIMODO_RUNTIME_DIR "cascadeur-kimodo-backend.log"
$BackendPidFile = Join-Path $env:KIMODO_RUNTIME_DIR "cascadeur-kimodo-backend.pid"

$existingPid = $null
if (Test-Path $BackendPidFile) {
    $existingPid = Get-Content $BackendPidFile -Raw
    if ($existingPid) {
        try {
            $proc = Get-Process -Id ([int]$existingPid) -ErrorAction Stop
            Write-Host "[INFO] Kimodo backend already running (PID $existingPid)." -ForegroundColor Cyan
            exit 0
        } catch {
            Remove-Item $BackendPidFile -Force
        }
    }
}

$ArgsList = @(
    "--host", $HostAddr,
    "--port", $Port,
    "--preload-dataset", $PreloadDataset,
    "--text-encoder-profile", $TextEncoderProfile
)
if ($TextEncoderProfile -eq "fallback") {
    $ArgsList += "--text-pid-file"
    $ArgsList += "none"
}
if ($WatchWindowsPid -gt 0) {
    $ArgsList += "--watch-windows-pid"
    $ArgsList += $WatchWindowsPid
}

Write-StatusLine "STATUS" "Starting Kimodo backend..."
Write-Host "  Python: $PythonExe" -ForegroundColor DarkGray
Write-Host "  Backend: $BackendScript" -ForegroundColor DarkGray
Write-Host "  Profile: $TextEncoderProfile" -ForegroundColor DarkGray
Write-Host "  Dataset: $PreloadDataset" -ForegroundColor DarkGray
Write-Host "  Log: $BackendLog" -ForegroundColor DarkGray

$logDir = Split-Path $BackendLog -Parent
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }

$ProcessInfo = New-Object System.Diagnostics.ProcessStartInfo
$ProcessInfo.FileName = $PythonExe
$ProcessInfo.Arguments = "`"$BackendScript`" $($ArgsList -join ' ')"
$ProcessInfo.UseShellExecute = $false
$ProcessInfo.RedirectStandardOutput = $false
$ProcessInfo.RedirectStandardError = $false
$ProcessInfo.CreateNoWindow = $true
$ProcessInfo.WorkingDirectory = $RepoRoot

$Process = New-Object System.Diagnostics.Process
$Process.StartInfo = $ProcessInfo

$Process.Start() | Out-Null

$Process.Id | Out-File -FilePath $BackendPidFile -NoNewline

Write-Host "[INFO] Backend PID: $($Process.Id), log: $BackendLog" -ForegroundColor Cyan

$deadline = (Get-Date).AddSeconds(600)
$ready = $false
while ((Get-Date) -lt $deadline) {
    if ($Process.HasExited) {
        Write-Host "[ERROR] Backend exited before ready. Check log: $BackendLog" -ForegroundColor Red
        if (Test-Path $BackendLog) { Get-Content $BackendLog -Tail 20 | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray } }
        exit 1
    }
    try {
        $response = Invoke-RestMethod -Uri "http://${HostAddr}:${Port}/health" -Method Get -TimeoutSec 3
        if ($response.ok) {
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 250
    }
}

if (-not $ready) {
    Write-Host "[ERROR] Backend did not become ready within timeout." -ForegroundColor Red
    $Process.Kill()
    exit 1
}

Write-StatusLine "STATUS" "Kimodo backend ready at http://${HostAddr}:${Port}"
Write-Output "BACKEND_URL: http://${HostAddr}:${Port}/health"
exit 0
