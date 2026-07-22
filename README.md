# KimoDer — Kimodo+Cascadeur Portable

One-click portable installer for [Kimodo](https://github.com/NVlabs/kimodo) motion diffusion model with Cascadeur integration. **No Docker, no WSL, no cloud.** Runs entirely from a single folder.

## Quick Start

```powershell
# First time — install everything (~12 GB download)
.\Install_KimoDer-UV.ps1 -Install

# Daily use — GUI control panel
.\Run_KimoDer.ps1
```

## GUI Control Panel

Two-section layout with per-service status indicators:

- **Cascadeur BackEnd** (port 9552) — colored circle indicator (gray=down, yellow=warming, green=ready, blue=busy, red=error), Start/Stop buttons for LLAMA NF4 and LLAMA OFF modes
- **Kimodo Viser** — colored circle indicator (gray=stopped, yellow=loading, green=ready), Start/Stop Viser buttons, Log Folder
- **Live log** — all service output flows to the GUI log area and the console with `[Cascadeur BackEnd]`, `[Kimodo Viser]`, `[GUI]` tags and type symbols (! * + . >)

## CLI Reference

```powershell
.\Install_KimoDer-UV.ps1 -Install              # Non-interactive full install
.\Install_KimoDer-UV.ps1 -Reinstall            # Wipe & reinstall
.\Run_KimoDer.ps1 -StartBackend llama          # Start backend (LLAMA NF4)
.\Run_KimoDer.ps1 -StartBackend fallback       # Start backend (LLAMA OFF)
.\Run_KimoDer.ps1 -StopBackend                 # Stop backend
.\Run_KimoDer.ps1 -CheckBackend                # Health check (JSON output)
.\Run_KimoDer.ps1 -StartDemo                   # Launch web demo
.\Run_KimoDer.ps1 -InstallCascadeurCommand -CascadeurRoot "path"

# Direct backend control:
.\kimodo_env\Scripts\python.exe scripts\backend_ctl.py start --profile llama --watch
.\kimodo_env\Scripts\python.exe scripts\backend_ctl.py start-demo --watch
.\kimodo_env\Scripts\python.exe scripts\backend_ctl.py health --json
.\kimodo_env\Scripts\python.exe scripts\backend_ctl.py stop
```

## Requirements

- Windows 10/11, PowerShell 5.1+
- NVIDIA GPU with 8+ GB VRAM (RTX 3060+)
- Git
- [Cascadeur](https://cascadeur.com/) (optional, for animation roundtrip)

## Cascadeur Integration

1. Install Cascadeur separately
2. From the GUI or CLI: `-InstallCascadeurCommand` (asks for Cascadeur path)
3. Start the backend (GUI button or `-StartBackend`)
4. In Cascadeur: **Animation Scripts → Kimodo Roundtrip**

If you move the Repository folder, rerun `install_cascadeur_command.ps1` from the `scripts/` folder to update paths.

## Structure

```
Repository/
├── Install_KimoDer-UV.ps1         # AIO installer (env + models + hybrid)
├── Run_KimoDer.ps1                # GUI launcher / runtime CLI
├── _hf_pycurl_download.py         # HF model downloader (pycurl)
├── _llm2vec_wrapper_template.py
├── bin/uv.exe, bin/uvx.exe        # uv package manager
├── integrations/cascadeur/        # Cascadeur plugin files
├── kimodo_addons/                 # Merged into kimodo/ during install
├── scripts/
│   ├── kimoder_gui.py             # DearPyGui control panel
│   ├── backend_ctl.py             # Backend + demo lifecycle (CLI + module)
│   ├── install_cascadeur_command.ps1  # copies plugin into Cascadeur
│   └── cascadeur_backend_service.py   # HTTP backend (port 9552)
└── tools/io_scene_fbx/            # Blender FBX addon modules (Python-only)
```

## Credits

- Kimodo: [NVIDIA Research](https://research.nvidia.com/labs/sil/projects/kimodo/)
- Portable launcher & Cascadeur integration: Soror L.'.L.'.
