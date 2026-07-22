param(
    [int]$Port = 9552,
    [string]$HostAddr = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$ScriptPath = $PSScriptRoot
if (-not $ScriptPath) { $ScriptPath = "." }
$RepoRoot = (Get-Item -Path $ScriptPath).Parent.FullName
$PythonExe = Join-Path $RepoRoot "kimodo_env\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Host "[ERROR] Python not found in $RepoRoot\kimodo_env." -ForegroundColor Red
    exit 1
}

& $PythonExe (Join-Path $ScriptPath "backend_ctl.py") stop --port $Port
exit $LASTEXITCODE
