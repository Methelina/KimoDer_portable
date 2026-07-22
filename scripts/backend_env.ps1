$ScriptPath = $PSScriptRoot
if (-not $ScriptPath) { $ScriptPath = "." }
$RepoRoot = (Get-Item -Path $ScriptPath).Parent.FullName

$env:KIMODO_DATA_ROOT = $RepoRoot
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"

$CacheDir = Join-Path $RepoRoot ".cache"
$HfCacheDir = Join-Path $CacheDir "huggingface"
$env:HF_HOME = $HfCacheDir
$env:HUGGINGFACE_HUB_CACHE = Join-Path $HfCacheDir "hub"
$env:HUGGINGFACE_ASSETS_CACHE = Join-Path $HfCacheDir "assets"
$env:TRANSFORMERS_CACHE = Join-Path $HfCacheDir "hub"

$CheckpointDir = Join-Path $RepoRoot "checkpoints"
if (Test-Path $CheckpointDir) {
    $env:CHECKPOINT_DIR = $CheckpointDir
}

$TextEncodersDir = Join-Path $RepoRoot "text-encoders"
if (Test-Path $TextEncodersDir) {
    $env:TEXT_ENCODERS_DIR = $TextEncodersDir
}

$KimodoDir = Join-Path $RepoRoot "kimodo"
if (Test-Path $KimodoDir) {
    $env:PYTHONPATH = $KimodoDir
}

$env:PYTORCH_CUDA_ALLOC_CONF = "garbage_collection_threshold:0.8,expandable_segments:True,max_split_size_mb:128"

$env:TEXT_ENCODER_MODE = "local"

$RuntimeDir = Join-Path $env:TEMP "kimodo-runtime"
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
$env:KIMODO_RUNTIME_DIR = $RuntimeDir

$env:TEXT_ENCODER_TMP_FOLDER = Join-Path $RuntimeDir "text-encoder-tmp"
New-Item -ItemType Directory -Force -Path $env:TEXT_ENCODER_TMP_FOLDER | Out-Null

$env:KIMODO_FBX_FAST_ARMATURE = "1"
$env:KIMODO_FBX_FAST_ONLY = "1"
$env:TQDM_DISABLE = "1"
$env:HF_HUB_DISABLE_PROGRESS_BARS = "1"
