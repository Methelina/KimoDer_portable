# KimoDer v2.6.0 - Kimodo+Cascadeur Portable Runtime Launcher
# Default action (no args): launches DearPyGui control panel.
# USAGE:
#   .\Run_KimoDer.ps1                                = launch GUI
#   .\Run_KimoDer.ps1 -StartBackend llama             = start backend (LLAMA NF4)
#   .\Run_KimoDer.ps1 -StartBackend fallback          = start backend (LLAMA OFF)
#   .\Run_KimoDer.ps1 -StopBackend                    = stop backend
#   .\Run_KimoDer.ps1 -CheckBackend                   = health-check & print JSON
#   .\Run_KimoDer.ps1 -StartDemo                      = launch web demo
#   .\Run_KimoDer.ps1 -InstallCascadeurCommand -CascadeurRoot "path"

param(
    [ValidateSet("llama","fallback")]
    [string]$StartBackend = "",
    [switch]$StopBackend,
    [switch]$CheckBackend,
    [switch]$StartDemo,
    [string]$CascadeurRoot = "",
    [switch]$InstallCascadeurCommand,
    [switch]$Gui
)
$Script:CLI_MODE = ($StartBackend -or $StopBackend -or $CheckBackend -or $StartDemo -or $InstallCascadeurCommand)

$ScriptPath = $PSScriptRoot
if (-not $ScriptPath) { $ScriptPath = "." }
Set-Location $ScriptPath
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "KimoDer - Kimodo+Cascadeur Portable"

$EnvDir = Join-Path $ScriptPath "kimodo_env"
$PythonExe = Join-Path $EnvDir "Scripts\python.exe"
$PythonwExe = Join-Path $EnvDir "Scripts\pythonw.exe"

function Write-Status {
    param([string]$Message, [string]$Type = "INFO")
    $color = switch ($Type) {
        "INFO"    { "Cyan" }
        "WARN"    { "Yellow" }
        "ERROR"   { "Red" }
        "SUCCESS" { "Green" }
        default   { "White" }
    }
    Write-Host "[$Type] $Message" -ForegroundColor $color
}

function Test-IsInstalled {
    return (Test-Path $PythonExe)
}

function Invoke-BackendCtl {
    param([string[]]$CtlArgs)
    & $PythonExe (Join-Path $ScriptPath "scripts\backend_ctl.py") @CtlArgs
    return $LASTEXITCODE
}

# ---- CLI dispatch (non-interactive mode) ----
if ($Script:CLI_MODE) {
    $exitCode = 0
    try {
        if (-not (Test-IsInstalled)) { throw "Environment not installed. Run Install_KimoDer-UV.ps1 -Install first." }
        if ($StartBackend) {
            Write-Status "CLI: starting backend ($StartBackend)..." "INFO"
            $rc = Invoke-BackendCtl @("start", "--profile", $StartBackend)
            if ($rc -ne 0) { $exitCode = $rc }
        }
        if ($StopBackend) {
            Write-Status "CLI: stopping backend..." "INFO"
            $rc = Invoke-BackendCtl @("stop")
            if ($rc -ne 0) { $exitCode = $rc }
        }
        if ($CheckBackend) {
            $rc = Invoke-BackendCtl @("health", "--json")
            if ($rc -ne 0) { $exitCode = $rc }
        }
        if ($StartDemo) {
            Write-Status "CLI: starting demo..." "INFO"
            $kimodoDir = Join-Path $ScriptPath "kimodo"
            & (Join-Path $EnvDir "Scripts\Activate.ps1")
            Push-Location $kimodoDir
            python -m kimodo.demo
            Pop-Location
        }
        if ($InstallCascadeurCommand) {
            $cmdArgs = @{}
            if ($CascadeurRoot) { $cmdArgs.CascadeurRoot = $CascadeurRoot }
            & (Join-Path $ScriptPath "install_cascadeur_command.ps1") @cmdArgs
        }
    } catch {
        Write-Status "CLI ERROR: $_" "ERROR"
        $exitCode = 1
    }
    exit $exitCode
}

# ---- Default: launch GUI ----
if (-not (Test-IsInstalled)) {
    Write-Status "Environment not installed. Run Install_KimoDer-UV.ps1 -Install first." "ERROR"
    Read-Host "Press Enter to exit"
    exit 1
}

$GuiScript = Join-Path $ScriptPath "scripts\kimoder_gui.py"
if (-not (Test-Path $GuiScript)) {
    Write-Status "GUI script not found: $GuiScript" "ERROR"
    exit 1
}

$Launcher = $PythonwExe
if (-not (Test-Path $Launcher)) { $Launcher = $PythonExe }

& $Launcher $GuiScript
exit $LASTEXITCODE
