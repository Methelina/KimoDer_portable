param(
    [int]$Port = 9552,
    [string]$HostAddr = "127.0.0.1"
)

$ScriptPath = $PSScriptRoot
if (-not $ScriptPath) { $ScriptPath = "." }
$RepoRoot = (Get-Item -Path $ScriptPath).Parent.FullName

. "$ScriptPath\backend_env.ps1"

$BackendPidFile = Join-Path $env:KIMODO_RUNTIME_DIR "cascadeur-kimodo-backend.pid"

try {
    $null = Invoke-RestMethod -Uri "http://${HostAddr}:${Port}/shutdown" -Method Post -Body "{}" -ContentType "application/json" -TimeoutSec 5
    Write-Host "[INFO] Shutdown request sent." -ForegroundColor Cyan
} catch {
    Write-Host "[INFO] Backend may already be stopped." -ForegroundColor DarkGray
}

if (Test-Path $BackendPidFile) {
    $pid = Get-Content $BackendPidFile -Raw
    if ($pid) {
        try {
            $proc = Get-Process -Id ([int]$pid) -ErrorAction Stop
            $proc.Kill()
            Write-Host "[INFO] Terminated backend process PID $pid." -ForegroundColor Cyan
        } catch {
            Write-Host "[INFO] Backend process already exited." -ForegroundColor DarkGray
        }
    }
    Remove-Item $BackendPidFile -Force -ErrorAction SilentlyContinue
}

Write-Host "[OK] Kimodo backend stopped." -ForegroundColor Green
Write-Output "STATUS: Kimodo backend stopped."
