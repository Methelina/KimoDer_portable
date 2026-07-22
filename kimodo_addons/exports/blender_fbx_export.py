# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run inside Blender to build a SOMA rig+mesh FBX from a Kimodo motion payload."""

from __future__ import annotations

import os
import sys
import traceback

import bpy
import numpy as np
from mathutils import Matrix, Vector


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value if value else default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    return float(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _parse_args() -> tuple[str, str]:
    if "--" not in sys.argv:
        raise SystemExit("Expected arguments after '--': INPUT_PAYLOAD.npz OUTPUT.fbx")
    argv = sys.argv[sys.argv.index("--") + 1 :]
    if len(argv) != 2:
        raise SystemExit("Expected arguments after '--': INPUT_PAYLOAD.npz OUTPUT.fbx")
    return argv[0], argv[1]


def _compute_bone_lengths(heads: np.ndarray, parents: np.ndarray) -> np.ndarray:
    n_joints = heads.shape[0]
    children: list[list[int]] = [[] for _ in range(n_joints)]
    for child_idx, parent_idx in enumerate(parents.tolist()):
        if parent_idx >= 0:
            children[parent_idx].append(child_idx)

    lengths = np.zeros(n_joints, dtype=np.float32)
    for idx in range(n_joints):
        child_ids = children[idx]
        if child_ids:
            distances = np.linalg.norm(heads[child_ids] - heads[idx], axis=1)
            distances = distances[distances > 1e-4]
            if len(distances) > 0:
                lengths[idx] = float(distances.mean())
                continue
        parent_idx = int(parents[idx])
        if parent_idx >= 0:
            lengths[idx] = max(float(np.linalg.norm(heads[idx] - heads[parent_idx]) * 0.33), 0.005)
        else:
            lengths[idx] = 0.1
    lengths = np.clip(lengths, 0.005, None)
    return lengths


def _build_armature(payload) -> bpy.types.Object:
    joint_names = [str(name) for name in payload["joint_names"]]
    parents = payload["joint_parents"].astype(np.int32)
    bind = payload["bind_rig_transform"].astype(np.float32)
    heads = bind[:, :3, 3]
    rotations = bind[:, :3, :3]
    lengths = _compute_bone_lengths(heads, parents)

    arm_data = bpy.data.armatures.new("KimodoArmature")
    arm_obj = bpy.data.objects.new("KimodoArmature", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")

    edit_bones = arm_data.edit_bones
    root_wrapper = edit_bones.new("Root")
    root_wrapper.head = (0.0, 0.0, 0.0)
    root_wrapper.tail = (0.0, 0.1, 0.0)

    created = {}
    for idx, name in enumerate(joint_names):
        bone = edit_bones.new(name)
        head = Vector(heads[idx].tolist())
        y_axis = Vector((rotations[idx] @ np.array([0.0, 1.0, 0.0], dtype=np.float32)).tolist())
        z_axis = Vector((rotations[idx] @ np.array([0.0, 0.0, 1.0], dtype=np.float32)).tolist())
        if y_axis.length < 1e-6:
            y_axis = Vector((0.0, 1.0, 0.0))
        if z_axis.length < 1e-6:
            z_axis = Vector((0.0, 0.0, 1.0))
        y_axis.normalize()
        z_axis.normalize()
        bone.head = head
        bone.tail = head + y_axis * float(lengths[idx])
        bone.align_roll(z_axis)
        created[idx] = bone

    for idx, bone in created.items():
        parent_idx = int(parents[idx])
        bone.parent = root_wrapper if parent_idx < 0 else created[parent_idx]
        bone.use_connect = False

    bpy.ops.object.mode_set(mode="OBJECT")
    return arm_obj


def _create_skinned_mesh(payload, armature_obj: bpy.types.Object) -> bpy.types.Object:
    vertices = payload["bind_vertices"].astype(np.float32)
    faces = payload["faces"].astype(np.int32)
    rig_joint_names = [str(name) for name in payload["rig_joint_names"]]
    lbs_indices = payload["lbs_indices"].astype(np.int32)
    lbs_weights = payload["lbs_weights"].astype(np.float32)

    mesh_data = bpy.data.meshes.new("KimodoSOMAMesh")
    mesh_data.from_pydata(vertices.tolist(), [], faces.tolist())
    mesh_data.update()

    mesh_obj = bpy.data.objects.new("KimodoSOMAMesh", mesh_data)
    bpy.context.scene.collection.objects.link(mesh_obj)

    available_bones = set(armature_obj.data.bones.keys())
    vertex_groups = {}
    for name in rig_joint_names:
        if name in available_bones:
            vertex_groups[name] = mesh_obj.vertex_groups.new(name=name)

    for vertex_idx, (joint_ids, joint_weights) in enumerate(zip(lbs_indices, lbs_weights)):
        for joint_id, weight in zip(joint_ids.tolist(), joint_weights.tolist()):
            if weight <= 0.0:
                continue
            group_name = rig_joint_names[joint_id]
            group = vertex_groups.get(group_name)
            if group is None:
                continue
            group.add([vertex_idx], float(weight), "REPLACE")

    modifier = mesh_obj.modifiers.new(name="Armature", type="ARMATURE")
    modifier.object = armature_obj
    modifier.use_vertex_groups = True
    modifier.use_bone_envelopes = False
    return mesh_obj


def _animate_armature(payload, armature_obj: bpy.types.Object) -> None:
    matrix_basis = payload["matrix_basis"].astype(np.float32)
    root_deltas = payload["root_deltas"].astype(np.float32)
    joint_names = [str(name) for name in payload["joint_names"]]
    fps = float(payload["fps"][0])
    num_frames = int(matrix_basis.shape[0])

    scene = bpy.context.scene
    scene.render.fps = int(round(fps)) if fps > 0 else 30
    scene.frame_start = 1
    scene.frame_end = num_frames

    root_bone = armature_obj.pose.bones["Root"]
    root_bone.rotation_mode = "QUATERNION"
    for name in joint_names:
        armature_obj.pose.bones[name].rotation_mode = "QUATERNION"

    identity_quat = (1.0, 0.0, 0.0, 0.0)
    unit_scale = (1.0, 1.0, 1.0)
    for frame_idx in range(num_frames):
        frame = frame_idx + 1
        scene.frame_set(frame)

        root_bone.location = root_deltas[frame_idx].tolist()
        root_bone.rotation_quaternion = identity_quat
        root_bone.scale = unit_scale
        root_bone.keyframe_insert(data_path="location", frame=frame)
        root_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
        root_bone.keyframe_insert(data_path="scale", frame=frame)

        for joint_idx, name in enumerate(joint_names):
            bone = armature_obj.pose.bones[name]
            loc, rot, _ = Matrix(matrix_basis[frame_idx, joint_idx].tolist()).decompose()
            bone.location = loc
            bone.rotation_quaternion = rot
            bone.scale = unit_scale
            bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
            bone.keyframe_insert(data_path="location", frame=frame)
            bone.keyframe_insert(data_path="scale", frame=frame)


def main() -> int:
    payload_path, fbx_path = _parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(fbx_path)), exist_ok=True)

    payload = np.load(payload_path, allow_pickle=False)
    include_mesh = bool(int(payload["include_mesh"][0])) if "include_mesh" in payload else True

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = _env_float("KIMODO_FBX_SCENE_SCALE_LENGTH", 1.0)
    armature_obj = _build_armature(payload)
    mesh_obj = _create_skinned_mesh(payload, armature_obj) if include_mesh else None
    _animate_armature(payload, armature_obj)

    bpy.ops.object.select_all(action="DESELECT")
    selected_objects = [armature_obj]
    if mesh_obj is not None:
        selected_objects.append(mesh_obj)
    for obj in selected_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature_obj

    bpy.ops.export_scene.fbx(
        filepath=fbx_path,
        use_selection=True,
        object_types={"ARMATURE", "MESH"} if mesh_obj is not None else {"ARMATURE"},
        bake_anim=True,
        add_leaf_bones=False,
        use_armature_deform_only=False,
        axis_forward=_env_str("KIMODO_FBX_AXIS_FORWARD", "-Y"),
        axis_up=_env_str("KIMODO_FBX_AXIS_UP", "Z"),
        global_scale=_env_float("KIMODO_FBX_GLOBAL_SCALE", 1.0),
        apply_unit_scale=_env_bool("KIMODO_FBX_APPLY_UNIT_SCALE", False),
        apply_scale_options="FBX_SCALE_NONE",
        use_space_transform=_env_bool("KIMODO_FBX_USE_SPACE_TRANSFORM", True),
        bake_space_transform=_env_bool("KIMODO_FBX_BAKE_SPACE_TRANSFORM", False),
        primary_bone_axis=_env_str("KIMODO_FBX_PRIMARY_BONE_AXIS", "Y"),
        secondary_bone_axis=_env_str("KIMODO_FBX_SECONDARY_BONE_AXIS", "X"),
        armature_nodetype=_env_str("KIMODO_FBX_ARMATURE_NODETYPE", "ROOT"),
    )
    if not os.path.exists(fbx_path):
        raise RuntimeError("Blender FBX export finished without writing the output file.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise
