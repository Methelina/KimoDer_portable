# KimoDer — Kimodo+Cascadeur Portable

Portable Windows installer/launcher for [Kimodo](https://github.com/NVlabs/kimodo) motion diffusion model with Cascadeur integration. **No Docker, no WSL, no cloud.** Runs entirely from a single folder.

## Features

- **One-click install** (`Install_KimoDer-UV.ps1`) — sets up Python 3.12, PyTorch 2.8 CUDA 12.8, all dependencies, LLM2Vec NF4 text encoder, and Cascadeur hybrid components
- **Web demo** — Gradio interface for interactive motion generation (port 7860)
- **Cascadeur backend** — headless HTTP server (port 9552) for AI-assisted animation roundtrip
- **Two text encoder modes** — LLAMA NF4 (default) or hash fallback (LLAMA OFF, ~0 VRAM)
- **Fully portable** — all caches, models, and environment inside the project folder

## Quick Start

```powershell
# First time — install everything (~12 GB download)
.\Install_KimoDer-UV.ps1 -Install

# Daily use — runtime menu
.\Run_KimoDer.ps1
```

## CLI Reference

```powershell
.\Install_KimoDer-UV.ps1 -Install              # Non-interactive full install
.\Install_KimoDer-UV.ps1 -StartBackend llama    # Start Cascadeur backend (LLAMA NF4)
.\Install_KimoDer-UV.ps1 -StartBackend fallback  # Start Cascadeur backend (LLAMA OFF)
.\Install_KimoDer-UV.ps1 -StopBackend            # Stop backend
.\Install_KimoDer-UV.ps1 -CheckBackend           # Health check (JSON output)
.\Install_KimoDer-UV.ps1 -StartDemo [-Offload]   # Launch web demo
.\Install_KimoDer-UV.ps1 -InstallCascadeurCommand -CascadeurRoot "path"
```

## Requirements

- Windows 10/11, PowerShell 5.1 or 7+
- NVIDIA GPU with 8+ GB VRAM (RTX 3060+)
- Git
- [Cascadeur](https://cascadeur.com/) (optional, for animation roundtrip)

## Cascadeur Integration

1. Install Cascadeur separately
2. Run `.\Install_KimoDer-UV.ps1` → menu 7 (or `-InstallCascadeurCommand`)
3. Start backend → menu 2
4. In Cascadeur: **Animation Scripts → Kimodo Roundtrip**

## Structure

```
Repository/
├── Install_KimoDer-UV.ps1     # AIO installer + launcher
├── Run_KimoDer.ps1            # Daily runtime launcher
├── _hf_pycurl_download.py     # HF model downloader (pycurl)
├── _llm2vec_wrapper_template.py
├── bin/uv.exe, bin/uvx.exe    # uv package manager
├── install_cascadeur_command.ps1
├── integrations/cascadeur/    # Cascadeur plugin (roundtrip script)
├── kimodo_addons/             # Merged into kimodo/ during install
├── scripts/                   # Backend service + launchers
│   ├── cascadeur_backend_service.py
│   ├── start_backend.ps1
│   └── stop_backend.ps1
└── tools/io_scene_fbx/        # Blender FBX addon modules
```

## Credits

- Kimodo: [NVIDIA Research](https://research.nvidia.com/labs/sil/projects/kimodo/)
- Original portable launcher: Soror L.'.L.'.
- Cascadeur hybrid integration: Kilo
