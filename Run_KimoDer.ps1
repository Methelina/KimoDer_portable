# KimoDer v2.5.0 — Kimodo+Cascadeur Portable Runtime Launcher
# USAGE:
#   .\Run_KimoDer.ps1                              = interactive menu
#   .\Run_KimoDer.ps1 -StartBackend llama           = start backend (LLAMA NF4)
#   .\Run_KimoDer.ps1 -StartBackend fallback         = start backend (LLAMA OFF)
#   .\Run_KimoDer.ps1 -StopBackend                   = stop backend
#   .\Run_KimoDer.ps1 -CheckBackend                  = health-check & print JSON
#   .\Run_KimoDer.ps1 -StartDemo [-Offload]          = launch demo
#   .\Run_KimoDer.ps1 -InstallCascadeurCommand -CascadeurRoot "path"

param(
    [ValidateSet("llama","fallback")]
    [string]$StartBackend = "",
    [switch]$StopBackend,
    [switch]$CheckBackend,
    [switch]$StartDemo,
    [switch]$Offload,
    [string]$CascadeurRoot = "",
    [switch]$InstallCascadeurCommand,
    [switch]$Menu
)
$Script:CLI_MODE = ($StartBackend -or $StopBackend -or $CheckBackend -or $StartDemo -or $InstallCascadeurCommand)
if (-not $Script:CLI_MODE -and -not $Menu) { $Menu = $true }

$ScriptPath = $PSScriptRoot
if (-not $ScriptPath) { $ScriptPath = "." }
Set-Location $ScriptPath
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "KimoDer - Kimodo+Cascadeur Portable"

$EnvDir = Join-Path $ScriptPath "kimodo_env"
$PythonExe = Join-Path $EnvDir "Scripts\python.exe"

# ==========================================================
# PORTABILITY ISOLATION
# ==========================================================
$CacheDir = Join-Path $ScriptPath ".cache"
$HfCacheDir = Join-Path $CacheDir "huggingface"
$TmpDir = Join-Path $CacheDir "tmp"
@($CacheDir, $HfCacheDir, $TmpDir) | ForEach-Object {
    if (-not (Test-Path $_)) { New-Item -ItemType Directory -Force -Path $_ | Out-Null }
}
$env:HF_HOME = $HfCacheDir
$env:TMP = $TmpDir
$env:TEMP = $TmpDir
$env:HF_HUB_DOWNLOAD_TIMEOUT = "60"
$env:MKL_DYNAMIC = "TRUE"
$env:SAFETENSORS_FAST_GPU = "1"
$env:CUDA_MODULE_LOADING = "LAZY"
$env:NVIDIA_TF32_OVERRIDE = "1"
$env:PYTORCH_CUDA_ALLOC_CONF = "garbage_collection_threshold:0.8,expandable_segments:True,max_split_size_mb:128"

function Write-Status {
    param([string]$Message, [string]$Type = "INFO")
    $color = switch ($Type) {
        "INFO"   { "Cyan" }
        "WARN"   { "Yellow" }
        "ERROR"  { "Red" }
        "SUCCESS"{ "Green" }
        default  { "White" }
    }
    Write-Host "[$Type] $Message" -ForegroundColor $color
}

function Test-IsInstalled {
    return (Test-Path $PythonExe)
}

function Ensure-Patches {
    $KimodoDir = Join-Path $ScriptPath "kimodo"
    $ModelDir = Join-Path $ScriptPath "KIMODO-Meta3_llm2vec_NF4"
    $WrapperDest = Join-Path $KimodoDir "kimodo\model\llm2vec\llm2vec_wrapper.py"
    $WrapperTemplate = Join-Path $ScriptPath "_llm2vec_wrapper_template.py"

    if ((-not (Test-Path $WrapperTemplate)) -or (-not (Test-Path $WrapperDest)) -or (-not (Test-Path $ModelDir))) {
        return $false
    }
    $current = Get-Content $WrapperDest -Raw
    $correctPath = $ModelDir -replace "\\", "/"
    if ($current -match "self\.custom_dir\s*=\s*['""]([^'""]+)['""]") {
        if ($Matches[1] -eq $correctPath) { return $true }
    }
    $template = Get-Content $WrapperTemplate -Raw
    $newContent = $template -replace "__MODEL_DIR__", $correctPath
    $Utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($WrapperDest, $newContent, $Utf8NoBom)
    return $true
}

function Start-Demo {
    param([bool]$Offload = $false)
    if (-not (Test-IsInstalled)) {
        Write-Status "Environment not installed. Run Install_KimoDer-UV.ps1 first." "ERROR"
        return
    }
    Write-Status "Checking patches..." "INFO"
    if (-not (Ensure-Patches)) { Write-Status "Patch may not be applied." "WARN" }
    $activateScript = Join-Path $EnvDir "Scripts\Activate.ps1"
    $kimodoDir = Join-Path $ScriptPath "kimodo"
    . $activateScript
    Push-Location $kimodoDir
    python -m kimodo.demo $(if ($Offload) { "--offload" })
    Pop-Location
}

function Start-Backend {
    param([string]$Profile = "llama")
    if (-not (Test-IsInstalled)) {
        Write-Status "Environment not installed. Run Install_KimoDer-UV.ps1 first." "ERROR"
        return
    }
    $BackendScript = Join-Path $ScriptPath "scripts\start_backend.ps1"
    if (-not (Test-Path $BackendScript)) {
        Write-Status "Backend script not found: $BackendScript" "ERROR"
        return
    }
    $label = if ($Profile -eq "fallback") { "LLAMA OFF" } else { "LLAMA NF4" }
    Write-Status "Starting Kimodo Cascadeur backend ($label)..." "INFO"
    & $BackendScript -TextEncoderProfile $Profile
    if ($LASTEXITCODE -eq 0) {
        Write-Status "Backend running at http://127.0.0.1:9552" "SUCCESS"
    }
}

