# ==========================================================
# Kimodo Portable Installer & Launcher (v2.5.0-cascadeur)
# ==========================================================
# SYNOPSIS:
#   Fully portable Kimodo installation + Cascadeur hybrid backend.
#   Uses uv, Python 3.12, PyTorch 2.8 CUDA 12.8.
#   All caches and models inside project folder.
#
# USAGE:
#   .\Install_KimoDer-UV.ps1                    = interactive menu
#   .\Install_KimoDer-UV.ps1 -Install           = full install (non-interactive)
#   .\Install_KimoDer-UV.ps1 -Reinstall         = wipe & reinstall (non-interactive)
#   .\Install_KimoDer-UV.ps1 -StartBackend llama = start backend & print status
#   .\Install_KimoDer-UV.ps1 -StartBackend fallback
#   .\Install_KimoDer-UV.ps1 -StopBackend       = stop backend
#   .\Install_KimoDer-UV.ps1 -CheckBackend       = health-check & print JSON
#   .\Install_KimoDer-UV.ps1 -StartDemo [-Offload] = launch demo
#   .\Install_KimoDer-UV.ps1 -InstallCascadeurCommand -CascadeurRoot "path"
# ==========================================================
# Based on: Soror L.'.L.' launcher v2.4.1
# Cascadeur integration: Soror L.'.L.'.
# Version: 2.5.0-cascadeur
# Date: 2026-07-22
# ==========================================================

