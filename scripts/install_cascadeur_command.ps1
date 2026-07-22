param(
    [string]$CascadeurRoot = "",
    [string]$KimodoRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $KimodoRoot) {
    $KimodoRoot = (Get-Item $PSScriptRoot).Parent.FullName
}
$KimodoRoot = (Resolve-Path $KimodoRoot).Path
$SrcDir = Join-Path $KimodoRoot "integrations\cascadeur"

Write-Host "===== Kimodo Cascadeur Command Installer =====" -ForegroundColor Cyan
Write-Host "Kimodo root : $KimodoRoot"
Write-Host ""

function Test-CascadeurInstall {
    param([string]$Path)
    if (-not $Path) { return $false }
    $ScriptsDir = Join-Path $Path "resources\scripts\python\commands\animation_scripts"
    return (Test-Path $ScriptsDir)
}

function Find-Cascadeur {
    $candidates = @(
        "C:\Program Files\Cascadeur",
        "C:\Program Files (x86)\Cascadeur",
        "D:\Program Files\Cascadeur",
        "E:\Program Files\Cascadeur"
    )
    foreach ($cand in $candidates) {
        if (Test-CascadeurInstall $cand) {
            return $cand
        }
    }
    return $null
}

if (-not $CascadeurRoot) {
    $detected = Find-Cascadeur
    if ($detected) {
        Write-Host "Detected Cascadeur at: $detected" -ForegroundColor DarkGray
        $useDefault = Read-Host "Use this path? (Y/n)"
        if ($useDefault -eq "" -or $useDefault -eq "y" -or $useDefault -eq "Y") {
            $CascadeurRoot = $detected
        }
    }
}

while (-not (Test-CascadeurInstall $CascadeurRoot)) {
    if ($CascadeurRoot) {
        Write-Host "[!] Not a valid Cascadeur installation: $CascadeurRoot" -ForegroundColor Red
        Write-Host "    Expected folder: resources\scripts\python\commands\animation_scripts\" -ForegroundColor DarkGray
    }
    Write-Host ""
    Write-Host "Enter the full path to your Cascadeur installation folder." -ForegroundColor Yellow
    Write-Host "Example: K:\Software\Cascadeur_2024-3" -ForegroundColor DarkGray
    Write-Host "         D:\Programs\Cascadeur" -ForegroundColor DarkGray
    $CascadeurRoot = Read-Host "Cascadeur path"
    if (-not $CascadeurRoot) {
        Write-Host "Installation cancelled." -ForegroundColor Yellow
        exit 0
    }
    $CascadeurRoot = $CascadeurRoot.Trim('"').Trim()
}

Write-Host "Cascadeur   : $CascadeurRoot" -ForegroundColor Green
Write-Host ""

$CommandDest = Join-Path $CascadeurRoot "resources\scripts\python\commands\animation_scripts"
$SamplesDest = Join-Path $CascadeurRoot "samples"

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    if (-not (Test-Path $CommandDest)) {
        Write-Host "[!] Cannot access scripts folder. Run as Administrator if Cascadeur is in a protected location." -ForegroundColor Yellow
    }
}

$RequiredFiles = @(
    (Join-Path $SrcDir "kimodo_roundtrip.py"),
    (Join-Path $SrcDir "kimodo_roundtrip.ini"),
    (Join-Path $SrcDir "Kimodo.casc")
)
foreach ($file in $RequiredFiles) {
    if (-not (Test-Path $file)) {
        Write-Host "[ERROR] Missing: $file" -ForegroundColor Red
        Write-Host "Run the main installer first (Install_KimoDer-UV.ps1)." -ForegroundColor Red
        exit 1
    }
}

Write-Host "[1/3] Copying Cascadeur command..."
try {
    Copy-Item -Path (Join-Path $SrcDir "kimodo_roundtrip.py") -Destination (Join-Path $CommandDest "kimodo_roundtrip.py") -Force -ErrorAction Stop
    Write-Host "       OK" -ForegroundColor Green
} catch {
    Write-Host "       FAILED: $_" -ForegroundColor Red
    Write-Host "       Run this script as Administrator." -ForegroundColor Yellow
    exit 1
}

Write-Host "[2/3] Copying Kimodo sample scene..."
try {
    Copy-Item -Path (Join-Path $SrcDir "Kimodo.casc") -Destination (Join-Path $SamplesDest "Kimodo.casc") -Force -ErrorAction Stop
    Write-Host "       OK" -ForegroundColor Green
} catch {
    Write-Host "       FAILED: $_" -ForegroundColor Red
    exit 1
}

Write-Host "[3/3] Writing kimodo_roundtrip.ini..."
$IniContent = @"
[paths]
backend_mode = native
kimodo_root = $KimodoRoot
python_exe = kimodo_env\Scripts\python.exe
cascadeur_root = $CascadeurRoot
kimodo_scene = $CascadeurRoot\samples\Kimodo.casc
backend_scripts_dir = scripts
workspace_root = %TEMP%\KimodoCascadeur

[defaults]
prompt =
samples_num = 1
sample_index = 0
seed = -1
denoising_steps = 100
cfg_enabled = True
text_weight = 2.0
constraint_weight = 2.0
dataset = RP
keep_debug_scenes = False
inspect_in_gui = False
"@
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText((Join-Path $CommandDest "kimodo_roundtrip.ini"), $IniContent, $Utf8NoBom)
Write-Host "       OK" -ForegroundColor Green

Remove-Item (Join-Path $CommandDest "kimodo_start.py") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $CommandDest "kimodo_stop.py") -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "===== Cascadeur command installed =====" -ForegroundColor Green
Write-Host "Installed to: $CommandDest"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Start Kimodo backend: Install_KimoDer-UV.ps1 -> menu 2"
Write-Host "  2. Restart Cascadeur"
Write-Host "  3. In Cascadeur: Animation Scripts -> Kimodo Roundtrip"
Write-Host "  4. Click 'Start Kimodo (LLAMA NF4)', then 'Generate'"
Write-Host ""
Write-Host "If you move the Repository folder later, rerun this script to update paths."
