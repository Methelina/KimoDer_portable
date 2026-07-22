# KimoDer — Kimodo+Cascadeur Portable

Portable Windows installer/launcher for [Kimodo](https://github.com/NVlabs/kimodo) motion diffusion model with Cascadeur integration. **No Docker, no WSL, no cloud.** Runs entirely from a single folder.

## Features

- **One-click install** (`Install_KimoDer-UV.ps1`) — sets up Python 3.12, PyTorch 2.8 CUDA 12.8, all dependencies, LLM2Vec NF4 text encoder, SOMA-RP diffusion model, and Cascadeur hybrid components
- **GUI control panel** (`Run_KimoDer.ps1`) — DearPyGui window: Start/Stop backend buttons, live status indicator, full backend log, VRAM+RAM monitors
- **Web demo** — Gradio interface for interactive motion generation (port 7860)
- **Cascadeur backend** — headless HTTP server (port 9552) for AI-assisted animation roundtrip
- **Two text encoder modes** — LLAMA NF4 (default) or hash fallback (LLAMA OFF, ~0 VRAM)
- **Fully portable** — all caches, models, and environment inside the project folder

## Quick Start

```powershell
# First time — install everything (~12 GB download)
.\Install_KimoDer-UV.ps1 -Install

# Daily use — GUI control panel
.\Run_KimoDer.ps1
```

## GUI Control Panel

Launched by `Run_KimoDer.ps1` (no arguments):

- **Start Backend (LLAMA NF4 / LLAMA OFF)** — spawns the headless backend, waits for readiness
- **Stop Backend** — graceful shutdown via HTTP + taskkill fallback
- **Status indicator** — gray (down) / yellow (warming up) / green (ready) / blue (busy) / red (error)
- **Live log** — colored backend log tail with autoscroll
- **Monitors** — VRAM usage (nvidia-smi), RAM usage, GPU utilization
- **Open Web Demo** — launches Gradio demo and opens the browser
- CLI flags (`-StartBackend`, `-CheckBackend`, ...) keep working for automation

## CLI Reference

```powershell
.\Install_KimoDer-UV.ps1 -Install              # Non-interactive full install
.\Run_KimoDer.ps1 -StartBackend llama           # Start Cascadeur backend (LLAMA NF4)
.\Run_KimoDer.ps1 -StartBackend fallback        # Start Cascadeur backend (LLAMA OFF)
.\Run_KimoDer.ps1 -StopBackend                  # Stop backend
.\Run_KimoDer.ps1 -CheckBackend                 # Health check (JSON output)
.\Run_KimoDer.ps1 -StartDemo                    # Launch web demo
.\Run_KimoDer.ps1 -InstallCascadeurCommand -CascadeurRoot "path"
```

Backend control is also available directly:

```powershell
.\kimodo_env\Scripts\python.exe scripts\backend_ctl.py start --profile llama
.\kimodo_env\Scripts\python.exe scripts\backend_ctl.py health --json
.\kimodo_env\Scripts\python.exe scripts\backend_ctl.py stop
```

## Requirements

- Windows 10/11, PowerShell 5.1 or 7+
- NVIDIA GPU with 8+ GB VRAM (RTX 3060+)
- Git
- [Cascadeur](https://cascadeur.com/) (optional, for animation roundtrip)

## Cascadeur Integration

1. Install Cascadeur separately
2. From the GUI or CLI: `-InstallCascadeurCommand` (asks for Cascadeur path, copies the plugin)
3. Start the backend (GUI button or menu)
4. In Cascadeur: **Animation Scripts → Kimodo Roundtrip**

## Structure

```
Repository/
├── Install_KimoDer-UV.ps1       # AIO installer (env + models + hybrid)
├── Run_KimoDer.ps1              # GUI launcher / runtime CLI
├── _hf_pycurl_download.py       # HF model downloader (pycurl)
├── _llm2vec_wrapper_template.py
├── bin/uv.exe, bin/uvx.exe      # uv package manager
├── integrations/cascadeur/      # Cascadeur plugin (roundtrip script)
├── kimodo_addons/               # Merged into kimodo/ during install
├── scripts/
│   ├── kimoder_gui.py           # DearPyGui control panel
│   ├── backend_ctl.py           # Backend lifecycle core (CLI + module)
│   ├── start_backend.ps1        # shim -> backend_ctl.py (roundtrip compat)
│   ├── stop_backend.ps1         # shim -> backend_ctl.py
│   ├── install_cascadeur_command.ps1  # copies plugin into Cascadeur
│   └── cascadeur_backend_service.py   # HTTP backend (port 9552)
└── tools/io_scene_fbx/          # Blender FBX addon modules
```

## Credits

- Kimodo: [NVIDIA Research](https://research.nvidia.com/labs/sil/projects/kimodo/)
- Portable launcher & Cascadeur integration: Soror L.'.L.'.
