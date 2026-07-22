# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""FBX export helpers for SOMA motions using a headless Blender bridge."""

from __future__ import annotations

import copy
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Union

import numpy as np
import torch

BLENDER_VERSION = "4.2.12"
BLENDER_DIRNAME = f"blender-{BLENDER_VERSION}-linux-x64"
BLENDER_RELATIVE_PATH = Path("tools") / BLENDER_DIRNAME / "blender"
SKIN_FILE_NAME = "skin_standard.npz"
FAST_ARMATURE_TEMPLATE_RELATIVE_PATH = Path("kimodo") / "assets" / "fbx" / "soma_armature_template_bind.json"
FBX_KTIME = 46186158000
_KIMODO_TO_BLENDER_BASIS = np.array(
    [
        [1.0, 0.0, 0.0],
        [0.0, 0.0, -1.0],
        [0.0, 1.0, 0.0],
    ],
    dtype=np.float32,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _addon_fbx_tools_dir() -> Path:
    return _repo_root() / "tools" / BLENDER_DIRNAME / "4.2" / "scripts" / "addons_core" / "io_scene_fbx"


def _candidate_blender_paths() -> list[Path]:
    candidates: list[Path] = []

    blender_bin = os.environ.get("KIMODO_BLENDER_BIN")
    if blender_bin:
        candidates.append(Path(blender_bin).expanduser())

    data_root = os.environ.get("KIMODO_DATA_ROOT")
    if data_root:
        candidates.append(Path(data_root).expanduser() / BLENDER_RELATIVE_PATH)

    candidates.append(_repo_root() / BLENDER_RELATIVE_PATH)

    which_blender = shutil.which("blender")
    if which_blender:
        candidates.append(Path(which_blender))

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def resolve_blender_binary() -> Path:
    """Locate a Blender executable for headless FBX conversion."""
    for candidate in _candidate_blender_paths():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

    install_script = _repo_root() / "scripts" / "install_blender_for_fbx.sh"
    searched = "\n".join(f"- {path}" for path in _candidate_blender_paths())
    raise FileNotFoundError(
        "FBX export requires Blender.\n"
        f"Searched:\n{searched}\n"
        f"Install it locally with: {install_script}\n"
        "Or set KIMODO_BLENDER_BIN to an existing Blender executable."
    )


def _coerce_batch(name: str, x: torch.Tensor, *, expected_ndim: int) -> torch.Tensor:
    if x.ndim == expected_ndim:
        return x
    if x.ndim == expected_ndim + 1:
        if int(x.shape[0]) != 1:
            raise ValueError(
                f"{name} has batch dimension B={int(x.shape[0])}, but FBX export only supports a single clip (B==1)."
            )
        return x[0]
    raise ValueError(f"{name} must have shape (T, ...) or (1, T, ...); got {tuple(x.shape)}")


def _transform_points_to_blender(points: np.ndarray) -> np.ndarray:
    return points @ _KIMODO_TO_BLENDER_BASIS.T


def _transform_transforms_to_blender(transforms: np.ndarray) -> np.ndarray:
    basis_4 = np.eye(4, dtype=np.float32)
    basis_4[:3, :3] = _KIMODO_TO_BLENDER_BASIS
    basis_4_inv = basis_4.T
    if transforms.ndim == 3:
        return basis_4 @ transforms @ basis_4_inv
    if transforms.ndim == 4:
        return basis_4[None] @ transforms @ basis_4_inv[None]
    raise ValueError(f"Unsupported transform rank for Blender conversion: {transforms.ndim}")


@lru_cache(maxsize=1)
def _fast_armature_template() -> list:
    template_path = _repo_root() / FAST_ARMATURE_TEMPLATE_RELATIVE_PATH
    if not template_path.is_file():
        raise FileNotFoundError(f"Missing fast armature FBX template: {template_path}")
    with template_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _fbx_json_modules():
    addon_dir = _addon_fbx_tools_dir()
    if not addon_dir.is_dir():
        raise FileNotFoundError(f"Missing Blender FBX tool scripts: {addon_dir}")
    addon_dir_str = str(addon_dir)
    if addon_dir_str not in sys.path:
        sys.path.insert(0, addon_dir_str)
    encode_bin = importlib.import_module("encode_bin")
    json2fbx = importlib.import_module("json2fbx")
    return encode_bin, json2fbx


def _find_child(node: list, name: str) -> list:
    for child in node[3]:
        if child[0] == name:
            return child
    raise KeyError(f"Missing FBX JSON child '{name}' under '{node[0]}'")


def _model_property_handles(model_obj: list) -> dict[str, list]:
    props70 = _find_child(model_obj, "Properties70")
    return _properties70_handles(props70)


def _properties70_handles(props70: list) -> dict[str, list]:
    props = {}
    for prop in props70[3]:
        if prop[0] == "P" and prop[1]:
            props[str(prop[1][0])] = prop
    return props


def _set_curve_data(curve_obj: list, times: np.ndarray, values: np.ndarray) -> None:
    curve_children = {child[0]: child for child in curve_obj[3]}
    curve_children["Default"][1] = [float(values[0])]
    curve_children["KeyVer"][1] = [4008]
    curve_children["KeyTime"][1] = [times.astype(np.int64).tolist()]
    curve_children["KeyValueFloat"][1] = [values.astype(np.float32).tolist()]
    curve_children["KeyAttrFlags"][1] = [[24836]]
    curve_children["KeyAttrDataFloat"][1] = [[0.0, 0.0, 9.419963346924634e-30, 0.0]]
    curve_children["KeyAttrRefCount"][1] = [[int(values.shape[0])]]


def _fbx_frame_times(num_frames: int, fps: float) -> np.ndarray:
    if fps <= 0.0:
        fps = 30.0
    frame_indices = np.arange(num_frames, dtype=np.float64)
    return (frame_indices / float(fps) * FBX_KTIME).astype(np.int64)


def _bone_local_bind_transforms(bind_rig_transform: np.ndarray, parents: np.ndarray) -> np.ndarray:
    local_bind = np.repeat(np.eye(4, dtype=np.float32)[None], bind_rig_transform.shape[0], axis=0)
    for joint_idx, parent_idx in enumerate(parents.tolist()):
        parent_bind = np.eye(4, dtype=np.float32) if parent_idx < 0 else bind_rig_transform[parent_idx]
        local_bind[joint_idx] = np.linalg.inv(parent_bind) @ bind_rig_transform[joint_idx]
    return local_bind


def _rotation_xyz_degrees(rot_mats: np.ndarray) -> np.ndarray:
    from scipy.spatial.transform import Rotation

    return Rotation.from_matrix(rot_mats).as_euler("xyz", degrees=True).astype(np.float32)


def _prepare_fast_armature_clip(payload: dict[str, np.ndarray]) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    matrix_basis = payload["matrix_basis"].astype(np.float32)
    root_deltas = payload["root_deltas"].astype(np.float32)
    joint_names = [str(name) for name in payload["joint_names"]]
    parents = payload["joint_parents"].astype(np.int32)
    bind_rig_transform = payload["bind_rig_transform"].astype(np.float32)
    local_bind = _bone_local_bind_transforms(bind_rig_transform, parents)
    num_frames = int(matrix_basis.shape[0])
    ones = np.ones((num_frames, 3), dtype=np.float32)
    zeros = np.zeros((num_frames, 3), dtype=np.float32)

    transforms: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {
        "KimodoArmature": (zeros.copy(), zeros.copy(), ones.copy()),
        "Root": (root_deltas.copy(), zeros.copy(), ones.copy()),
    }
    for joint_idx, joint_name in enumerate(joint_names):
        local_target = local_bind[joint_idx][None] @ matrix_basis[:, joint_idx]
        loc = local_target[:, :3, 3].astype(np.float32)
        rot = _rotation_xyz_degrees(local_target[:, :3, :3])
        transforms[joint_name] = (loc, rot, ones.copy())
    return transforms


def _rewrite_fast_armature_template(payload: dict[str, np.ndarray], fps: float) -> list:
    json_root = copy.deepcopy(_fast_armature_template())
    objects = next(node for node in json_root if node[0] == "Objects")[3]
    connections = next(node for node in json_root if node[0] == "Connections")[3]
    global_settings = next(node for node in json_root if node[0] == "GlobalSettings")
    takes = next(node for node in json_root if node[0] == "Takes")

    model_objs = {obj[1][0]: obj for obj in objects if obj[0] == "Model"}
    curve_objs = {obj[1][0]: obj for obj in objects if obj[0] == "AnimationCurve"}
    model_name_to_id = {obj[1][1].split("::")[0]: obj[1][0] for obj in objects if obj[0] == "Model"}

    curve_node_to_curves: dict[int, dict[str, list]] = {}
    model_property_to_node: dict[tuple[str, str], int] = {}
    for connection in connections:
        props = connection[1]
        if not props or props[0] != "OP":
            continue
        src_id, dst_id = int(props[1]), int(props[2])
        if len(props) >= 4 and props[3] in {"Lcl Translation", "Lcl Rotation", "Lcl Scaling"}:
            model_name = model_objs[dst_id][1][1].split("::")[0]
            model_property_to_node[(model_name, props[3])] = src_id
        elif len(props) >= 4 and props[3] in {"d|X", "d|Y", "d|Z"}:
            curve_node_to_curves.setdefault(dst_id, {})[props[3]] = curve_objs[src_id]

    frame_times = _fbx_frame_times(int(payload["matrix_basis"].shape[0]), fps)
    transforms = _prepare_fast_armature_clip(payload)

    for model_name, (loc, rot, scale) in transforms.items():
        for prop_name, values in (
            ("Lcl Translation", loc),
            ("Lcl Rotation", rot),
            ("Lcl Scaling", scale),
        ):
            curve_node_id = model_property_to_node[(model_name, prop_name)]
            axis_curves = curve_node_to_curves[curve_node_id]
            _set_curve_data(axis_curves["d|X"], frame_times, values[:, 0])
            _set_curve_data(axis_curves["d|Y"], frame_times, values[:, 1])
            _set_curve_data(axis_curves["d|Z"], frame_times, values[:, 2])

    time_stop = int(frame_times[-1]) if len(frame_times) else 0
    take = _find_child(takes, "Take")
    _find_child(take, "LocalTime")[1] = [0, time_stop]
    _find_child(take, "ReferenceTime")[1] = [0, time_stop]
    return json_root


def _motion_to_fbx_bytes_fast_armature(
    local_rot_mats: torch.Tensor,
    root_positions: torch.Tensor,
    *,
    skeleton,
    fps: float,
) -> bytes:
    payload = _prepare_soma_payload(local_rot_mats, root_positions, skeleton=skeleton, include_mesh=False)
    payload["fps"] = np.asarray([float(fps)], dtype=np.float32)
    json_root = _rewrite_fast_armature_template(payload, fps=float(fps))
    encode_bin, json2fbx = _fbx_json_modules()
    with tempfile.TemporaryDirectory(prefix="kimodo-fbx-fast-") as tmpdir:
        fbx_path = Path(tmpdir) / "motion.fbx"
        with encode_bin.FBXElem.enable_multithreading_cm():
            fbx_root, fbx_version = json2fbx.parse_json(json_root)
        encode_bin.write(str(fbx_path), fbx_root, fbx_version)
        return fbx_path.read_bytes()


def _compute_bind_relative_animation(
    bind_rig_transform: np.ndarray,
    posed_global_transform: np.ndarray,
    *,
    parents: np.ndarray,
    root_idx: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Convert absolute joint transforms into Blender pose-bone basis transforms.

    The SOMA skin asset is already in bind pose. Blender therefore needs root motion as a
    translation delta from the bind root position, plus a per-bone ``matrix_basis`` transform
    relative to the bind local transform.
    """

    num_frames, num_joints = posed_global_transform.shape[:2]
    identity_4 = np.eye(4, dtype=np.float32)

    root_bind = bind_rig_transform[root_idx, :3, 3]
    root_deltas = posed_global_transform[:, root_idx, :3, 3] - root_bind[None]

    wrapper_target = np.repeat(identity_4[None], num_frames, axis=0)
    wrapper_target[:, :3, 3] = root_deltas

    matrix_basis = np.repeat(identity_4[None, None], num_frames * num_joints, axis=0).reshape(
        num_frames, num_joints, 4, 4
    )

    for joint_idx, parent_idx in enumerate(parents.tolist()):
        parent_bind = identity_4 if parent_idx < 0 else bind_rig_transform[parent_idx]
        local_bind = np.linalg.inv(parent_bind) @ bind_rig_transform[joint_idx]
        local_bind_inv = np.linalg.inv(local_bind)

        parent_target = wrapper_target if parent_idx < 0 else posed_global_transform[:, parent_idx]
        local_target = np.linalg.inv(parent_target) @ posed_global_transform[:, joint_idx]
        matrix_basis[:, joint_idx] = local_bind_inv[None] @ local_target

    return root_deltas.astype(np.float32), matrix_basis.astype(np.float32)


def _prepare_soma_payload(
    local_rot_mats: torch.Tensor,
    root_positions: torch.Tensor,
    *,
    skeleton,
    include_mesh: bool = True,
) -> dict[str, np.ndarray]:
    local_rot_mats = local_rot_mats.detach()
    root_positions = root_positions.detach()

    if skeleton.name == "somaskel30":
        local_rot_mats = skeleton.to_SOMASkeleton77(local_rot_mats)
        skeleton = skeleton.somaskel77

    local_rot_mats = _coerce_batch("local_rot_mats", local_rot_mats, expected_ndim=4)
    root_positions = _coerce_batch("root_positions", root_positions, expected_ndim=2)
    if int(local_rot_mats.shape[0]) != int(root_positions.shape[0]):
        raise ValueError("local_rot_mats and root_positions must have the same number of frames")

    skin_path = Path(skeleton.folder) / SKIN_FILE_NAME
    if not skin_path.is_file():
        raise FileNotFoundError(f"Missing SOMA skin data for FBX export: {skin_path}")

    skin = np.load(skin_path)
    parents = skeleton.joint_parents.detach().cpu().numpy().astype(np.int32)

    global_rot_mats, posed_joints, _ = skeleton.fk(local_rot_mats, root_positions)
    posed_global_transform = np.repeat(
        np.eye(4, dtype=np.float32)[None, None],
        int(local_rot_mats.shape[0]) * int(local_rot_mats.shape[1]),
        axis=0,
    ).reshape(int(local_rot_mats.shape[0]), int(local_rot_mats.shape[1]), 4, 4)
    posed_global_transform[:, :, :3, :3] = global_rot_mats.detach().cpu().numpy().astype(np.float32)
    posed_global_transform[:, :, :3, 3] = posed_joints.detach().cpu().numpy().astype(np.float32)

    bind_vertices = _transform_points_to_blender(skin["bind_vertices"].astype(np.float32))
    bind_rig_transform = _transform_transforms_to_blender(skin["bind_rig_transform"].astype(np.float32))
    posed_global_transform = _transform_transforms_to_blender(posed_global_transform)

    root_deltas, matrix_basis = _compute_bind_relative_animation(
        bind_rig_transform,
        posed_global_transform,
        parents=parents,
        root_idx=int(skeleton.root_idx),
    )

    payload = {
        "fps": np.asarray([0.0], dtype=np.float32),
        "include_mesh": np.asarray([1 if include_mesh else 0], dtype=np.int32),
        "root_deltas": root_deltas,
        "matrix_basis": matrix_basis,
        "joint_names": np.asarray(list(skeleton.bone_order_names)),
        "joint_parents": parents,
        "bind_rig_transform": bind_rig_transform,
    }
    if include_mesh:
        payload.update(
            {
                "bind_vertices": bind_vertices,
                "faces": skin["faces"].astype(np.int32),
                "lbs_indices": skin["lbs_indices"].astype(np.int32),
                "lbs_weights": skin["lbs_weights"].astype(np.float32),
                "rig_joint_names": skin["rig_joint_names"],
            }
        )
    return payload


def motion_to_fbx_bytes(
    local_rot_mats: torch.Tensor,
    root_positions: torch.Tensor,
    *,
    skeleton,
    fps: float,
    include_mesh: bool = True,
) -> bytes:
    """Convert a SOMA motion clip to FBX bytes.

    Armature-only exports use a fast JSON-template writer and fall back to Blender on failure.
    Mesh-inclusive exports always use the existing headless Blender bridge.
    """
    skeleton_name = getattr(skeleton, "name", "")
    if "somaskel" not in skeleton_name:
        raise ValueError("FBX export is currently supported for SOMA skeletons only.")

    if not include_mesh and os.environ.get("KIMODO_FBX_FAST_ARMATURE", "").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            return _motion_to_fbx_bytes_fast_armature(
                local_rot_mats,
                root_positions,
                skeleton=skeleton,
                fps=fps,
            )
        except Exception:
            if os.environ.get("KIMODO_FBX_FAST_ONLY", "").strip():
                raise

    blender_bin = resolve_blender_binary()
    blender_script = Path(__file__).with_name("blender_fbx_export.py")
    payload = _prepare_soma_payload(
        local_rot_mats,
        root_positions,
        skeleton=skeleton,
        include_mesh=include_mesh,
    )
    payload["fps"] = np.asarray([float(fps)], dtype=np.float32)

    with tempfile.TemporaryDirectory(prefix="kimodo-fbx-") as tmpdir:
        tmpdir_path = Path(tmpdir)
        payload_path = tmpdir_path / "motion_payload.npz"
        fbx_path = tmpdir_path / "motion.fbx"
        np.savez(payload_path, **payload)

        cmd = [
            str(blender_bin),
            "--background",
            "--factory-startup",
            "--python",
            str(blender_script),
            "--",
            str(payload_path),
            str(fbx_path),
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        if result.returncode != 0:
            output = (result.stdout or "").strip()
            raise RuntimeError(f"FBX export failed via Blender.\n{output}")
        if not fbx_path.exists():
            output = (result.stdout or "").strip()
            raise RuntimeError(f"FBX export did not produce an output file.\n{output}")
        return fbx_path.read_bytes()


def save_motion_fbx(
    path: Union[str, Path],
    local_rot_mats: torch.Tensor,
    root_positions: torch.Tensor,
    *,
    skeleton,
    fps: float,
    include_mesh: bool = True,
) -> None:
    """Write local rotations and root positions to an FBX file at the given path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        motion_to_fbx_bytes(
            local_rot_mats,
            root_positions,
            skeleton=skeleton,
            fps=fps,
            include_mesh=include_mesh,
        )
    )
