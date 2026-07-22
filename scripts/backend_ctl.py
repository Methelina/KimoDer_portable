"""
KimoDer backend control module.

Start/stop/health for cascadeur_backend_service.
Used both as CLI (python backend_ctl.py start|stop|health) and as an
importable module by kimoder_gui.py.

Version: 1.0.1
Author:  Soror L.'.L.'.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOST = "127.0.0.1"
DEFAULT_PORT = 9552


def hidden_flags() -> int:
    if os.name != "nt":
        return 0
    return subprocess.CREATE_NO_WINDOW


def detached_flags() -> int:
    if os.name != "nt":
        return 0
    return (
        subprocess.CREATE_NO_WINDOW
        | subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP
    )


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def runtime_dir() -> Path:
    override = os.environ.get("KIMODO_RUNTIME_DIR")
    if override:
        p = Path(override)
    else:
        temp = os.environ.get("TEMP") or str(Path.home())
        p = Path(temp) / "kimodo-runtime"
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_path() -> Path:
    return runtime_dir() / "cascadeur-kimodo-backend.log"


def pid_path() -> Path:
    return runtime_dir() / "cascadeur-kimodo-backend.pid"


def python_exe() -> Path:
    root = repo_root()
    for candidate in (root / "kimodo_env" / "Scripts" / "python.exe",
                      root / "kimodo_env" / "python.exe"):
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        f"Python not found in {root / 'kimodo_env'}. Run the installer first."
    )


def is_installed() -> bool:
    try:
        python_exe()
        return True
    except RuntimeError:
        return False


def build_env(profile: str = "llama") -> dict:
    env = dict(os.environ)
    root = repo_root()
    cache = root / ".cache"
    hf = cache / "huggingface"

    env["KIMODO_DATA_ROOT"] = str(root)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    env["HF_HOME"] = str(hf)
    env["HUGGINGFACE_HUB_CACHE"] = str(hf / "hub")
    env["HUGGINGFACE_ASSETS_CACHE"] = str(hf / "assets")
    env["TRANSFORMERS_CACHE"] = str(hf / "hub")

    checkpoints = root / "checkpoints"
    if checkpoints.is_dir():
        env["CHECKPOINT_DIR"] = str(checkpoints)

    text_encoders = root / "text-encoders"
    if text_encoders.is_dir():
        env["TEXT_ENCODERS_DIR"] = str(text_encoders)

    kimodo = root / "kimodo"
    if kimodo.is_dir():
        env["PYTHONPATH"] = str(kimodo)

    env["PYTORCH_CUDA_ALLOC_CONF"] = (
        "garbage_collection_threshold:0.8,expandable_segments:True,max_split_size_mb:128"
    )
    env["TEXT_ENCODER_MODE"] = "local"

    rt = runtime_dir()
    env["KIMODO_RUNTIME_DIR"] = str(rt)
    env["TEXT_ENCODER_TMP_FOLDER"] = str(rt / "text-encoder-tmp")
    Path(env["TEXT_ENCODER_TMP_FOLDER"]).mkdir(parents=True, exist_ok=True)

    env["KIMODO_FBX_FAST_ARMATURE"] = "1"
    env["KIMODO_FBX_FAST_ONLY"] = "1"
    env["TQDM_DISABLE"] = "1"
    env["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

    if profile == "fallback":
        env["TEXT_ENCODER"] = "hash"
    else:
        env.pop("TEXT_ENCODER", None)

    return env


def health(port: int = DEFAULT_PORT, timeout: float = 3.0):
    try:
        with urllib.request.urlopen(
            f"http://{HOST}:{port}/health", timeout=timeout
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def current_pid() -> int:
    pidfile = pid_path()
    if not pidfile.exists():
        return 0
    try:
        return int(pidfile.read_text().strip() or "0")
    except Exception:
        return 0


def start(
    profile: str = "llama",
    preload_dataset: str = "RP",
    port: int = DEFAULT_PORT,
    watch_pid: int = 0,
    wait: bool = True,
    timeout: float = 600.0,
    status_cb=None,
) -> int:
    emit = status_cb or (lambda msg: print(f"STATUS: {msg}", flush=True))

    pidfile = pid_path()
    old_pid = current_pid()
    if old_pid and pid_alive(old_pid):
        snap = health(port)
        if snap and snap.get("ok"):
            emit(f"Kimodo backend already running (PID {old_pid}).")
            return 0
        pidfile.unlink(missing_ok=True)

    env = build_env(profile)
    script = Path(__file__).resolve().parent / "cascadeur_backend_service.py"
    if not script.is_file():
        emit(f"Backend script not found: {script}")
        return 1

    args = [
        str(python_exe()),
        str(script),
        "--host", HOST,
        "--port", str(port),
        "--preload-dataset", preload_dataset,
        "--text-encoder-profile", profile,
        "--text-pid-file", "none",
    ]
    if watch_pid:
        args += ["--watch-windows-pid", str(watch_pid)]

    emit("Starting Kimodo backend...")
    log_file = open(log_path(), "w", encoding="utf-8", errors="replace")

    proc = subprocess.Popen(
        args,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=str(repo_root()),
        env=env,
        creationflags=detached_flags(),
        close_fds=True,
    )
    pidfile.write_text(str(proc.pid))
    emit(f"Backend PID {proc.pid}, log {log_path()}")

    if not wait:
        return 0

    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            emit("Backend exited before ready. See log.")
            return 1
        snap = health(port, timeout=3.0)
        if snap and snap.get("ok"):
            emit(f"Kimodo backend ready at http://{HOST}:{port}")
            if status_cb is None:
                print(f"BACKEND_URL: http://{HOST}:{port}/health", flush=True)
            return 0
        time.sleep(0.25)

    emit("Backend did not become ready within timeout.")
    try:
        proc.kill()
    except Exception:
        pass
    return 1


def stop(port: int = DEFAULT_PORT, status_cb=None) -> int:
    emit = status_cb or (lambda msg: print(f"STATUS: {msg}", flush=True))

    try:
        urllib.request.urlopen(
            urllib.request.Request(
                f"http://{HOST}:{port}/shutdown",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            ),
            timeout=5,
        )
        emit("Shutdown request sent.")
    except Exception:
        emit("Backend may already be stopped.")

    pid = current_pid()
    if pid and pid_alive(pid):
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True,
                    timeout=10,
                    creationflags=hidden_flags(),
                )
            else:
                os.kill(pid, 9)
            emit(f"Terminated backend process PID {pid}.")
        except Exception as exc:
            emit(f"Failed to terminate PID {pid}: {exc}")
    pid_path().unlink(missing_ok=True)

    emit("Kimodo backend stopped.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="KimoDer backend control")
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start")
    p_start.add_argument("--profile", choices=["llama", "fallback"], default="llama")
    p_start.add_argument("--preload-dataset", default="RP")
    p_start.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_start.add_argument("--watch-pid", type=int, default=0)
    p_start.add_argument("--no-wait", action="store_true")

    p_stop = sub.add_parser("stop")
    p_stop.add_argument("--port", type=int, default=DEFAULT_PORT)

    p_health = sub.add_parser("health")
    p_health.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_health.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.command == "start":
        return start(
            profile=args.profile,
            preload_dataset=args.preload_dataset,
            port=args.port,
            watch_pid=args.watch_pid,
            wait=not args.no_wait,
        )
    if args.command == "stop":
        return stop(port=args.port)
    if args.command == "health":
        snap = health(port=args.port)
        if args.json:
            print(json.dumps(snap or {"ok": False, "error": "backend unreachable"}))
        else:
            print(json.dumps(snap, indent=2) if snap else "backend unreachable")
        return 0 if (snap and snap.get("ok")) else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
