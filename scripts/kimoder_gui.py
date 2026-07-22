"""
KimoDer GUI — DearPyGui control panel for Kimodo+Cascadeur backend.

Start/Stop backend buttons, live status indicator (green/yellow/red),
full backend log tail with colored levels and autoscroll.

Launched by Run_KimoDer.ps1 via kimodo_env python.

Version: 1.0.0
Author:  Kilo
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import backend_ctl as bc

import dearpygui.dearpygui as dpg

LOG_TAG = "log_area"
STATUS_CIRCLE_TAG = "status_circle"
STATUS_TEXT_TAG = "status_text"
INFO_TAG = "backend_info"
VRAM_TAG = "vram_text"
PROGRESS_TAG = "warm_progress"

MAX_LOG_LINES = 3000

_ui_queue = queue.Queue()
_shutdown = threading.Event()
_log_items = []
_log_offset = 0
_state = {
    "ok": False,
    "warming_up": False,
    "busy": False,
    "warmup_error": "",
    "device": "-",
    "text_encoder_profile": "-",
    "loaded_datasets": [],
}
_backend_was_up = False


def log_line(text, color=(190, 190, 190)):
    _ui_queue.put(("log", str(text), color))


def classify_line(line):
    up = line.upper()
    if "TRACEBACK" in up or "ERROR" in up or "EXCEPTION" in up:
        return (235, 110, 110)
    if "WARN" in up:
        return (230, 200, 90)
    if "STATUS:" in up:
        return (120, 220, 250)
    if "PROGRESS:" in up:
        return (130, 230, 140)
    if "OK" in up and ("[" in line or "ready" in line.lower()):
        return (130, 230, 140)
    return (185, 185, 185)


def backend_status_color():
    if _state["warmup_error"]:
        return (230, 70, 70), "ERROR"
    if not _state["ok"]:
        return (110, 110, 110), "DOWN"
    if _state["warming_up"]:
        return (240, 200, 60), "WARMING"
    if _state["busy"]:
        return (90, 160, 250), "BUSY"
    return (80, 210, 100), "READY"


def _append_log_item(text, color):
    global _log_items
    try:
        item = dpg.add_text(text, parent=LOG_TAG, color=color, wrap=0)
        _log_items.append(item)
        if len(_log_items) > MAX_LOG_LINES:
            old = _log_items[: len(_log_items) - MAX_LOG_LINES]
            _log_items = _log_items[len(_log_items) - MAX_LOG_LINES :]
            for o in old:
                if dpg.does_item_exist(o):
                    dpg.delete_item(o)
        if dpg.get_value("autoscroll_chk"):
            dpg.set_y_scroll(LOG_TAG, 1e9)
    except Exception:
        pass


def _apply_state():
    color, label = backend_status_color()
    if dpg.does_item_exist(STATUS_CIRCLE_TAG):
        dpg.configure_item(STATUS_CIRCLE_TAG, fill=color)
    if dpg.does_item_exist(STATUS_TEXT_TAG):
        dpg.set_value(STATUS_TEXT_TAG, label)
        dpg.configure_item(STATUS_TEXT_TAG, color=color)
    if dpg.does_item_exist(INFO_TAG):
        datasets = ", ".join(_state["loaded_datasets"]) or "-"
        dpg.set_value(
            INFO_TAG,
            f"device: {_state['device']}   encoder: {_state['text_encoder_profile']}   datasets: {datasets}",
        )
    running = _state["ok"] or _state["warming_up"]
    for tag in ("btn_start_nf4", "btn_start_off"):
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, enabled=not running)
    if dpg.does_item_exist("btn_stop"):
        dpg.configure_item("btn_stop", enabled=running)


def drain_queue():
    global _state
    for _ in range(200):
        try:
            kind, *payload = _ui_queue.get_nowait()
        except queue.Empty:
            break
        if kind == "log":
            _append_log_item(payload[0], payload[1])
        elif kind == "state":
            _state.update(payload[0])
            _apply_state()
        elif kind == "vram":
            if dpg.does_item_exist(VRAM_TAG):
                dpg.set_value(VRAM_TAG, payload[0])


def _tail_log_worker():
    global _log_offset
    while not _shutdown.is_set():
        try:
            lp = bc.log_path()
            if lp.is_file():
                size = lp.stat().st_size
                if size < _log_offset:
                    _log_offset = 0
                if size > _log_offset:
                    with open(lp, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(_log_offset)
                        chunk = f.read()
                    _log_offset = f.tell()
                    for line in chunk.splitlines():
                        line = line.rstrip()
                        if line:
                            log_line(line, classify_line(line))
        except Exception:
            pass
        _shutdown.wait(0.3)


def _health_worker():
    global _backend_was_up
    while not _shutdown.is_set():
        snap = bc.health()
        if snap and snap.get("ok"):
            _backend_was_up = True
            _ui_queue.put(("state", {
                "ok": True,
                "warming_up": bool(snap.get("warming_up")),
                "busy": bool(snap.get("busy")),
                "warmup_error": snap.get("warmup_error") or "",
                "device": snap.get("device") or "-",
                "text_encoder_profile": snap.get("text_encoder_profile") or "-",
                "loaded_datasets": snap.get("loaded_datasets") or [],
            }))
        else:
            if _backend_was_up:
                log_line("--- backend unreachable ---", (235, 110, 110))
                _backend_was_up = False
            _ui_queue.put(("state", {
                "ok": False,
                "warming_up": False,
                "busy": False,
                "warmup_error": "",
                "device": "-",
                "text_encoder_profile": "-",
                "loaded_datasets": [],
            }))
        _shutdown.wait(1.0)


def _vram_worker():
    while not _shutdown.is_set():
        try:
            out = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used,memory.total,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if out.returncode == 0 and out.stdout.strip():
                used, total, util = [x.strip() for x in out.stdout.strip().split(",")[0:3]]
                _ui_queue.put(("vram", f"VRAM {used}/{total} MiB   GPU {util}%"))
        except Exception:
            pass
        _shutdown.wait(3.0)


def _start_backend(profile):
    def work():
        label = "LLAMA NF4" if profile == "llama" else "LLAMA OFF"
        log_line(f">>> starting backend ({label}) ...", (120, 220, 250))
        rc = bc.start(profile=profile, status_cb=lambda m: log_line(f"STATUS: {m}", (120, 220, 250)))
        if rc == 0:
            log_line(">>> backend is ready.", (130, 230, 140))
        else:
            log_line(">>> backend failed to start.", (235, 110, 110))

    threading.Thread(target=work, daemon=True).start()


def _stop_backend():
    def work():
        log_line(">>> stopping backend ...", (120, 220, 250))
        bc.stop(status_cb=lambda m: log_line(f"STATUS: {m}", (120, 220, 250)))
        log_line(">>> backend stopped.", (230, 200, 90))

    threading.Thread(target=work, daemon=True).start()


def _open_demo():
    def work():
        try:
            kimodo_dir = bc.repo_root() / "kimodo"
            if not kimodo_dir.is_dir():
                log_line("kimodo folder not found.", (235, 110, 110))
                return
            env = bc.build_env("llama")
            flags = 0
            if os.name == "nt":
                flags = (
                    subprocess.CREATE_NO_WINDOW
                    | subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                )
            log_file = open(bc.runtime_dir() / "kimodo-demo.log", "w", encoding="utf-8", errors="replace")
            subprocess.Popen(
                [str(bc.python_exe()), "-m", "kimodo.demo"],
                cwd=str(kimodo_dir),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                close_fds=True,
            )
            log_line("Demo starting on http://127.0.0.1:7860 ...", (130, 230, 140))
            time.sleep(5)
            webbrowser.open("http://127.0.0.1:7860")
        except Exception as exc:
            log_line(f"Demo launch failed: {exc}", (235, 110, 110))

    threading.Thread(target=work, daemon=True).start()


def _open_log_folder():
    try:
        os.startfile(str(bc.runtime_dir()))
    except Exception as exc:
        log_line(f"Cannot open log folder: {exc}", (235, 110, 110))


def _clear_log():
    global _log_items
    for item in _log_items:
        if dpg.does_item_exist(item):
            dpg.delete_item(item)
    _log_items = []


def build_gui():
    dpg.create_context()

    with dpg.theme() as global_theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (24, 26, 30))
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (20, 22, 26))
            dpg.add_theme_color(dpg.mvThemeCol_Button, (45, 60, 90))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (60, 80, 120))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (75, 100, 150))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (35, 38, 45))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (215, 218, 224))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 5)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 8)
    dpg.bind_theme(global_theme)

    with dpg.window(tag="main_window", label="KimoDer Control", no_title_bar=True,
                    no_resize=False, no_collapse=True):
        with dpg.group(horizontal=True):
            with dpg.drawlist(width=26, height=26):
                dpg.draw_circle(center=(13, 13), radius=9, tag=STATUS_CIRCLE_TAG,
                                fill=(110, 110, 110), color=(0, 0, 0, 0))
            dpg.add_text("DOWN", tag=STATUS_TEXT_TAG, color=(110, 110, 110))
            dpg.add_text("|")
            dpg.add_text("device: -", tag=INFO_TAG)
            dpg.add_text("|")
            dpg.add_text("VRAM -", tag=VRAM_TAG)

        dpg.add_separator()

        with dpg.group(horizontal=True):
            dpg.add_button(label="Start Backend (LLAMA NF4)", tag="btn_start_nf4",
                           width=220, height=36,
                           callback=lambda: _start_backend("llama"))
            dpg.add_button(label="Start Backend (LLAMA OFF)", tag="btn_start_off",
                           width=220, height=36,
                           callback=lambda: _start_backend("fallback"))
            dpg.add_button(label="Stop Backend", tag="btn_stop", width=140, height=36,
                           callback=_stop_backend)

        with dpg.group(horizontal=True):
            dpg.add_button(label="Open Web Demo", width=160,
                           callback=_open_demo)
            dpg.add_button(label="Open Log Folder", width=160,
                           callback=_open_log_folder)
            dpg.add_button(label="Clear Log", width=110, callback=_clear_log)
            dpg.add_checkbox(label="Autoscroll", tag="autoscroll_chk", default_value=True)

        dpg.add_separator()
        dpg.add_text("Backend log:", color=(140, 145, 155))

        with dpg.child_window(tag=LOG_TAG, border=True, height=-1,
                              horizontal_scrollbar=True):
            pass

    dpg.create_viewport(title="KimoDer — Kimodo+Cascadeur Control", width=980, height=640)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("main_window", True)


def main():
    if not bc.is_installed():
        print("Environment not installed. Run Install_KimoDer-UV.ps1 -Install first.")
        return 1

    build_gui()

    workers = [
        threading.Thread(target=_tail_log_worker, daemon=True),
        threading.Thread(target=_health_worker, daemon=True),
        threading.Thread(target=_vram_worker, daemon=True),
    ]
    for w in workers:
        w.start()

    log_line("KimoDer GUI ready.", (130, 230, 140))
    log_line(f"Repo root: {bc.repo_root()}", (140, 145, 155))
    log_line(f"Backend log: {bc.log_path()}", (140, 145, 155))

    try:
        while dpg.is_dearpygui_running():
            drain_queue()
            dpg.render_dearpygui_frame()
    finally:
        _shutdown.set()
        dpg.destroy_context()
    return 0


if __name__ == "__main__":
    sys.exit(main())
