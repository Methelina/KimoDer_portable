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
$PythonExe = Join-Path $RepoRoot "kimodo_env\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Host "[ERROR] Python not found in $RepoRoot\kimodo_env. Run the installer first." -ForegroundColor Red
    exit 1
}

$CtlArgs = @("start", "--profile", $TextEncoderProfile, "--preload-dataset", $PreloadDataset, "--port", $Port)
if ($WatchWindowsPid -gt 0) { $CtlArgs += @("--watch-pid", $WatchWindowsPid) }

& $PythonExe (Join-Path $ScriptPath "backend_ctl.py") @CtlArgs
exit $LASTEXITCODE