param(
    [switch]$Install,
    [switch]$Reinstall,
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
$Script:CLI_MODE = ($Install -or $Reinstall -or $StartBackend -or $StopBackend -or $CheckBackend -or $StartDemo -or $InstallCascadeurCommand -or $Menu)
if (-not $Script:CLI_MODE) { $Script:CLI_MODE = $false; $Menu = $true }

# ---- Init ----
$ScriptPath = $PSScriptRoot
if (-not $ScriptPath) { $ScriptPath = "." }
Set-Location $ScriptPath
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "Kimodo+Cascadeur Portable by L.'.L.'."

# ==========================================================
# ASCII Art
# ==========================================================
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
Write-Host "    Kimodo+Cascadeur Portable v2.5.0 by L.'.L.'./Kilo" -ForegroundColor Green
Write-Host "    Python 3.12 + PyTorch 2.8 CUDA 12.8" -ForegroundColor Cyan
Write-Host "    Aero-Ex / Cascadeur Hybrid" -ForegroundColor Cyan
Write-Host "  ===========================================" -ForegroundColor Cyan
Write-Host ""

# ==========================================================
# PORTABILITY ISOLATION BLOCK
# ==========================================================
$EnvName = "kimodo_env"
$CacheDir = Join-Path $ScriptPath ".cache"
$UvCacheDir = Join-Path $CacheDir "uv"
$HfCacheDir = Join-Path $CacheDir "huggingface"
$PipCacheDir = Join-Path $CacheDir "pip"
$TmpDir = Join-Path $CacheDir "tmp"
@($CacheDir, $UvCacheDir, $HfCacheDir, $PipCacheDir, $TmpDir) | ForEach-Object {
    if (-not (Test-Path $_)) { New-Item -ItemType Directory -Force -Path $_ | Out-Null }
}
$env:UV_CACHE_DIR = $UvCacheDir
$env:HF_HOME = $HfCacheDir
$env:PIP_CACHE_DIR = $PipCacheDir
$env:TMP = $TmpDir
$env:TEMP = $TmpDir
$env:HF_HUB_DOWNLOAD_TIMEOUT = "60"

# ---- Optimization variables ----
$env:MKL_DYNAMIC = "TRUE"
$env:MKL_NUMA_DOMAIN = "ALL"
$env:SAFETENSORS_FAST_GPU = "1"
$env:CUDA_MODULE_LOADING = "LAZY"
$env:TF_ENABLE_ONEDNN_OPTS = "1"
$env:NVIDIA_TF32_OVERRIDE = "1"
$env:TORCH_ALLOW_TF32_CUBLAS_OVERRIDE = "1"
$env:TORCH_CUDNN_V8_API_ENABLED = "1"
$env:PYTORCH_CUDA_ALLOC_CONF = "garbage_collection_threshold:0.8,expandable_segments:True,max_split_size_mb:128"
$env:CUDA_VISIBLE_DEVICES = "0"
$env:XFORMERS_MORE_DETAILS = "1"
$env:FLASH_ATTENTION_FORCE_OPTIM = "1"

# ==========================================================
# Helper Functions
# ==========================================================
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

function Test-Command {
    param([string]$Cmd)
    return $null -ne (Get-Command $Cmd -ErrorAction SilentlyContinue)
}

function Test-IsInstalled {
    try { return (Test-Path (Join-Path $ScriptPath $EnvName "Scripts\Activate.ps1")) } catch { return $false }
}

function Invoke-WithRetry {
    param([scriptblock]$Script, [int]$MaxAttempts = 3, [int]$DelaySec = 5)
    $attempt = 0
    while ($attempt -lt $MaxAttempts) {
        try {
            & $Script
            if ($LASTEXITCODE -eq 0) { return $true }
        } catch {}
        $attempt++
        if ($attempt -ge $MaxAttempts) { return $false }
        Write-Status "  Retry in $DelaySec sec... (attempt $attempt of $MaxAttempts)" "WARN"
        Start-Sleep -Seconds $DelaySec
    }
    return $false
}

function Invoke-UvPipInstall {
    param([string]$Command)
    Write-Host "   > uv pip install $Command" -ForegroundColor DarkGray
    $process = Start-Process -FilePath $UvExePath -ArgumentList "pip install --python `"$PythonExePath`" $Command" -NoNewWindow -Wait -PassThru
    return $process.ExitCode
}

function Invoke-PythonCommand {
    param([string]$Command)
    Write-Host "   > python $Command" -ForegroundColor DarkGray
    $process = Start-Process -FilePath $PythonExePath -ArgumentList $Command -NoNewWindow -Wait -PassThru
    return $process.ExitCode
}

# ==========================================================
# EMBEDDED PYTHON PAYLOAD (All-In-One / self-extracting)
# Auto-generated. The two .py helpers are embedded below and
# written next to this script at startup (Expand-EmbeddedPayload).
# ==========================================================
$Embedded_hf_pycurl_download = @'
# -*- coding: utf-8 -*-
"""
Загрузчик моделей HuggingFace через pycurl + HTTP API Hub'а.

Замена для huggingface_hub.snapshot_download в портативной сборке Kimodo.
Никакой зависимости от huggingface_hub: список файлов берётся из публичного
tree-API, а сами файлы качаются напрямую через pycurl (libcurl).

Использование:
    python _hf_pycurl_download.py <repo_id> <local_dir>
                                  [--revision main]
                                  [--repo-type model|dataset|space]
                                  [--token <hf_token>]

Логика:
    1. GET {ENDPOINT}/api/{repo_type}s/{repo_id}/tree/{revision}?recursive=1
       — получаем список всех файлов (с поддержкой пагинации через Link).
    2. Каждый файл качаем через pycurl из
       {ENDPOINT}/{repo_id}/resolve/{revision}/{path}
       (для LFS libcurl сам идёт по редиректу на CDN).
    3. Уже скачанные файлы совпадающего размера пропускаются; частично
       скачанные (*.part) — докачиваются с поддержкой Range (resume).
"""

import argparse
import json
import os
import sys
import time
from io import BytesIO
from urllib.parse import quote, urljoin, urlparse

try:
    import pycurl
except ImportError:
    sys.stderr.write(
        "[hf-pycurl] ОШИБКА: модуль 'pycurl' не установлен.\n"
        "            Установите его: uv pip install pycurl\n"
    )
    sys.exit(2)


ENDPOINT = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
USER_AGENT = "kimodo-pycurl/1.0 (+libcurl)"
CONNECT_TIMEOUT = 30
LOW_SPEED_LIMIT = 1024        # байт/сек: если медленнее...
LOW_SPEED_TIME = 60           # ...в течение стольких секунд — обрыв и повтор
MAX_ATTEMPTS = 5
MAX_REDIRECTS = 10


# --------------------------------------------------------------------------- #
# SSL / CA
# --------------------------------------------------------------------------- #
def _detect_cainfo():
    """Для сборок libcurl на OpenSSL/GnuTLS указываем CA-бандл из certifi.

    Сборки на нативном Schannel (типичны для Windows-wheel'ов pycurl) берут
    доверенные корни из хранилища Windows и CAINFO игнорируют — тогда ничего
    не задаём, чтобы не спровоцировать ошибку.
    """
    try:
        ssl_backend = (pycurl.version_info()[5] or "").lower()
    except Exception:
        ssl_backend = ""
    if any(name in ssl_backend for name in ("openssl", "libressl", "boringssl",
                                            "gnutls", "mbedtls", "wolfssl")):
        try:
            import certifi
            return certifi.where()
        except Exception:
            return None
    return None


_CAINFO = _detect_cainfo()


def _apply_common(c, token, host_is_hf, resume_pos=0):
    c.setopt(pycurl.USERAGENT, USER_AGENT)
    c.setopt(pycurl.CONNECTTIMEOUT, CONNECT_TIMEOUT)
    c.setopt(pycurl.NOSIGNAL, 1)
    c.setopt(pycurl.TCP_KEEPALIVE, 1)
    if _CAINFO:
        try:
            c.setopt(pycurl.CAINFO, _CAINFO)
        except Exception:
            pass
    headers = ["Accept-Encoding: identity"]
    # Токен отправляем только на сам Hub, но НИКОГДА на CDN-редирект (там
    # своя подписанная ссылка, лишний Authorization вызывает 400).
    if token and host_is_hf:
        headers.append("Authorization: Bearer %s" % token)
    # Докачку задаём собственным Range-заголовком, а не RESUME_FROM_LARGE:
    # первый ответ Hub'а — это 302 на CDN, и встроенная в libcurl проверка
    # Range (ждущая 206) свалилась бы на редиректе с ошибкой 33.
    if resume_pos:
        headers.append("Range: bytes=%d-" % resume_pos)
    c.setopt(pycurl.HTTPHEADER, headers)


def _host_is_hf(url):
    host = (urlparse(url).hostname or "").lower()
    ep_host = (urlparse(ENDPOINT).hostname or "").lower()
    return host == ep_host or host.endswith(".huggingface.co") or host == "huggingface.co"


# --------------------------------------------------------------------------- #
# Работа со списком файлов (tree API)
# --------------------------------------------------------------------------- #
def _api_get(url, token):
    """GET JSON. Возвращает (bytes, {rel: url}) из заголовка Link."""
    buf = BytesIO()
    headers = {}

    def _hdr(line):
        try:
            text = line.decode("iso-8859-1")
        except Exception:
            return
        if ":" in text:
            k, v = text.split(":", 1)
            headers[k.strip().lower()] = v.strip()

    c = pycurl.Curl()
    c.setopt(pycurl.URL, url)
    c.setopt(pycurl.FOLLOWLOCATION, 1)
    c.setopt(pycurl.MAXREDIRS, MAX_REDIRECTS)
    c.setopt(pycurl.WRITEDATA, buf)
    c.setopt(pycurl.HEADERFUNCTION, _hdr)
    _apply_common(c, token, host_is_hf=True)
    try:
        c.perform()
        code = c.getinfo(pycurl.RESPONSE_CODE)
    finally:
        c.close()

    if code != 200:
        snippet = buf.getvalue()[:500].decode("utf-8", "replace")
        raise RuntimeError("HF API вернул HTTP %s для %s\n%s" % (code, url, snippet))

    links = {}
    raw = headers.get("link")
    if raw:
        for part in raw.split(","):
            seg = part.split(";")
            if len(seg) < 2:
                continue
            u = seg[0].strip().lstrip("<").rstrip(">")
            for attr in seg[1:]:
                attr = attr.strip()
                if attr.startswith("rel="):
                    rel = attr[4:].strip().strip('"')
                    links[rel] = u
    return buf.getvalue(), links


def list_repo_files(repo_id, revision, repo_type, token):
    """Список (path, size) всех файлов репозитория (рекурсивно, с пагинацией)."""
    prefix = {"model": "models", "dataset": "datasets", "space": "spaces"}[repo_type]
    url = "%s/api/%s/%s/tree/%s?recursive=1" % (
        ENDPOINT, prefix, repo_id, quote(revision, safe=""))
    files = []
    while url:
        body, links = _api_get(url, token)
        for item in json.loads(body):
            if item.get("type") != "file":
                continue
            size = item.get("size")
            lfs = item.get("lfs")
            if isinstance(lfs, dict) and lfs.get("size") is not None:
                size = lfs["size"]
            files.append((item["path"], size))
        url = links.get("next")
    return files


# --------------------------------------------------------------------------- #
# Скачивание одного файла
# --------------------------------------------------------------------------- #
class _Sink:
    """Пишет тело ответа в файл; тело редиректов/ошибок отбрасывает.

    Учитывает Range: при 206 дописывает от resume_pos, при 200 (сервер Range
    проигнорировал) — перезаписывает файл с нуля.
    """

    def __init__(self, path, resume_pos, total, name):
        self.path = path
        self.resume_pos = resume_pos
        self.total = total or 0
        self.name = name
        self.status = None
        self.location = None
        self.fh = None
        self._last_pct = -1

    def header(self, line):
        try:
            text = line.decode("iso-8859-1").strip()
        except Exception:
            return
        if text.startswith("HTTP/"):
            parts = text.split()
            if len(parts) >= 2 and parts[1].isdigit():
                self.status = int(parts[1])
            self.location = None          # новый ответ в цепочке редиректов
        elif ":" in text:
            k, v = text.split(":", 1)
            if k.strip().lower() == "location":
                self.location = v.strip()

    def _open(self):
        if self.fh is not None:
            return
        if self.status == 206 and self.resume_pos:
            self.fh = open(self.path, "r+b")
            self.fh.seek(self.resume_pos)
        else:                              # 200 или скачивание с нуля
            self.fh = open(self.path, "wb")

    def write(self, data):
        if self.status is None:
            return len(data)
        if 200 <= self.status < 300:
            self._open()
            self.fh.write(data)
        return len(data)                   # тело не-2xx проглатываем

    def xferinfo(self, dltotal, dlnow, ultotal, ulnow):
        # Прогресс считаем только по телу успешного ответа: тело редиректов
        # (3xx) и ошибок не относится к файлу и портило бы проценты.
        if self.status is None or not (200 <= self.status < 300):
            return
        base = self.resume_pos if self.status == 206 else 0
        done = base + dlnow
        total = self.total or (base + dltotal)
        if total <= 0:
            return
        pct = int(done * 100 / total)
        pct = 0 if pct < 0 else (100 if pct > 100 else pct)
        if pct != self._last_pct:
            self._last_pct = pct
            bar = ("#" * (pct // 4)).ljust(25)
            sys.stdout.write("\r    [%s] %3d%%  %s" % (bar, pct, self.name))
            sys.stdout.flush()

    def close(self):
        if self.fh is not None:
            self.fh.close()
            self.fh = None


def _download_once(url, sink, token):
    """Одна попытка: ручное следование редиректам, чтобы не слать токен на CDN."""
    current = url
    for _ in range(MAX_REDIRECTS):
        sink.status = None
        sink.location = None
        c = pycurl.Curl()
        c.setopt(pycurl.URL, current)
        c.setopt(pycurl.FOLLOWLOCATION, 0)
        c.setopt(pycurl.HEADERFUNCTION, sink.header)
        c.setopt(pycurl.WRITEFUNCTION, sink.write)
        c.setopt(pycurl.NOPROGRESS, 0)
        c.setopt(pycurl.XFERINFOFUNCTION, sink.xferinfo)
        c.setopt(pycurl.LOW_SPEED_LIMIT, LOW_SPEED_LIMIT)
        c.setopt(pycurl.LOW_SPEED_TIME, LOW_SPEED_TIME)
        _apply_common(c, token, host_is_hf=_host_is_hf(current),
                      resume_pos=sink.resume_pos)
        try:
            c.perform()
            code = c.getinfo(pycurl.RESPONSE_CODE)
        finally:
            c.close()

        if code in (301, 302, 303, 307, 308) and sink.location:
            current = urljoin(current, sink.location)
            continue
        if 200 <= code < 300:
            return
        raise RuntimeError("HTTP %s" % code)
    raise RuntimeError("превышено число редиректов")


def download_file(repo_id, revision, path, size, dest, token):
    """Скачивает один файл репозитория в dest с докачкой и повторами."""
    if size is not None and os.path.isfile(dest) and os.path.getsize(dest) == size:
        print("    ПРОПУСК (уже скачан): %s" % path)
        return

    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    part = dest + ".part"
    url = "%s/%s/resolve/%s/%s" % (
        ENDPOINT, repo_id, quote(revision, safe=""),
        "/".join(quote(seg, safe="") for seg in path.split("/")))

    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        resume_pos = os.path.getsize(part) if os.path.isfile(part) else 0
        if size is not None and resume_pos >= size:
            resume_pos = 0                 # битый .part — качаем заново
        sink = _Sink(part, resume_pos, size, path)
        try:
            _download_once(url, sink, token)
            sink.close()
            sys.stdout.write("\n")
            if size is not None and os.path.getsize(part) != size:
                raise RuntimeError("размер не совпал: ожидалось %s, получено %s"
                                   % (size, os.path.getsize(part)))
            if os.path.exists(dest):
                os.remove(dest)
            os.replace(part, dest)
            return
        except Exception as exc:            # noqa: BLE001 — повторяем любую сетевую ошибку
            sink.close()
            last_err = exc
            sys.stdout.write("\n")
            if attempt < MAX_ATTEMPTS:
                delay = min(2 ** attempt, 30)
                print("    ! %s (попытка %d/%d), повтор через %dс..."
                      % (exc, attempt, MAX_ATTEMPTS, delay))
                time.sleep(delay)

    raise RuntimeError("не удалось скачать %s: %s" % (path, last_err))


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(
        description="Скачивание репозитория HuggingFace через pycurl + HF API.")
    ap.add_argument("repo_id", help="например Aero-Ex/KIMODO-Meta3_llm2vec_NF4")
    ap.add_argument("local_dir", help="куда сложить файлы")
    ap.add_argument("--revision", default="main", help="ветка/тег/commit (по умолчанию main)")
    ap.add_argument("--repo-type", default="model",
                    choices=["model", "dataset", "space"])
    ap.add_argument("--token", default=None, help="HF-токен для приватных/gated репо")
    args = ap.parse_args()

    token = (args.token
             or os.environ.get("HF_TOKEN")
             or os.environ.get("HUGGING_FACE_HUB_TOKEN")
             or os.environ.get("HUGGINGFACE_HUB_TOKEN"))

    print("=" * 60)
    print(" HF pycurl downloader")
    print("   repo     : %s (%s)" % (args.repo_id, args.repo_type))
    print("   revision : %s" % args.revision)
    print("   endpoint : %s" % ENDPOINT)
    print("   dest     : %s" % args.local_dir)
    try:
        print("   libcurl  : %s" % pycurl.version)
    except Exception:
        pass
    print("=" * 60)

    try:
        files = list_repo_files(args.repo_id, args.revision, args.repo_type, token)
    except Exception as exc:               # noqa: BLE001
        sys.stderr.write("[hf-pycurl] Не удалось получить список файлов: %s\n" % exc)
        return 1

    if not files:
        sys.stderr.write("[hf-pycurl] В репозитории не найдено файлов.\n")
        return 1

    total_bytes = sum(s for _, s in files if s)
    print("Файлов: %d, суммарный размер: %.2f GB\n"
          % (len(files), total_bytes / (1024 ** 3)))

    os.makedirs(args.local_dir, exist_ok=True)
    for idx, (path, size) in enumerate(files, 1):
        human = "%.1f MB" % (size / (1024 ** 2)) if size else "?"
        print("[%d/%d] %s (%s)" % (idx, len(files), path, human))
        dest = os.path.join(args.local_dir, *path.split("/"))
        try:
            download_file(args.repo_id, args.revision, path, size, dest, token)
        except Exception as exc:           # noqa: BLE001
            sys.stderr.write("[hf-pycurl] ОШИБКА: %s\n" % exc)
            return 1

    print("\n[hf-pycurl] Готово: все файлы скачаны в %s" % args.local_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'@

$Embedded_llm2vec_wrapper_template = @'
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""LLM2Vec encoder wrapper for Kimodo text conditioning."""

import os
import gc
import numpy as np
import torch
from torch import nn
from .llm2vec import LLM2Vec


class LLM2VecEncoder(nn.Module):
    """LLM2Vec text embeddings."""

    def __init__(
        self,
        base_model_name_or_path: str,
        peft_model_name_or_path: str,
        dtype: str,
        llm_dim: int,
    ) -> None:
        super().__init__()
        self.torch_dtype = getattr(torch, dtype)
        self.llm_dim = llm_dim
        # Update this path to where your model is actually located!
        self.custom_dir = "__MODEL_DIR__"
        print(f"[LLM2VecEncoder] Initialized (Waiting for first use to load weights)...")
        self.model = None

    def unload(self):
        """Offload the model weights to System RAM (CPU) if currently on GPU."""
        if self.model is not None:
            if self.get_device().type == "cuda":
                print(f"[LLM2VecEncoder] Offloading 5.4GB model to System RAM...")
                self.model.model.to("cpu")
                gc.collect()
                import platform
                if platform.system() == "Linux":
                    try:
                        import ctypes
                        ctypes.CDLL("libc.so.6").malloc_trim(0)
                    except Exception:
                        pass
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()

    def reload(self):
        """Move from System RAM to VRAM."""
        if self.model is None:
            print(f"[LLM2VecEncoder] Model was None. Reloading from disk (15s delay)...")
            self.model = LLM2Vec.from_pretrained(
                base_model_name_or_path=self.custom_dir,
                peft_model_name_or_path=None,
                torch_dtype=self.torch_dtype,
                device_map="cpu"
            )

        from kimodo.demo.memory_manager import manager
        manager.ensure_vram_capacity(5400 * 1024 * 1024, device="cuda:0", exclude_name="text_encoder")

        curr_device = self.get_device()
        if curr_device.type != "cuda":
            print(f"[LLM2VecEncoder] Moving weights to GPU (cuda:0)...")
            self.model.model.to("cuda:0")

            gc.collect()
            import platform
            if platform.system() == "Linux":
                try:
                    import ctypes
                    ctypes.CDLL("libc.so.6").malloc_trim(0)
                except Exception:
                    pass
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

            manager.log_memory_usage("Encoder Transfer Complete (RAM Reclaimed)")
        else:
            print(f"[LLM2VecEncoder] Model already on GPU ({curr_device})")

    def get_device(self):
        if self.model is None:
            return torch.device("cpu")
        for p in self.model.model.parameters():
            if p.device.type != "meta":
                return p.device
        return torch.device("cpu")

    def delete(self):
        """Reclaim RAM without deleting from disk unless absolutely necessary."""
        # We no longer delete the model by default to avoid slow reloads.
        # Just unload to CPU instead.
        self.unload()

    def __call__(self, text: list[str] | str):
        self.reload()  # Auto-reload if called
        is_string = False
        if isinstance(text, str):
            text = [text]
            is_string = True

        results = []
        for t in text:
            with torch.no_grad():
                emb = self.model.encode([t])
                results.append(emb)

        encoded_text = np.concatenate(results, axis=0)

        assert len(encoded_text.shape)
        assert self.llm_dim == encoded_text.shape[-1]

        encoded_text = encoded_text[:, None]
        lengths = np.ones(len(encoded_text), dtype=int).tolist()

        if is_string:
            encoded_text = encoded_text[0]
            lengths = lengths[0]

        encoded_text = torch.tensor(encoded_text).to(self.get_device())
        return encoded_text, lengths
'@

function Expand-EmbeddedPayload {
    # Materialize the embedded Python helpers next to this script (AIO mode).
    # Always overwrites so the embedded copies are the single source of truth.
    $Utf8NoBom = New-Object System.Text.UTF8Encoding $false
    $targets = [ordered]@{
        "_hf_pycurl_download.py"       = $Embedded_hf_pycurl_download
        "_llm2vec_wrapper_template.py" = $Embedded_llm2vec_wrapper_template
    }
    foreach ($name in $targets.Keys) {
        $dest = Join-Path $ScriptPath $name
        try {
            [System.IO.File]::WriteAllText($dest, $targets[$name], $Utf8NoBom)
            Write-Status "Embedded file ready: $name" "SUCCESS"
        } catch {
            Write-Status "Failed to write ${name}: $_" "ERROR"
        }
    }
}

# ==========================================================
# INSTALL FUNCTION
# ==========================================================
function Install-Kimodo {
    param([bool]$Reinstall = $false)

    if ($Reinstall) {
        Write-Status "Reinstall: removing existing components..." "WARN"
        if (Test-Path $EnvName) { Remove-Item -Path $EnvName -Recurse -Force }
        if (Test-Path "kimodo") { Remove-Item -Path "kimodo" -Recurse -Force }
        if (Test-Path "KIMODO-Meta3_llm2vec_NF4") { Remove-Item -Path "KIMODO-Meta3_llm2vec_NF4" -Recurse -Force }
    }

    # ---- 0. Download uv ----
    $UvVersion = "0.11.6"
    $UvZipUrl = "https://releases.astral.sh/github/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip"
    $global:UvExePath = Join-Path $ScriptPath "bin\uv.exe"
    if (-not (Test-Path $UvExePath)) {
        Write-Status "Downloading uv $UvVersion..." "INFO"
        $uvZip = Join-Path $ScriptPath "uv.zip"
        try { Invoke-WebRequest -Uri $UvZipUrl -OutFile $uvZip -ErrorAction Stop } catch {
            Write-Status "Failed to download uv: $_" "ERROR"
            return $false
        }
        if ((Get-Item $uvZip).Length -lt 1000) {
            Write-Status "Downloaded file is corrupted." "ERROR"
            Remove-Item $uvZip -Force -ErrorAction SilentlyContinue
            return $false
        }
        $uvTmp = Join-Path $ScriptPath "uv_tmp"
        if (Test-Path $uvTmp) { Remove-Item -Recurse -Force $uvTmp }
        Expand-Archive -Path $uvZip -DestinationPath $uvTmp -Force
        $extractedDir = Get-ChildItem -Path $uvTmp -Directory | Select-Object -First 1
        if (-not $extractedDir) { $extractedDir = @{ FullName = $uvTmp } }
        Copy-Item (Join-Path $extractedDir.FullName "uv.exe") $UvExePath
        Copy-Item (Join-Path $extractedDir.FullName "uvx.exe") (Join-Path $ScriptPath "bin\uvx.exe") -ErrorAction SilentlyContinue
        Remove-Item $uvTmp -Recurse -Force
        Remove-Item $uvZip -Force
        Write-Status "uv $UvVersion ready." "SUCCESS"
    } else {
        Write-Status "uv already exists." "SUCCESS"
    }

    # ---- 1. Create venv ----
    $PythonVersion = "3.12"
    $EnvDirPath = Join-Path $ScriptPath $EnvName
    if (Test-Path $EnvDirPath) { Remove-Item -Recurse -Force $EnvDirPath }
    Write-Status "Creating virtual environment ($EnvName, Python $PythonVersion)..." "INFO"
    & $UvExePath venv $EnvDirPath --python $PythonVersion
    if ($LASTEXITCODE -ne 0) {
        Write-Status "Failed to create environment." "ERROR"
        return $false
    }
    # Python.exe link for compatibility
    $pythonTarget = Join-Path $EnvDirPath "Scripts\python.exe"
    $pythonLink = Join-Path $EnvDirPath "python.exe"
    if (-not (Test-Path $pythonLink)) {
        try { New-Item -ItemType HardLink -Path $pythonLink -Target $pythonTarget -ErrorAction Stop | Out-Null } catch {
            Set-Content -Path $pythonLink -Value "@`"%~dp0Scripts\python.exe`" %*" -Encoding ASCII
        }
    }
    $global:PythonExePath = Join-Path $EnvDirPath "Scripts\python.exe"
    Write-Status "Environment created." "SUCCESS"

    # ---- 2. Install PyTorch ----
    Write-Status "Installing PyTorch 2.8.0+cu128..." "INFO"
    $TorchCmd = "torch==2.8.0+cu128 torchvision==0.23.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128"
    if (Invoke-UvPipInstall $TorchCmd -ne 0) {
        Write-Status "Failed to install PyTorch." "ERROR"
        return $false
    }

    # ---- 3. Base packages ----
    # Download models with our pycurl loader (HF HTTP API)
    # instead of huggingface_hub. certifi needed for CA bundle if
    # libcurl built against OpenSSL.
    Write-Status "Installing model downloader (pycurl + certifi)..." "INFO"
    Invoke-UvPipInstall "pycurl certifi"

    # ---- 4. Clone repositories ----
    Write-Status "Cloning repositories..." "INFO"
    $KimodoRepo = "https://github.com/Aero-Ex/kimodo.git"
    $ViserRepo = "https://github.com/nv-tlabs/kimodo-viser.git"
    $KimodoDir = Join-Path $ScriptPath "kimodo"
    $ViserDir = Join-Path $KimodoDir "kimodo-viser"
    if (Test-Path $KimodoDir) { Remove-Item -Recurse -Force $KimodoDir }
    git clone $KimodoRepo $KimodoDir
    if ($LASTEXITCODE -ne 0) {
        Write-Status "Failed to clone Kimodo." "ERROR"
        return $false
    }
    Push-Location $KimodoDir
    git clone $ViserRepo $ViserDir
    if ($LASTEXITCODE -ne 0) {
        Write-Status "Failed to clone Viser." "ERROR"
        Pop-Location
        return $false
    }
    Pop-Location
    Write-Status "Repositories cloned." "SUCCESS"

    # ---- 5. Install Kimodo and Viser (editable) ----
    Write-Status "Installing Kimodo and Viser dependencies..." "INFO"
    Push-Location $KimodoDir
    Invoke-UvPipInstall "-e `"$ViserDir`""
    $env:SKIP_MOTION_CORRECTION_IN_SETUP = "1"
    Invoke-UvPipInstall "-e ."
    Remove-Item Env:SKIP_MOTION_CORRECTION_IN_SETUP -ErrorAction SilentlyContinue
    Pop-Location

    # ---- 6. motion_correction ----
    Write-Status "Installing motion_correction..." "INFO"
    $pyTag = & $PythonExePath -c "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')" 2>$null
    if ($pyTag) {
        $pyTag = "cp$pyTag"
        $wheelUrl = "https://github.com/Aero-Ex/kimodo/releases/download/v1.0.0/motion_correction-1.0.0-$pyTag-$pyTag-win_amd64.whl"
        Write-Status "Trying pre-built wheel for $pyTag..." "INFO"
        $ok = Invoke-WithRetry -Script {
            Invoke-UvPipInstall $wheelUrl
            if ($LASTEXITCODE -ne 0) { throw "Wheel install failed" }
        }
        if ($ok) {
            Write-Status "motion_correction installed (wheel)." "SUCCESS"
        } else {
            Write-Status "Pre-built wheel failed. Building from source..." "WARN"
            $hasCMake = Test-Command "cmake"
            $hasCompiler = (Test-Command "cl") -or (Test-Command "g++")
            if (-not $hasCMake -or -not $hasCompiler) {
                Write-Status "Building from source requires CMake and a C++ compiler. Install them and restart the installer." "ERROR"
                return $false
            }
            Push-Location $KimodoDir
            $env:SKIP_MOTION_CORRECTION_IN_SETUP = "0"
            Invoke-UvPipInstall "-e . --no-build-isolation"
            Remove-Item Env:SKIP_MOTION_CORRECTION_IN_SETUP -ErrorAction SilentlyContinue
            Pop-Location
            Write-Status "motion_correction built from source." "SUCCESS"
        }
    } else {
        Write-Status "Could not determine Python version. Skipping motion_correction." "WARN"
    }

    # ---- 7. ML dependencies ----
    Write-Status "Installing bitsandbytes, transformers, dearpygui..." "INFO"
    Invoke-UvPipInstall "bitsandbytes"
    Invoke-UvPipInstall "transformers==5.1.0"
    Invoke-UvPipInstall "dearpygui"

    # ---- 8. Download LLM2Vec model (pycurl, no huggingface_hub) ----
    Write-Status "Downloading LLM2Vec model (NF4) via pycurl..." "INFO"
    $ModelRepo = "Aero-Ex/KIMODO-Meta3_llm2vec_NF4"
    $ModelDir = Join-Path $ScriptPath "KIMODO-Meta3_llm2vec_NF4"
    $DownloaderScript = Join-Path $ScriptPath "_hf_pycurl_download.py"
    if (Test-Path $ModelDir) {
        Write-Status "Model already downloaded." "SUCCESS"
    } elseif (-not (Test-Path $DownloaderScript)) {
        Write-Status "Downloader _hf_pycurl_download.py not found next to script." "ERROR"
        return $false
    } else {
        # The downloader supports resume and retry per file, so
        # the outer Invoke-WithRetry is an extra safety net.
        $ok = Invoke-WithRetry -Script {
            & $PythonExePath $DownloaderScript $ModelRepo $ModelDir --revision main
            if ($LASTEXITCODE -ne 0) { throw "Download failed" }
        }
        if ($ok) {
            Write-Status "Model downloaded." "SUCCESS"
        } else {
            Write-Status "Failed to download model. Try again later." "ERROR"
            return $false
        }
    }

    # ---- 8b. Download Kimodo-SOMA-RP-v1 diffusion model ----
    Write-Status "Downloading Kimodo-SOMA-RP-v1 model (~1.1GB)..." "INFO"
    $SomaModelDir = Join-Path $HfCacheDir "hub"
    $downloadOk = Invoke-WithRetry -Script {
        & $PythonExePath -c "from huggingface_hub import snapshot_download; print(snapshot_download('nvidia/Kimodo-SOMA-RP-v1'))"
        if ($LASTEXITCODE -ne 0) { throw "SOMA model download failed" }
    }
    if ($downloadOk) {
        Write-Status "Kimodo-SOMA-RP-v1 downloaded." "SUCCESS"
    } else {
        Write-Status "Failed to download SOMA model. Backend will download it on first start." "WARN"
    }

    # ---- 9. Apply patches ----
    Write-Status "Applying patches..." "INFO"
    $WrapperTemplate = Join-Path $ScriptPath "_llm2vec_wrapper_template.py"
    $WrapperDest = Join-Path $KimodoDir "kimodo\model\llm2vec\llm2vec_wrapper.py"
    if ((Test-Path $WrapperTemplate) -and (Test-Path $WrapperDest)) {
        $modelPath = $ModelDir -replace "\\", "/"
        $content = Get-Content $WrapperTemplate -Raw
        $content = $content -replace "__MODEL_DIR__", $modelPath
        $Utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText($WrapperDest, $content, $Utf8NoBom)
        Write-Status "Wrapper updated." "SUCCESS"
    } else {
        Write-Status "Wrapper template not found. Skipping." "WARN"
    }
    $playbackFile = Join-Path $KimodoDir "kimodo\viz\playback.py"
    if (Test-Path $playbackFile) {
        $content = Get-Content $playbackFile -Raw
        $old = "self.skeleton.neutral_joints[[self.skeleton.root_idx]]"
        $new = "self.skeleton.neutral_joints[[self.skeleton.root_idx]].to(new_posed_joints.device)"
        if ($content -match [regex]::Escape($old)) {
            $content = $content -replace [regex]::Escape($old), $new
            $Utf8NoBom = New-Object System.Text.UTF8Encoding $false
            [System.IO.File]::WriteAllText($playbackFile, $content, $Utf8NoBom)
            Write-Status "playback.py patched." "SUCCESS"
        } else {
            Write-Status "playback.py already patched." "WARN"
        }
    } else {
        Write-Status "playback.py not found." "WARN"
    }

    # ---- 10. Build Viser client (if Node.js is present) ----
    Write-Status "Building Viser client (optional)..." "INFO"
    $clientDir = Join-Path $ViserDir "src\viser\client"
    $buildDir = Join-Path $clientDir "build"
    if (Test-Path $buildDir) {
        Write-Status "Viser client already built." "SUCCESS"
    } else {
        if (Test-Command "node") {
            Push-Location $clientDir
            Write-Status "Installing npm dependencies..." "INFO"
            npm install --legacy-peer-deps
            if ($LASTEXITCODE -eq 0) {
                Write-Status "Building client..." "INFO"
                npx vite build
                if ($LASTEXITCODE -eq 0) {
                    Write-Status "Viser client built." "SUCCESS"
                } else {
                    Write-Status "Vite build failed." "ERROR"
                }
            } else {
                Write-Status "npm install failed." "ERROR"
            }
            Pop-Location
        } else {
            Write-Status "Node.js not found. Build skipped. You can build manually later." "WARN"
        }
    }

    # ---- 11. Install Cascadeur hybrid components ----
    Write-Status "Installing Cascadeur hybrid components..." "INFO"
    $KimodoPkg = Join-Path $KimodoDir "kimodo"
    $AddonsSrc = Join-Path $ScriptPath "kimodo_addons"

    # 11a. FBX export modules
    Write-Status "  FBX export..." "INFO"
    Copy-Item -Path (Join-Path $AddonsSrc "exports\fbx.py") -Destination (Join-Path $KimodoPkg "exports\fbx.py") -Force -ErrorAction SilentlyContinue
    Copy-Item -Path (Join-Path $AddonsSrc "exports\blender_fbx_export.py") -Destination (Join-Path $KimodoPkg "exports\blender_fbx_export.py") -Force -ErrorAction SilentlyContinue
    $FbxDst = Join-Path $KimodoPkg "assets\fbx"
    New-Item -ItemType Directory -Force -Path $FbxDst | Out-Null
    Copy-Item -Path (Join-Path $AddonsSrc "assets\fbx\*") -Destination $FbxDst -Force -ErrorAction SilentlyContinue

    # 11b. HashTextEncoder (LLAMA OFF fallback)
    Write-Status "  HashTextEncoder..." "INFO"
    Copy-Item -Path (Join-Path $AddonsSrc "model\hash_text_encoder.py") -Destination (Join-Path $KimodoPkg "model\hash_text_encoder.py") -Force -ErrorAction SilentlyContinue

    # 11c. io_scene_fbx (headless FBX addon modules)
    Write-Status "  io_scene_fbx addon..." "INFO"
    $BlenderAddonDst = Join-Path $KimodoDir "tools\blender-4.2.12-linux-x64\4.2\scripts\addons_core\io_scene_fbx"
    New-Item -ItemType Directory -Force -Path $BlenderAddonDst | Out-Null
    Copy-Item -Path (Join-Path $ScriptPath "tools\io_scene_fbx\*") -Destination $BlenderAddonDst -Recurse -Force -ErrorAction SilentlyContinue

    # 11d. Register hash encoder preset in load_model.py
    Write-Status "  Registering hash encoder preset..." "INFO"
    $LoadModelPath = Join-Path $KimodoPkg "model\load_model.py"
    if (Test-Path $LoadModelPath) {
        $content = Get-Content $LoadModelPath -Raw
        if ($content -notmatch '"hash"\s*:') {
            $hashEntry = 'TEXT_ENCODER_PRESETS = {' + "`n" + '    "hash": {' + "`n" + '        "target": "kimodo.model.hash_text_encoder.HashTextEncoder",' + "`n" + '        "kwargs": {' + "`n" + '            "llm_dim": 4096,' + "`n" + '        },' + "`n" + '    },'
            $patched = $content -replace '(?m)^TEXT_ENCODER_PRESETS\s*=\s*\{\s*$', $hashEntry
            if ($patched -ne $content) {
                $Utf8NoBom = New-Object System.Text.UTF8Encoding $false
                [System.IO.File]::WriteAllText($LoadModelPath, $patched, $Utf8NoBom)
            } else {
                Write-Status "  Could not locate TEXT_ENCODER_PRESETS block. Hash preset NOT registered." "WARN"
            }
        }
    }

    Write-Status "Installation complete!" "SUCCESS"
    return $true
}

# ==========================================================
# START CASCADEUR BACKEND
# ==========================================================
function Start-CascadeurBackend {
    param([string]$Profile = "llama")

    if (-not (Test-IsInstalled)) {
        Write-Status "Environment not installed. Run the installer first." "ERROR"
        return $false
    }

    Write-Status "Checking and applying patches..." "INFO"
    if (-not (Ensure-PatchesApplied)) {
        Write-Status "Patch was not applied. Model loading may fail." "WARN"
    }

    $BackendScript = Join-Path $ScriptPath "scripts\backend_ctl.py"
    if (-not (Test-Path $BackendScript)) {
        Write-Status "Backend script not found: $BackendScript. Install hybrid components first." "ERROR"
        return $false
    }
    $PythonExe = Join-Path $ScriptPath "kimodo_env\Scripts\python.exe"

    $ProfileLabel = if ($Profile -eq "fallback") { "LLAMA OFF" } else { "LLAMA NF4" }
    Write-Status "Starting Kimodo Cascadeur backend ($ProfileLabel)..." "INFO"

    & $PythonExe $BackendScript start --profile $Profile
    if ($LASTEXITCODE -eq 0) {
        Write-Status "Backend running at http://127.0.0.1:9552" "SUCCESS"
    } else {
        Write-Status "Failed to start backend." "ERROR"
    }
    return $true
}

function Stop-CascadeurBackend {
    $BackendScript = Join-Path $ScriptPath "scripts\backend_ctl.py"
    $PythonExe = Join-Path $ScriptPath "kimodo_env\Scripts\python.exe"
    if (-not (Test-Path $BackendScript)) {
        Write-Status "Backend script not found." "ERROR"
        return $false
    }
    Write-Status "Stopping Kimodo Cascadeur backend..." "INFO"
    & $PythonExe $BackendScript stop
    return $true
}

# ==========================================================
# UPDATE REPOSITORIES
# ==========================================================
function Update-Repositories {
    Write-Status "Updating repositories (git pull)..." "INFO"
    $KimodoDir = Join-Path $ScriptPath "kimodo"
    $ViserDir = Join-Path $KimodoDir "kimodo-viser"
    if (Test-Path $KimodoDir) {
        Push-Location $KimodoDir
        git pull
        Pop-Location
    }
    if (Test-Path $ViserDir) {
        Push-Location $ViserDir
        git pull
        Pop-Location
    }
    Write-Status "Repositories updated." "SUCCESS"
}

# ==========================================================
# FORCE PATCH APPLICATION (before launch)
# ==========================================================
function Ensure-PatchesApplied {
    $KimodoDir = Join-Path $ScriptPath "kimodo"
    $ModelDir = Join-Path $ScriptPath "KIMODO-Meta3_llm2vec_NF4"
    $WrapperDest = Join-Path $KimodoDir "kimodo\model\llm2vec\llm2vec_wrapper.py"
    $WrapperTemplate = Join-Path $ScriptPath "_llm2vec_wrapper_template.py"

    if (-not (Test-Path $WrapperTemplate)) {
        Write-Status "Wrapper template not found. Skipping patch." "WARN"
        return $false
    }
    if (-not (Test-Path $WrapperDest)) {
        Write-Status "Target wrapper file not found ($WrapperDest). Skipping." "WARN"
        return $false
    }
    if (-not (Test-Path $ModelDir)) {
        Write-Status "Model folder not found ($ModelDir). Model may not be downloaded." "ERROR"
        return $false
    }

    $currentContent = Get-Content $WrapperDest -Raw
    $correctPath = $ModelDir -replace "\\", "/"
    if ($currentContent -match "self\.custom_dir\s*=\s*['""]([^'""]+)['""]") {
        $currentPath = $Matches[1]
        if ($currentPath -eq $correctPath) {
            Write-Status "Wrapper path already correct: $correctPath" "SUCCESS"
            return $true
        } else {
            Write-Status "Wrapper path differs: $currentPath → $correctPath" "WARN"
        }
    } else {
        Write-Status "Could not find self.custom_dir in wrapper. Applying patch." "WARN"
    }

    $templateContent = Get-Content $WrapperTemplate -Raw
    $newContent = $templateContent -replace "__MODEL_DIR__", $correctPath
    if ($newContent -eq $templateContent) {
        Write-Status "Template missing __MODEL_DIR__ marker. Nothing to replace." "WARN"
        return $false
    }

    $Utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($WrapperDest, $newContent, $Utf8NoBom)
    Write-Status "Wrapper successfully updated. Path: $correctPath" "SUCCESS"

    # playback.py patch (idempotent, self-healing after git pull)
    $playbackFile = Join-Path $KimodoDir "kimodo\viz\playback.py"
    if (Test-Path $playbackFile) {
        $pb = Get-Content $playbackFile -Raw
        $pbOld = "self.skeleton.neutral_joints[[self.skeleton.root_idx]]"
        $pbNew = "self.skeleton.neutral_joints[[self.skeleton.root_idx]].to(new_posed_joints.device)"
        if (($pb -match [regex]::Escape($pbOld)) -and ($pb -notmatch [regex]::Escape($pbNew))) {
            $pb = $pb -replace [regex]::Escape($pbOld), $pbNew
            [System.IO.File]::WriteAllText($playbackFile, $pb, $Utf8NoBom)
            Write-Status "playback.py patched." "SUCCESS"
        }
    }

    # hash encoder preset in load_model.py (idempotent, self-healing after git pull)
    $LoadModelPath = Join-Path $KimodoDir "kimodo\model\load_model.py"
    if (Test-Path $LoadModelPath) {
        $lm = Get-Content $LoadModelPath -Raw
        if ($lm -notmatch '"hash"\s*:') {
            $hashEntry = 'TEXT_ENCODER_PRESETS = {' + "`n" + '    "hash": {' + "`n" + '        "target": "kimodo.model.hash_text_encoder.HashTextEncoder",' + "`n" + '        "kwargs": {' + "`n" + '            "llm_dim": 4096,' + "`n" + '        },' + "`n" + '    },'
            $lmPatched = $lm -replace '(?m)^TEXT_ENCODER_PRESETS\s*=\s*\{\s*$', $hashEntry
            if ($lmPatched -ne $lm) {
                [System.IO.File]::WriteAllText($LoadModelPath, $lmPatched, $Utf8NoBom)
                Write-Status "Hash encoder preset registered." "SUCCESS"
            }
        }
    }

    # hybrid addon files (idempotent re-copy after git pull)
    $AddonsSrc = Join-Path $ScriptPath "kimodo_addons"
    $KimodoPkg = Join-Path $KimodoDir "kimodo"
    if (Test-Path $AddonsSrc) {
        if (-not (Test-Path (Join-Path $KimodoPkg "exports\fbx.py"))) {
            Copy-Item -Path (Join-Path $AddonsSrc "exports\fbx.py") -Destination (Join-Path $KimodoPkg "exports\fbx.py") -Force -ErrorAction SilentlyContinue
            Copy-Item -Path (Join-Path $AddonsSrc "exports\blender_fbx_export.py") -Destination (Join-Path $KimodoPkg "exports\blender_fbx_export.py") -Force -ErrorAction SilentlyContinue
            $FbxDst = Join-Path $KimodoPkg "assets\fbx"
            New-Item -ItemType Directory -Force -Path $FbxDst | Out-Null
            Copy-Item -Path (Join-Path $AddonsSrc "assets\fbx\*") -Destination $FbxDst -Force -ErrorAction SilentlyContinue
        }
        if (-not (Test-Path (Join-Path $KimodoPkg "model\hash_text_encoder.py"))) {
            Copy-Item -Path (Join-Path $AddonsSrc "model\hash_text_encoder.py") -Destination (Join-Path $KimodoPkg "model\hash_text_encoder.py") -Force -ErrorAction SilentlyContinue
        }
    }

    return $true
}

# ==========================================================
# START KIMODO
# ==========================================================
function Start-Kimodo {
    param([bool]$Offload = $false)

    if (-not (Test-IsInstalled)) {
        Write-Status "Environment not installed. Run the installer first." "ERROR"
        return $false
    }

    Write-Status "Checking and applying patches..." "INFO"
    if (-not (Ensure-PatchesApplied)) {
        Write-Status "Patch was not applied. Model loading may fail." "WARN"
    }

    $activateScript = Join-Path $ScriptPath $EnvName "Scripts\Activate.ps1"
    $kimodoDir = Join-Path $ScriptPath "kimodo"

    Write-Status "Starting Kimodo (mode: $(if ($Offload) { 'OFFLOAD' } else { 'NORMAL' }))" "INFO"
    & $activateScript
    Push-Location $kimodoDir
    python -m kimodo.demo $(if ($Offload) { "--offload" })
    Pop-Location

    return $true
}

# ==========================================================
# MENU AND MAIN LOOP
# ==========================================================
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
    Write-Host "    Kimodo+Cascadeur Portable v2.5.0 by L.'.L.'./Kilo" -ForegroundColor Green
    Write-Host "    Python 3.12 + PyTorch 2.8 CUDA 12.8" -ForegroundColor Cyan
    Write-Host "  ===========================================" -ForegroundColor Cyan
    Write-Host ""
    $installed = Test-IsInstalled
    if ($installed) {
        Write-Host "  1) Start Kimodo Demo" -ForegroundColor Yellow
        Write-Host "  2) Start Cascadeur Backend (LLAMA NF4)" -ForegroundColor Yellow
        Write-Host "  3) Start Cascadeur Backend (LLAMA OFF)" -ForegroundColor Yellow
        Write-Host "  4) Stop Cascadeur Backend" -ForegroundColor Yellow
        Write-Host "  5) Reinstall (wipe and reinstall)" -ForegroundColor Yellow
        Write-Host "  6) Update Repositories (git pull)" -ForegroundColor Yellow
        Write-Host "  7) Install Cascadeur Command" -ForegroundColor Yellow
        Write-Host "  8) Exit" -ForegroundColor Gray
    } else {
        Write-Host "  1) Install Kimodo (first time)" -ForegroundColor Yellow
        Write-Host "  2) Exit" -ForegroundColor Gray
    }
    Write-Host ""
    $choice = Read-Host "Choice"
    return $choice, $installed
}

# ---- Main loop ----
if (-not (Test-Command "git")) {
    Write-Status "Git not found. Install Git and add to PATH." "ERROR"
    Read-Host "Press Enter to exit"
    exit 1
}

# ---- Distribute embedded Python helpers (AIO) ----
Expand-EmbeddedPayload

# ---- CLI dispatch (non-interactive mode) ----
if (-not $Menu) {
    $exitCode = 0
    try {
        if ($Install) {
            Write-Status "CLI: full install..." "INFO"
            Install-Kimodo -Reinstall $false
            if (-not (Test-IsInstalled)) { throw "Installation failed." }
        }
        if ($Reinstall) {
            Write-Status "CLI: reinstall..." "INFO"
            Install-Kimodo -Reinstall $true
            if (-not (Test-IsInstalled)) { throw "Reinstall failed." }
        }
        if ($StartBackend) {
            Write-Status "CLI: starting backend ($StartBackend)..." "INFO"
            Start-CascadeurBackend -Profile $StartBackend
        }
        if ($StopBackend) {
            Write-Status "CLI: stopping backend..." "INFO"
            Stop-CascadeurBackend
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
            Start-Kimodo -Offload $Offload
        }
        if ($InstallCascadeurCommand) {
            $cmdArgs = @{}
            if ($CascadeurRoot) { $cmdArgs.CascadeurRoot = $CascadeurRoot }
            & (Join-Path $ScriptPath "scripts\install_cascadeur_command.ps1") @cmdArgs
        }
    } catch {
        Write-Status "CLI ERROR: $_" "ERROR"
        $exitCode = 1
    }
    exit $exitCode
}

# ---- Interactive menu loop ----
do {
    $choice, $installed = Show-Menu
    switch ($choice) {
        "1" {
            if (-not $installed) {
                Write-Status "Starting installation..." "INFO"
                Install-Kimodo -Reinstall $false
            } else {
                Write-Status "Preparing to launch..." "INFO"
                $offloadChoice = Read-Host "Start with --offload (GPU < 8GB)? (y/n) [n]"
                $offload = ($offloadChoice -eq 'y' -or $offloadChoice -eq 'Y')
                Start-Kimodo -Offload $offload
            }
        }
        "2" {
            if ($installed) {
                Start-CascadeurBackend -Profile "llama"
            } else {
                Write-Status "Exiting." "INFO"
                exit 0
            }
        }
        "3" {
            if ($installed) {
                Start-CascadeurBackend -Profile "fallback"
            } else {
                Write-Status "Invalid choice." "WARN"
            }
        }
        "4" {
            if ($installed) {
                Stop-CascadeurBackend
            } else {
                Write-Status "Invalid choice." "WARN"
            }
        }
        "5" {
            if ($installed) {
                Write-Status "Starting reinstall..." "INFO"
                Install-Kimodo -Reinstall $true
            } else {
                Write-Status "Invalid choice." "WARN"
            }
        }
        "6" {
            if ($installed) {
                Update-Repositories
            } else {
                Write-Status "Invalid choice." "WARN"
            }
        }
        "7" {
            if ($installed) {
                $CmdInstaller = Join-Path $ScriptPath "scripts\install_cascadeur_command.ps1"
                if (Test-Path $CmdInstaller) {
                    & $CmdInstaller
                } else {
                    Write-Status "install_cascadeur_command.ps1 not found." "WARN"
                }
            } else {
                Write-Status "Invalid choice." "WARN"
            }
        }
        "8" {
            Write-Status "Exiting." "INFO"
            exit 0
        }
        default {
            Write-Status "Invalid choice." "WARN"
        }
    }
    if ($choice -ne "8") {
        Write-Host "`nPress any key to return to menu..." -ForegroundColor Gray
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    }
} while ($true)