function Stop-Backend {
    $BackendScript = Join-Path $ScriptPath "scripts\stop_backend.ps1"
    if (Test-Path $BackendScript) {
        & $BackendScript
    } else {
        try { Invoke-RestMethod -Uri "http://127.0.0.1:9552/shutdown" -Method Post -TimeoutSec 3 -Body "{}" -ContentType "application/json" } catch {}
        Write-Status "Backend stopped." "INFO"
    }
}

function Install-CascadeurCommand {
    $CmdInstaller = Join-Path $ScriptPath "install_cascadeur_command.ps1"
    if (Test-Path $CmdInstaller) {
        & $CmdInstaller
    } else {
        Write-Status "install_cascadeur_command.ps1 not found." "ERROR"
    }
}

function Show-Menu {
    Clear-Host
    Write-Host " ===========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  ██▓        ██▓    ██▓        ██▓" -ForegroundColor Yellow
    Write-Host " ▓██▒              ▓██▒" -ForegroundColor Yellow
    Write-Host " ▒██░              ▒██░" -ForegroundColor Yellow
    Write-Host " ▒██░              ▒██░" -ForegroundColor Yellow
    Write-Host " ░██████▒ ██▓  ██▓ ░██████▒ ██▓  ██▓" -ForegroundColor Yellow
    Write-Host " ░ ▒░▓  ░ ▒▓▒  ▒▓▒ ░ ▒░▓  ░ ▒▓▒  ▒▓▒" -ForegroundColor Yellow
    Write-Host " ░ ░ ▒  ░ ░▒   ░▒  ░ ░ ▒  ░ ░▒   ░▒" -ForegroundColor Yellow
    Write-Host "   ░ ░    ░    ░     ░ ░    ░    ░" -ForegroundColor Yellow
    Write-Host "     ░  ░  ░    ░      ░  ░  ░    ░" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  ===========================================" -ForegroundColor Cyan
    Write-Host "    KimoDer v2.5.0 - Kimodo+Cascadeur Portable" -ForegroundColor Green
    Write-Host "    Python 3.12 + PyTorch 2.8 CUDA 12.8" -ForegroundColor Cyan
    Write-Host "  ===========================================" -ForegroundColor Cyan
    Write-Host ""
    $installed = Test-IsInstalled
    if ($installed) {
        Write-Host "  1) Start Kimodo Demo" -ForegroundColor Yellow
        Write-Host "  2) Start Cascadeur Backend (LLAMA NF4)" -ForegroundColor Yellow
        Write-Host "  3) Start Cascadeur Backend (LLAMA OFF)" -ForegroundColor Yellow
        Write-Host "  4) Stop Cascadeur Backend" -ForegroundColor Yellow
        Write-Host "  5) Install Cascadeur Command" -ForegroundColor Yellow
        Write-Host "  6) Exit" -ForegroundColor Gray
    } else {
        Write-Host "  [!] Environment not installed." -ForegroundColor Red
        Write-Host "  Run: ./Install_KimoDer-UV.ps1" -ForegroundColor Red
        Write-Host ""
        Write-Host "  1) Exit" -ForegroundColor Gray
    }
    Write-Host ""
    $choice = Read-Host "Choice"
    return $choice, $installed
}

# ---- CLI dispatch (non-interactive mode) ----
if (-not $Menu) {
    $exitCode = 0
    try {
        if (-not (Test-IsInstalled)) { throw "Environment not installed. Run Install_KimoDer-UV.ps1 -Install first." }
        if ($StartBackend) {
            Write-Status "CLI: starting backend ($StartBackend)..." "INFO"
            Start-Backend -Profile $StartBackend
        }
        if ($StopBackend) {
            Write-Status "CLI: stopping backend..." "INFO"
            Stop-Backend
        }
        if ($CheckBackend) {
            try {
                $r = Invoke-RestMethod -Uri "http://127.0.0.1:9552/health" -Method Get -TimeoutSec 5
                Write-Host ($r | ConvertTo-Json -Depth 3) -ForegroundColor Green
                if (-not $r.ok) { $exitCode = 1 }
            } catch {
                Write-Host '{"ok":false,"error":"backend unreachable"}' -ForegroundColor Red
                $exitCode = 1
            }
        }
        if ($StartDemo) {
            Write-Status "CLI: starting demo..." "INFO"
            Start-Demo -Offload $Offload
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

# ---- Main loop ----
do {
    $choice, $installed = Show-Menu
    switch ($choice) {
        "1" {
            if ($installed) {
                $offloadChoice = Read-Host "Start with --offload (GPU < 8GB)? (y/n) [n]"
                Start-Demo -Offload ($offloadChoice -eq 'y')
            } else { exit 0 }
        }
        "2" { if ($installed) { Start-Backend -Profile "llama" } }
        "3" { if ($installed) { Start-Backend -Profile "fallback" } }
        "4" { if ($installed) { Stop-Backend } }
        "5" { if ($installed) { Install-CascadeurCommand } }
        "6" { Write-Status "Exiting." "INFO"; exit 0 }
        default { Write-Status "Invalid choice." "WARN" }
    }
    if ($choice -ne "6") {
        Write-Host "`nPress any key to return to menu..." -ForegroundColor Gray
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    }
} while ($true)

