#!/usr/bin/env python3

import argparse
import gc
import json
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import torch


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)


_KIMODO_API = None


def _safe_print(message):
    try:
        print(message, flush=True)
    except OSError:
        pass


def _kimodo_api():
    global _KIMODO_API
    if _KIMODO_API is None:
        from kimodo import load_model
        from kimodo.constraints import FullBodyConstraintSet
        from kimodo.exports.fbx import save_motion_fbx
        from kimodo.exports.motion_io import save_kimodo_npz
        from kimodo.model.registry import get_model_info, kimodo_short_key_for_skeleton_dataset
        from kimodo.skeleton import SOMASkeleton30
        from kimodo.tools import seed_everything

        _KIMODO_API = {
            "load_model": load_model,
            "FullBodyConstraintSet": FullBodyConstraintSet,
            "save_motion_fbx": save_motion_fbx,
            "save_kimodo_npz": save_kimodo_npz,
            "get_model_info": get_model_info,
            "kimodo_short_key_for_skeleton_dataset": kimodo_short_key_for_skeleton_dataset,
            "SOMASkeleton30": SOMASkeleton30,
            "seed_everything": seed_everything,
        }
    return _KIMODO_API


def parse_args():
    parser = argparse.ArgumentParser(description="Persistent Kimodo backend for Cascadeur.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9552)
    parser.add_argument("--preload-dataset", choices=["RP", "SEED", ""], default="")
    parser.add_argument("--watch-windows-pid", type=int, default=0)
    parser.add_argument("--text-pid-file", default="")
    parser.add_argument(
        "--text-encoder-profile",
        choices=["llama", "llama-8bit", "llama-10gb", "llama-4bit", "fallback"],
        default="llama",
    )
    return parser.parse_args()


def load_constraints(path):
    with np.load(path, allow_pickle=False) as data:
        frame_indices = np.asarray(data["frame_indices"], dtype=np.int64)
        global_positions = np.asarray(data["global_positions"], dtype=np.float32)
        global_rot_mats = np.asarray(data["global_rot_mats"], dtype=np.float32)
        position_offset = np.asarray(data["position_offset"], dtype=np.float32) if "position_offset" in data else np.zeros(3, dtype=np.float32)
    if global_positions.ndim != 3 or global_rot_mats.ndim != 4:
        raise ValueError("Constraint NPZ has unexpected shapes.")
    if global_positions.shape[:2] != global_rot_mats.shape[:2]:
        raise ValueError("Constraint position and rotation arrays do not match.")
    if position_offset.shape != (3,):
        raise ValueError("Constraint NPZ position_offset has unexpected shape.")
    return frame_indices, global_positions, global_rot_mats, position_offset


def select_sample(output_dict, sample_index, num_samples):
    sample_index = max(0, min(sample_index, num_samples - 1))
    single = {}
    for key, value in output_dict.items():
        array = np.asarray(value)
        if array.ndim > 0 and array.shape[0] == num_samples:
            single[key] = array[sample_index]
        else:
            single[key] = array
    return single


def apply_world_position_offset(single, position_offset):
    position_offset = np.asarray(position_offset, dtype=np.float32)
    if not np.any(np.abs(position_offset) > 1e-8):
        return single

    adjusted = dict(single)
    if "root_positions" in adjusted:
        adjusted["root_positions"] = np.asarray(adjusted["root_positions"], dtype=np.float32) + position_offset[None, :]
    if "posed_joints" in adjusted:
        adjusted["posed_joints"] = np.asarray(adjusted["posed_joints"], dtype=np.float32) + position_offset[None, None, :]
    return adjusted


def adapt_constraints_to_model_skeleton(model_skeleton, global_positions, global_rot_mats):
    api = _kimodo_api()
    joint_count = int(global_positions.shape[1])
    if joint_count == model_skeleton.nbjoints:
        return global_positions, global_rot_mats

    if isinstance(model_skeleton, api["SOMASkeleton30"]) and joint_count == 77:
        skel_slice = model_skeleton.get_skel_slice(model_skeleton.somaskel77)
        return global_positions[:, skel_slice], global_rot_mats[:, skel_slice]

    raise RuntimeError(
        f"Constraint joint count {joint_count} does not match model skeleton joint count {model_skeleton.nbjoints}."
    )


def resolve_fbx_skeleton(model_skeleton, local_rot_mats_np):
    joint_count = int(local_rot_mats_np.shape[1])
    if joint_count == int(getattr(model_skeleton, "nbjoints", -1)):
        return model_skeleton

    somaskel77 = getattr(model_skeleton, "somaskel77", None)
    if somaskel77 is not None and joint_count == int(getattr(somaskel77, "nbjoints", -1)):
        return somaskel77

    raise RuntimeError(
        f"Cannot resolve FBX export skeleton for generated motion with {joint_count} joints."
    )


class Job:
    def __init__(self, job_id, payload):
        self.job_id = job_id
        self.payload = payload
        self.status = "queued"
        self.progress = 0
        self.done = False
        self.error = ""
        self.started_at = time.time()
        self.updated_at = self.started_at
        self.log_path = payload.get("log_path", "")
        self._lock = threading.RLock()
        self._log_handle = None
        if self.log_path:
            log_dir = os.path.dirname(self.log_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            self._log_handle = open(self.log_path, "w", encoding="utf-8")

    def close(self):
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def _write_log(self, line):
        if self._log_handle is None:
            return
        self._log_handle.write(line + "\n")
        self._log_handle.flush()

    def emit_status(self, message):
        with self._lock:
            self.status = message
            self.updated_at = time.time()
            self._write_log(f"STATUS: {message}")
        print(f"STATUS: {message}", flush=True)

    def emit_progress(self, index, total):
        percent = 100 if total <= 0 else int((index * 100) / total)
        with self._lock:
            self.progress = percent
            self.status = f"Denoising {index}/{total} ({percent}%)"
            self.updated_at = time.time()
            self._write_log(f"PROGRESS: Denoising {index}/{total} ({percent}%)")
        print(f"PROGRESS: Denoising {index}/{total} ({percent}%)", flush=True)

    def fail(self, message, exc_text=""):
        with self._lock:
            self.error = message if not exc_text else f"{message}\n{exc_text}"
            self.done = True
            self.updated_at = time.time()
            self._write_log(f"ERROR: {self.error}")

    def succeed(self):
        with self._lock:
            self.progress = 100
            self.done = True
            self.updated_at = time.time()

    def snapshot(self):
        with self._lock:
            return {
                "job_id": self.job_id,
                "status": self.status,
                "progress": self.progress,
                "done": self.done,
                "error": self.error,
                "log_path": self.log_path,
                "started_at": self.started_at,
                "updated_at": self.updated_at,
            }


class BackendState:
    def __init__(self, text_pid_file="", watch_windows_pid=0, text_encoder_profile="llama"):
        self.text_pid_file = text_pid_file
        self.watch_windows_pid = int(watch_windows_pid or 0)
        self.text_encoder_profile = text_encoder_profile
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.models = {}
        self.current_job_id = None
        self.jobs = {}
        self.next_job_id = 1
        self.lock = threading.RLock()
        self.shutdown_requested = False
        self.max_completed_jobs = 8
        self.warming_up = False
        self.warmup_dataset = ""
        self.warmup_error = ""
        self._preload_thread = None
        self._model_locks = {}

    def get_or_load_model(self, dataset, emit_status):
        api = _kimodo_api()
        with self.lock:
            cached = self.models.get(dataset)
            model_lock = self._model_locks.setdefault(dataset, threading.Lock())
        if cached is not None:
            return cached

        with model_lock:
            with self.lock:
                cached = self.models.get(dataset)
            if cached is not None:
                return cached

            model_name = api["kimodo_short_key_for_skeleton_dataset"]("SOMA", dataset)
            if not model_name:
                raise RuntimeError(f"Could not resolve Kimodo SOMA model for dataset {dataset}.")

            emit_status(f"Loading Kimodo model for dataset {dataset} on {self.device}...")
            model, resolved_name = api["load_model"](
                model_name,
                device=self.device,
                default_family="Kimodo",
                return_resolved_name=True,
            )
            info = api["get_model_info"](resolved_name)
            emit_status(f"Loaded model: {info.display_name if info is not None else resolved_name}")

            with self.lock:
                self.models[dataset] = (model, resolved_name)
                return self.models[dataset]

    def start_preload(self, dataset):
        dataset = str(dataset or "").strip().upper()
        if not dataset:
            return
        with self.lock:
            if dataset in self.models:
                self.warming_up = False
                self.warmup_dataset = dataset
                self.warmup_error = ""
                return
            if self.warming_up and self.warmup_dataset == dataset:
                return
            self.warming_up = True
            self.warmup_dataset = dataset
            self.warmup_error = ""

        def worker():
            error_text = ""
            try:
                self.get_or_load_model(dataset, lambda message: _safe_print(f"STATUS: {message}"))
            except Exception:
                error_text = traceback.format_exc()
                _safe_print(error_text)
            finally:
                with self.lock:
                    self.warming_up = False
                    self.warmup_error = error_text

        thread = threading.Thread(target=worker, daemon=True)
        with self.lock:
            self._preload_thread = thread
        thread.start()

    def create_job(self, payload):
        with self.lock:
            if self.current_job_id is not None:
                raise RuntimeError("Kimodo backend is busy.")
            if self.warming_up:
                raise RuntimeError("Kimodo backend is still warming up. Wait for model preload to finish.")
            if self.warmup_error:
                raise RuntimeError("Kimodo backend warmup failed. Restart Kimodo and check the backend log.")
            job = Job(self.next_job_id, payload)
            self.jobs[job.job_id] = job
            self.current_job_id = job.job_id
            self.next_job_id += 1
            return job

    def finish_job(self, job_id):
        with self.lock:
            if self.current_job_id == job_id:
                self.current_job_id = None
            self._prune_finished_jobs_locked()

    def _prune_finished_jobs_locked(self):
        finished = [
            (job_id, job.updated_at)
            for job_id, job in self.jobs.items()
            if job.done and job_id != self.current_job_id
        ]
        if len(finished) <= self.max_completed_jobs:
            return
        finished.sort(key=lambda item: item[1], reverse=True)
        keep_ids = {job_id for job_id, _ in finished[: self.max_completed_jobs]}
        for job_id, _ in finished[self.max_completed_jobs :]:
            job = self.jobs.pop(job_id, None)
            if job is not None:
                try:
                    job.close()
                except Exception:
                    pass

    def snapshot(self):
        with self.lock:
            loaded_datasets = sorted(self.models.keys())
            current_job = self.jobs.get(self.current_job_id)
            current_job_snapshot = current_job.snapshot() if current_job is not None else None
            return {
                "ok": True,
                "busy": self.current_job_id is not None,
                "warming_up": self.warming_up,
                "warmup_dataset": self.warmup_dataset,
                "warmup_error": self.warmup_error,
                "current_job": current_job_snapshot,
                "loaded_datasets": loaded_datasets,
                "device": self.device,
                "watch_windows_pid": self.watch_windows_pid,
                "text_encoder_profile": self.text_encoder_profile,
            }

    def shutdown(self):
        self.shutdown_requested = True

    def cleanup_external_processes(self):
        pid_files = [self.text_pid_file] if self.text_pid_file else []
        for pid_file in pid_files:
            try:
                if not pid_file or not os.path.exists(pid_file):
                    continue
                with open(pid_file, "r", encoding="utf-8") as handle:
                    pid_text = handle.read().strip()
                if not pid_text:
                    continue
                pid = int(pid_text)
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            except Exception:
                pass


def build_progress_bar(job):
    state = {"last_percent": -1}

    def progress_bar(iterable):
        total = len(iterable)
        if total <= 0:
            for item in iterable:
                yield item
            return
        for index, item in enumerate(iterable, 1):
            percent = int((index * 100) / total)
            if percent != state["last_percent"]:
                state["last_percent"] = percent
                job.emit_progress(index, total)
            yield item

    return progress_bar


def emit_memory_snapshot(job, label):
    if not torch.cuda.is_available():
        return
    try:
        allocated = torch.cuda.memory_allocated()
        reserved = torch.cuda.memory_reserved()
        max_allocated = torch.cuda.max_memory_allocated()
        max_reserved = torch.cuda.max_memory_reserved()
        job.emit_status(
            f"{label} | CUDA allocated={allocated // (1024 * 1024)}MB "
            f"reserved={reserved // (1024 * 1024)}MB "
            f"max_allocated={max_allocated // (1024 * 1024)}MB "
            f"max_reserved={max_reserved // (1024 * 1024)}MB"
        )
    except Exception:
        pass


def run_generation_job(state, job):
    api = _kimodo_api()
    payload = job.payload
    frame_indices = None
    global_positions = None
    global_rot_mats = None
    position_offset = None
    constraint = None
    output = None
    single = None
    local_rot_mats_np = None
    root_positions_np = None
    try:
        if torch.cuda.is_available():
            try:
                torch.cuda.reset_peak_memory_stats()
            except Exception:
                pass
        emit_memory_snapshot(job, "Before job")
        frame_indices, global_positions, global_rot_mats, position_offset = load_constraints(payload["constraints"])

        metadata = {
            "constraints": payload["constraints"],
            "output": payload.get("output", ""),
            "output_fbx": payload["output_fbx"],
            "prompt": payload["prompt"],
            "num_frames": payload["num_frames"],
            "num_samples": payload["num_samples"],
            "sample_index": payload["sample_index"],
            "diffusion_steps": payload["diffusion_steps"],
            "dataset": payload["dataset"],
            "seed": payload["seed"],
            "cfg_enabled": payload["cfg_enabled"],
            "text_weight": payload["text_weight"],
            "constraint_weight": payload["constraint_weight"],
            "constraint_frames": frame_indices.tolist(),
            "position_offset": position_offset.tolist(),
        }
        job._write_log(json.dumps(metadata, indent=2))

        if payload["seed"] is not None:
            api["seed_everything"](payload["seed"])

        model, resolved_name = state.get_or_load_model(payload["dataset"], job.emit_status)
        info = api["get_model_info"](resolved_name)
        if info is not None:
            job.emit_status(f"Using model: {info.display_name}")

        job.emit_status("Building full-pose constraints...")
        global_positions, global_rot_mats = adapt_constraints_to_model_skeleton(
            model.skeleton, global_positions, global_rot_mats
        )
        constraint = api["FullBodyConstraintSet"](
            model.skeleton,
            torch.from_numpy(frame_indices).long().to(state.device),
            torch.from_numpy(global_positions).to(device=state.device, dtype=torch.float32),
            torch.from_numpy(global_rot_mats).to(device=state.device, dtype=torch.float32),
        )

        cfg_kwargs = {"cfg_type": "nocfg"}
        if payload["cfg_enabled"]:
            cfg_kwargs = {
                "cfg_type": "separated",
                "cfg_weight": [float(payload["text_weight"]), float(payload["constraint_weight"])],
            }

        job.emit_status(f"Starting generation for {payload['num_frames']} frames...")
        with torch.inference_mode():
            output = model(
                payload["prompt"],
                int(payload["num_frames"]),
                constraint_lst=[constraint],
                num_denoising_steps=int(payload["diffusion_steps"]),
                num_samples=int(payload["num_samples"]),
                multi_prompt=False,
                post_processing=True,
                return_numpy=True,
                progress_bar=build_progress_bar(job),
                **cfg_kwargs,
            )

        job.emit_status("Selecting requested sample...")
        single = select_sample(output, int(payload["sample_index"]), int(payload["num_samples"]))
        single = apply_world_position_offset(single, position_offset)

        output_path = (payload.get("output") or "").strip()
        if output_path in {"", ".", "./"}:
            output_path = ""
        if output_path:
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            job.emit_status("Saving generated motion...")
            api["save_kimodo_npz"](output_path, single)
            job.emit_status(f"Wrote generated motion to {output_path}")

        if payload["output_fbx"]:
            output_fbx_dir = os.path.dirname(payload["output_fbx"])
            if output_fbx_dir:
                os.makedirs(output_fbx_dir, exist_ok=True)
            job.emit_status("Saving generated FBX...")
            local_rot_mats_np = np.asarray(single["local_rot_mats"], dtype=np.float32)
            root_positions_np = np.asarray(single["root_positions"], dtype=np.float32)
            api["save_motion_fbx"](
                payload["output_fbx"],
                torch.from_numpy(local_rot_mats_np),
                torch.from_numpy(root_positions_np),
                skeleton=resolve_fbx_skeleton(model.skeleton, local_rot_mats_np),
                fps=30.0,
                include_mesh=False,
            )
            job.emit_status(f"Wrote generated FBX to {payload['output_fbx']}")

        emit_memory_snapshot(job, "After job")
        job.succeed()
    except Exception as exc:
        job.fail(str(exc), traceback.format_exc())
    finally:
        del frame_indices
        del global_positions
        del global_rot_mats
        del position_offset
        del constraint
        del output
        del single
        del local_rot_mats_np
        del root_positions_np
        gc.collect()
        if torch.cuda.is_available():
            try:
                torch.cuda.synchronize()
            except Exception:
                pass
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
            try:
                torch.cuda.ipc_collect()
            except Exception:
                pass
        job.close()
        state.finish_job(job.job_id)


def windows_pid_exists(pid):
    if pid <= 0:
        return True
    try:
        completed = subprocess.run(
            ["cmd.exe", "/c", "tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return True
    output = (completed.stdout or "").strip()
    if not output:
        return False
    lowered = output.lower()
    if "no tasks are running" in lowered:
        return False
    return f'"{pid}"' in output


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "KimodoCascadeurBackend/1.0"

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _write_json(self, status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._write_json(HTTPStatus.OK, self.server.backend_state.snapshot())
            return
        if self.path.startswith("/jobs/"):
            job_id_text = self.path.split("/")[-1]
            try:
                job_id = int(job_id_text)
            except ValueError:
                self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Invalid job id"})
                return
            job = self.server.backend_state.jobs.get(job_id)
            if job is None:
                self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown job"})
                return
            self._write_json(HTTPStatus.OK, {"ok": True, "job": job.snapshot()})
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown endpoint"})

    def do_POST(self):
        if self.path == "/generate":
            try:
                payload = self._read_json()
                required = [
                    "constraints",
                    "output_fbx",
                    "prompt",
                    "num_frames",
                    "num_samples",
                    "sample_index",
                    "diffusion_steps",
                    "dataset",
                    "seed",
                    "cfg_enabled",
                    "text_weight",
                    "constraint_weight",
                    "log_path",
                ]
                missing = [key for key in required if key not in payload]
                if missing:
                    raise RuntimeError("Missing fields: " + ", ".join(missing))
                job = self.server.backend_state.create_job(payload)
                worker = threading.Thread(
                    target=run_generation_job,
                    args=(self.server.backend_state, job),
                    daemon=True,
                )
                worker.start()
                self._write_json(HTTPStatus.OK, {"ok": True, "job_id": job.job_id})
                return
            except RuntimeError as exc:
                self._write_json(HTTPStatus.CONFLICT, {"ok": False, "error": str(exc)})
                return
            except Exception as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
                return

        if self.path == "/shutdown":
            self._write_json(HTTPStatus.OK, {"ok": True})
            self.server.backend_state.shutdown()
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown endpoint"})

    def log_message(self, format, *args):
        return


def main():
    args = parse_args()
    state = BackendState(
        text_pid_file=args.text_pid_file,
        watch_windows_pid=args.watch_windows_pid,
        text_encoder_profile=args.text_encoder_profile,
    )

    server = ThreadingHTTPServer((args.host, args.port), RequestHandler)
    server.backend_state = state

    def shutdown_handler(signum, frame):
        state.shutdown()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    if state.watch_windows_pid > 0:
        def parent_watchdog():
            while not state.shutdown_requested:
                if not windows_pid_exists(state.watch_windows_pid):
                    print("STATUS: Cascadeur parent process exited. Stopping Kimodo backend.", flush=True)
                    state.shutdown()
                    state.cleanup_external_processes()
                    os._exit(0)
                time.sleep(5)

        threading.Thread(target=parent_watchdog, daemon=True).start()

    if args.preload_dataset:
        state.start_preload(args.preload_dataset)

    print(json.dumps({
        "status": "ready",
        "host": args.host,
        "port": args.port,
        "watch_windows_pid": args.watch_windows_pid,
        "text_encoder_profile": args.text_encoder_profile,
        "loaded_datasets": sorted(state.models.keys()),
        "warming_up": state.warming_up,
        "warmup_dataset": state.warmup_dataset,
    }), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        state.shutdown()
        state.cleanup_external_processes()
        server.server_close()


if __name__ == "__main__":
    main()
