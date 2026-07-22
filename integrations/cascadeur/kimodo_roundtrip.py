import configparser
import json
import os
import re
import shlex
import subprocess
import time
import traceback
import uuid
import urllib.error
import urllib.request

import csc
import numpy as np
import common.selection_operations as so
import rig_mode.off as rm_off
from pycsc import data_constants as c_dc


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "kimodo_roundtrip.ini")
RUNTIME_CONFIG_DIR = os.path.join(os.path.expandvars(r"%APPDATA%"), "KimodoCascadeur")
RUNTIME_CONFIG_PATH = os.path.join(RUNTIME_CONFIG_DIR, "kimodo_roundtrip.ini")
KIMODO_INSPECTOR_PORT = 7861
KIMODO_BACKEND_PORT = 9552
KIMODO_BACKEND_URL = f"http://127.0.0.1:{KIMODO_BACKEND_PORT}"
LLAMA_10GB_GPU_MEMORY_GB = "6"
_NATIVE_MODE_CACHE = None


def _native_mode(config=None):
    global _NATIVE_MODE_CACHE
    if _NATIVE_MODE_CACHE is not None and config is None:
        return _NATIVE_MODE_CACHE
    if config is None:
        config = _ensure_config()
    mode = (config.get("paths", "backend_mode", fallback="wsl") or "wsl").strip().lower()
    _NATIVE_MODE_CACHE = mode in {"native", "1", "true", "yes", "on", "direct"}
    return _NATIVE_MODE_CACHE
SESSION_TEMP_SCENES = {
    "input": None,
    "output": None,
}
DIAGNOSTIC_SKIP_FINAL_PASTE = False
CASCADEUR_TO_KIMODO_ROT_BASIS = np.asarray(
    [
        [1.0, 0.0, 0.0],
        [0.0, 0.0, -1.0],
        [0.0, 1.0, 0.0],
    ],
    dtype=np.float32,
)
SOMA_JOINT_NAMES = [
    "Hips",
    "Spine1",
    "Spine2",
    "Chest",
    "Neck1",
    "Neck2",
    "Head",
    "HeadEnd",
    "Jaw",
    "LeftEye",
    "RightEye",
    "LeftShoulder",
    "LeftArm",
    "LeftForeArm",
    "LeftHand",
    "LeftHandThumb1",
    "LeftHandThumb2",
    "LeftHandThumb3",
    "LeftHandThumbEnd",
    "LeftHandIndex1",
    "LeftHandIndex2",
    "LeftHandIndex3",
    "LeftHandIndex4",
    "LeftHandIndexEnd",
    "LeftHandMiddle1",
    "LeftHandMiddle2",
    "LeftHandMiddle3",
    "LeftHandMiddle4",
    "LeftHandMiddleEnd",
    "LeftHandRing1",
    "LeftHandRing2",
    "LeftHandRing3",
    "LeftHandRing4",
    "LeftHandRingEnd",
    "LeftHandPinky1",
    "LeftHandPinky2",
    "LeftHandPinky3",
    "LeftHandPinky4",
    "LeftHandPinkyEnd",
    "RightShoulder",
    "RightArm",
    "RightForeArm",
    "RightHand",
    "RightHandThumb1",
    "RightHandThumb2",
    "RightHandThumb3",
    "RightHandThumbEnd",
    "RightHandIndex1",
    "RightHandIndex2",
    "RightHandIndex3",
    "RightHandIndex4",
    "RightHandIndexEnd",
    "RightHandMiddle1",
    "RightHandMiddle2",
    "RightHandMiddle3",
    "RightHandMiddle4",
    "RightHandMiddleEnd",
    "RightHandRing1",
    "RightHandRing2",
    "RightHandRing3",
    "RightHandRing4",
    "RightHandRingEnd",
    "RightHandPinky1",
    "RightHandPinky2",
    "RightHandPinky3",
    "RightHandPinky4",
    "RightHandPinkyEnd",
    "LeftLeg",
    "LeftShin",
    "LeftFoot",
    "LeftToeBase",
    "LeftToeEnd",
    "RightLeg",
    "RightShin",
    "RightFoot",
    "RightToeBase",
    "RightToeEnd",
]
FINGER_NAME_TOKENS = ("Thumb", "Index", "Middle", "Ring", "Pinky")


def command_name():
    return "Animation Scripts.Kimodo Roundtrip"


def command_description():
    return "Roundtrip blocked keyframes through Kimodo headlessly and paste the baked result back"


def _default_config():
    return {
        "paths": {
            "kimodo_root": "",
            "cascadeur_root": r"C:\Program Files\Cascadeur",
            "kimodo_scene": r"C:\Program Files\Cascadeur\samples\Kimodo.casc",
            "wsl_exe": r"C:\Windows\System32\wsl.exe",
            "wsl_distro": "auto",
            "backend_mode": "native",
            "python_exe": r"kimodo_env\Scripts\python.exe",
            "backend_scripts_dir": "scripts",
            "workspace_root": r"%TEMP%\KimodoCascadeur",
        },
        "defaults": {
            "prompt": "",
            "samples_num": "1",
            "sample_index": "0",
            "seed": "-1",
            "denoising_steps": "100",
            "cfg_enabled": "True",
            "text_weight": "2.0",
            "constraint_weight": "2.0",
            "dataset": "RP",
            "keep_debug_scenes": "False",
            "inspect_in_gui": "False",
        },
    }


def _expand_win_path(path_value):
    value = str(path_value or "").replace("\x00", "").strip().strip('"')
    if not value:
        return ""
    value = os.path.expandvars(value)
    value = os.path.expanduser(value)
    return os.path.normpath(value)


def _ensure_config():
    # Keep Windows env vars like %TEMP% as raw text; we expand them ourselves later.
    parser = configparser.ConfigParser(interpolation=None)
    defaults = _default_config()
    parser.read_dict(defaults)
    changed = False

    if os.path.exists(CONFIG_PATH):
        parser.read(CONFIG_PATH)

    runtime_parser = configparser.ConfigParser(interpolation=None)
    runtime_parser.read_dict(defaults)
    if os.path.exists(RUNTIME_CONFIG_PATH):
        runtime_parser.read(RUNTIME_CONFIG_PATH)
    else:
        changed = True

    for section, values in defaults.items():
        if not parser.has_section(section):
            parser.add_section(section)
            changed = True
        for key, value in values.items():
            if not parser.has_option(section, key):
                parser.set(section, key, value)
                changed = True

    # Runtime config is user preference storage only. It must not override
    # install-time path settings such as kimodo_root, wsl_exe, or wsl_distro.
    if runtime_parser.has_section("defaults"):
        for key, value in runtime_parser.items("defaults"):
            parser.set("defaults", key, str(value).replace("\x00", ""))

    if changed:
        os.makedirs(RUNTIME_CONFIG_DIR, exist_ok=True)
        with open(RUNTIME_CONFIG_PATH, "w", encoding="utf-8") as handle:
            parser.write(handle)

    return parser


def _persist_defaults(parser, settings):
    parser.set("defaults", "prompt", settings["prompt"])
    parser.set("defaults", "samples_num", str(settings["samples_num"]))
    parser.set("defaults", "sample_index", str(settings["sample_index"]))
    parser.set("defaults", "seed", "-1" if settings["seed"] is None else str(settings["seed"]))
    parser.set("defaults", "denoising_steps", str(settings["denoising_steps"]))
    parser.set("defaults", "cfg_enabled", "True" if settings["cfg_enabled"] else "False")
    parser.set("defaults", "text_weight", str(settings["text_weight"]))
    parser.set("defaults", "constraint_weight", str(settings["constraint_weight"]))
    parser.set("defaults", "dataset", settings["dataset"])
    parser.set("defaults", "keep_debug_scenes", "False")
    parser.set("defaults", "inspect_in_gui", "False")
    os.makedirs(RUNTIME_CONFIG_DIR, exist_ok=True)
    with open(RUNTIME_CONFIG_PATH, "w", encoding="utf-8") as handle:
        parser.write(handle)


def _to_wsl_path(win_path):
    if _native_mode():
        return _expand_win_path(win_path)
    normalized = _expand_win_path(win_path).replace("\\", "/")
    match = re.match(r"^([A-Za-z]):/(.*)$", normalized)
    if match:
        return f"/mnt/{match.group(1).lower()}/{match.group(2)}"
    return normalized


def _parse_bool(value, default=False):
    if value is None:
        return default
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _parse_seed(value):
    raw = str(value).strip()
    if raw == "":
        return None
    seed = int(raw)
    return None if seed < 0 else seed


def _status_reporter(scene):
    class Reporter:
        def __init__(self, scene_ref):
            self._scene = scene_ref
            self._status_manager = None
            self._status_handle = None
            self._informer = None

        def _set_text(self, text):
            if self._informer is not None and hasattr(self._informer, "set_text"):
                try:
                    self._informer.set_text(text)
                except Exception:
                    pass

        def _set_progress_value(self, percent):
            if self._informer is None:
                return
            candidates = [
                "set_progress",
                "set_percent",
                "set_percentage",
                "set_value",
            ]
            for name in candidates:
                setter = getattr(self._informer, name, None)
                if callable(setter):
                    try:
                        setter(percent)
                        return
                    except Exception:
                        pass

        def update(self, text):
            try:
                self._scene.info(text)
            except Exception:
                pass
            self._set_text(text)

        def progress(self, text):
            try:
                self._scene.info(text)
            except Exception:
                pass
            self._set_text(text)
            match = re.search(r"(\d+)\s*%", str(text))
            if match:
                self._set_progress_value(int(match.group(1)))

        def close(self):
            return

    return Reporter(scene)


def _get_interval(scene):
    dv = scene.model_viewer().data_viewer()
    last_frame = max(0, dv.get_animation_size() - 1)
    try:
        frames_interval = scene.get_layers_selector().selection().frames_interval()
        valid = getattr(frames_interval, "valid", None)
        if callable(valid) and valid():
            start = int(frames_interval.first)
            end = int(frames_interval.last)
            if end >= start:
                return start, end
    except Exception:
        pass
    return 0, last_frame


def _collect_source_constraint_frames(scene, first_frame, last_frame, layer_ids=None):
    lv = scene.layers_viewer()
    ls = scene.get_layers_selector()
    candidate_layer_ids = list(layer_ids) if layer_ids is not None else []
    if not candidate_layer_ids:
        try:
            candidate_layer_ids = list(ls.all_included_layer_ids())
        except Exception:
            candidate_layer_ids = []
    if not candidate_layer_ids:
        candidate_layer_ids = list(lv.all_layer_ids())

    keyframes = set()
    for layer_id in candidate_layer_ids:
        try:
            layer = lv.layer(layer_id)
        except Exception:
            continue
        keyframes.update(frame for frame in layer.key_frame_indices() if first_frame <= frame <= last_frame)

    if keyframes:
        return sorted(keyframes)
    if first_frame == last_frame:
        return [first_frame]
    return [first_frame, last_frame]


def _ordered_unique(items):
    seen = set()
    ordered = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _resolve_single_rig(scene, label, rig_owner=None):
    bv = scene.model_viewer().behaviour_viewer()
    if rig_owner is not None and hasattr(rig_owner, "is_null") and not rig_owner.is_null():
        rig_info = bv.get_behaviour_by_name(rig_owner, "RigInfo")
        if rig_info.is_null():
            raise RuntimeError(f"Could not resolve the selected rigged character in the {label} scene.")
        return rig_info

    rig_infos = list(bv.get_behaviours("RigInfo"))
    if not rig_infos:
        raise RuntimeError(f"Could not find a rigged character in the {label} scene.")

    selected_rig_owners = [obj_id for obj_id in so.get_rig_info(scene) if hasattr(obj_id, "is_null") and not obj_id.is_null()]
    if len(rig_infos) == 1:
        return rig_infos[0]
    if len(selected_rig_owners) != 1:
        raise RuntimeError(
            f"The {label} scene has multiple rigged characters. Select one object that belongs to the intended character."
        )

    rig_info = bv.get_behaviour_by_name(selected_rig_owners[0], "RigInfo")
    if rig_info.is_null():
        raise RuntimeError(f"Could not resolve the selected rigged character in the {label} scene.")
    return rig_info


def _get_rig_context(scene, label, rig_owner=None):
    mv = scene.model_viewer()
    bv = mv.behaviour_viewer()
    lv = scene.layers_viewer()

    rig_info = _resolve_single_rig(scene, label, rig_owner=rig_owner)
    rig_owner = bv.get_behaviour_owner(rig_info)
    joint_ids = _ordered_unique(bv.get_behaviour_objects_range(rig_info, "related_joints"))
    rig_object_ids = list(bv.get_behaviour_objects_range(rig_info, "rig_objects"))

    objects_container = bv.get_behaviour_by_name(rig_owner, "ObjectsContainer")
    if not objects_container.is_null():
        rig_object_ids.extend(bv.get_behaviour_objects_range(objects_container, "ids"))

    rig_object_ids = _ordered_unique([rig_owner] + rig_object_ids + joint_ids)
    joint_layer_ids = _ordered_unique(
        layer_id for layer_id in (lv.layer_id_by_obj_id(obj_id) for obj_id in joint_ids) if not layer_id.is_null()
    )
    rig_layer_ids = _ordered_unique(
        layer_id for layer_id in (lv.layer_id_by_obj_id(obj_id) for obj_id in rig_object_ids) if not layer_id.is_null()
    )

    if not joint_ids or not joint_layer_ids:
        raise RuntimeError(f"Could not resolve the joint animation layers for the {label} scene.")
    if not rig_layer_ids:
        raise RuntimeError(f"Could not resolve the rig animation layers for the {label} scene.")

    return {
        "rig_info": rig_info,
        "rig_owner": rig_owner,
        "joint_ids": joint_ids,
        "joint_layer_ids": joint_layer_ids,
        "rig_object_ids": rig_object_ids,
        "rig_layer_ids": rig_layer_ids,
        "primary_joint_id": joint_ids[0],
        "primary_object_id": rig_owner if hasattr(rig_owner, "is_null") and not rig_owner.is_null() else joint_ids[0],
    }


def _object_id_sort_key(obj_id):
    to_string = getattr(obj_id, "to_string", None)
    if callable(to_string):
        try:
            return to_string()
        except Exception:
            pass
    return str(obj_id)


def _get_selected_autoposing_rig_owners(scene):
    selector = scene.selector()
    mv = scene.model_viewer()
    bv = mv.behaviour_viewer()
    frame_index = scene.get_current_frame()
    selected_tool_ids = {
        sid
        for sid in selector.selected().ids
        if isinstance(sid, csc.domain.Tool_object_id)
    }
    if not selected_tool_ids:
        return []

    rig_owners = []
    try:
        ids_by_procs = csc.domain.get_all_visible_ids_by_proc(scene, selected_tool_ids, frame_index)
    except Exception:
        ids_by_procs = []

    find_rig = getattr(csc.domain, "find_actual_rig_info_id", None)
    if not callable(find_rig):
        return []

    for tool_ids in ids_by_procs or []:
        if not tool_ids:
            continue
        try:
            first = next(iter(tool_ids))
        except StopIteration:
            continue
        try:
            rig_info = find_rig(scene, {first})
        except Exception:
            continue
        if rig_info is None or getattr(rig_info, "is_null", lambda: True)():
            continue
        try:
            owner = bv.get_behaviour_owner(rig_info)
        except Exception:
            continue
        if owner is not None and hasattr(owner, "is_null") and not owner.is_null():
            rig_owners.append(owner)

    return sorted(_ordered_unique(rig_owners), key=_object_id_sort_key)


def _get_selected_rig_owners(scene):
    object_selected_rig_owners = [
        obj_id
        for obj_id in (so.get_rig_info(scene) or set())
        if obj_id is not None and hasattr(obj_id, "is_null") and not obj_id.is_null()
    ]
    rig_owners = _ordered_unique(object_selected_rig_owners + _get_selected_autoposing_rig_owners(scene))
    return sorted(rig_owners, key=_object_id_sort_key)


def _get_all_rig_owners(scene):
    bv = scene.model_viewer().behaviour_viewer()
    rig_owners = []
    for rig_info in bv.get_behaviours("RigInfo"):
        try:
            owner = bv.get_behaviour_owner(rig_info)
        except Exception:
            continue
        if owner is not None and hasattr(owner, "is_null") and not owner.is_null():
            rig_owners.append(owner)
    return sorted(_ordered_unique(rig_owners), key=_object_id_sort_key)


def _describe_scene_object(scene, obj_id, type_hint="Object"):
    try:
        path_name = csc.model.PathName.get_path_name(obj_id, scene.model_viewer(), type_hint)
        return csc.model.get_path_without_namespace(path_name).name
    except Exception:
        return _object_id_sort_key(obj_id)


def _joint_name_map(scene, joint_ids):
    return {obj_id: _describe_scene_object(scene, obj_id, "Joint") for obj_id in joint_ids}


def _layer_header_name(scene, item_id):
    lv = scene.layers_viewer()
    try:
        header = lv.header(item_id)
        return str(getattr(header, "name", "") or "")
    except Exception:
        return ""


def _find_character_folder_id(scene, rig_layer_ids):
    lv = scene.layers_viewer()
    root_id = lv.root_id()
    ancestor_lists = []
    for layer_id in rig_layer_ids:
        try:
            parents = [parent for parent in lv.all_parent_ids(layer_id) if parent != root_id]
        except Exception:
            continue
        if parents:
            ancestor_lists.append(parents)
    if not ancestor_lists:
        return None

    common = set(ancestor_lists[0])
    for parents in ancestor_lists[1:]:
        common.intersection_update(parents)
    if not common:
        return None

    for candidate in ancestor_lists[0]:
        if candidate in common:
            return candidate
    return None


def _collect_descendant_layer_ids(scene, folder_id):
    lv = scene.layers_viewer()
    descendant_layer_ids = []
    try:
        child_ids = lv.all_child_ids(folder_id)
    except Exception:
        child_ids = []
    for item_id in child_ids:
        try:
            item = lv.item(item_id)
            if item.is_layer():
                descendant_layer_ids.append(item_id)
        except Exception:
            continue
    return _ordered_unique(descendant_layer_ids)


def _layer_path_names(scene, item_id):
    lv = scene.layers_viewer()
    names = []
    try:
        parent_ids = list(lv.all_parent_ids(item_id))
    except Exception:
        parent_ids = []
    for parent_id in reversed(parent_ids):
        name = _layer_header_name(scene, parent_id)
        if name:
            names.append(name)
    own_name = _layer_header_name(scene, item_id)
    if own_name:
        names.append(own_name)
    return names


def _is_finger_timeline_layer(scene, layer_id):
    path_text = " / ".join(_layer_path_names(scene, layer_id)).lower()
    if "fingers" in path_text:
        return True
    return any(token.lower() in path_text for token in FINGER_NAME_TOKENS)


def _remove_frames_from_layers(scene, layer_ids, frames_to_delete):
    layer_ids = list(layer_ids)
    frames_to_delete = sorted({int(frame) for frame in frames_to_delete})
    if not layer_ids or not frames_to_delete:
        return 0

    removed_count = {"count": 0}

    def mod(model, update, sc):
        lv = sc.layers_viewer()
        le = model.layers_editor()
        for layer_id in layer_ids:
            try:
                layer = lv.layer(layer_id)
                existing = {int(frame) for frame in layer.key_frame_indices()}
            except Exception:
                continue
            for frame in frames_to_delete:
                if frame in existing:
                    le.unset_section(frame, layer_id)
                    removed_count["count"] += 1

    scene.modify(command_name(), mod)
    return removed_count["count"]


def _select_interval(scene, first_frame, last_frame, layer_ids=None):
    first_frame = int(first_frame)
    last_frame = int(last_frame)
    if last_frame < first_frame:
        last_frame = first_frame

    def mod(model, update, scene_updater, session):
        take_layers_selector = session.take_layers_selector()
        model_layer_selector = model.layers_selector()
        chosen_layer_ids = list(layer_ids) if layer_ids is not None else list(model_layer_selector.all_included_layer_ids())
        if not chosen_layer_ids:
            raise RuntimeError("No animation layers found in the scene.")
        try:
            frame_indices = csc.layers.index.FramesIndices.from_range(first_frame, last_frame)
            selection = csc.layers.index.IndicesContainer(chosen_layer_ids, frame_indices)
            take_layers_selector.set_full_selection_by_parts(selection)
            return
        except Exception:
            pass
        take_layers_selector.set_full_selection_by_parts(chosen_layer_ids, first_frame, last_frame)

    scene.modify_with_session(command_name(), mod)


def _select_objects(scene, object_ids, primary_object_id):
    chosen_object_ids = list(object_ids)
    if not chosen_object_ids:
        raise RuntimeError("No rig objects found in the scene.")

    def mod(model, update, scene_updater, session):
        session.take_selector().select(set(chosen_object_ids), primary_object_id)

    scene.modify_with_session(command_name(), mod)


def _append_debug_log(path, *lines):
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(str(line) + "\n")


def _append_lifecycle_log(path, *lines):
    if not path:
        return
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(f"{timestamp} {line}\n")


def _ui_settle(delay=0.0):
    return


def _scene_runtime_summary(scene):
    try:
        mv = scene.model_viewer()
        lv = scene.layers_viewer()
        object_count = len(list(mv.get_objects()))
        layer_count = len(list(lv.all_layer_ids()))
        animation_size = int(mv.data_viewer().get_animation_size())
        current_frame = int(scene.get_current_frame())
        return (
            f"objects={object_count}",
            f"layers={layer_count}",
            f"animation_size={animation_size}",
            f"current_frame={current_frame}",
        )
    except Exception as exc:
        return (f"scene_summary_failed={type(exc).__name__}: {exc}",)


def _wait_for_scene_ready(scene, lifecycle_log_path=None, label="scene", timeout=0.0, stable_window=0.0):
    if lifecycle_log_path:
        try:
            _append_lifecycle_log(
                lifecycle_log_path,
                f"{label} wait_disabled :: " + " | ".join(_scene_runtime_summary(scene)),
            )
        except Exception:
            pass
    return


def _object_name(scene, obj_id):
    mv = scene.model_viewer()
    try:
        return mv.get_object_name(obj_id)
    except Exception:
        return str(obj_id)


def _format_frame_values(frames, max_items=24):
    frames = [int(frame) for frame in frames]
    if len(frames) <= max_items:
        return ", ".join(str(frame) for frame in frames)
    head = ", ".join(str(frame) for frame in frames[:max_items])
    return f"{head}, ... ({len(frames)} total)"


def _selected_objects_summary(scene, max_items=20):
    selected = list(so.selected_obj_ids(scene))
    named = [_object_name(scene, obj_id) for obj_id in selected[:max_items]]
    if len(selected) > max_items:
        named.append(f"... ({len(selected)} total)")
    return f"selected_objects={len(selected)} :: " + ", ".join(named)


def _object_list_summary(scene, object_ids, max_items=40):
    object_ids = list(object_ids)
    named = [_object_name(scene, obj_id) for obj_id in object_ids[:max_items]]
    if len(object_ids) > max_items:
        named.append(f"... ({len(object_ids)} total)")
    return f"object_ids={len(object_ids)} :: " + ", ".join(named)


def _layer_list_summary(scene, layer_ids, max_items=40):
    lv = scene.layers_viewer()
    layer_ids = list(layer_ids)
    names = []
    for layer_id in layer_ids[:max_items]:
        try:
            header = lv.header(layer_id)
            names.append(getattr(header, "name", str(layer_id)))
        except Exception:
            names.append(str(layer_id))
    if len(layer_ids) > max_items:
        names.append(f"... ({len(layer_ids)} total)")
    return f"layer_ids={len(layer_ids)} :: " + ", ".join(names)


def _scene_tabs_summary(scene_manager):
    try:
        scenes = list(scene_manager.scenes())
    except Exception as exc:
        return f"scene_tabs=<failed to enumerate: {exc}>"
    names = []
    for scene_view in scenes:
        try:
            names.append(scene_view.name())
        except Exception:
            names.append("<unnamed>")
    return f"scene_tabs={len(scenes)} :: " + ", ".join(names)


def _layer_key_debug_summary(scene, layer_ids, max_layers=16):
    lv = scene.layers_viewer()
    layer_ids = list(layer_ids)
    lines = [f"animation_size={int(scene.model_viewer().data_viewer().get_animation_size())}"]
    for layer_id in layer_ids[:max_layers]:
        try:
            header = lv.header(layer_id)
            layer_name = getattr(header, "name", str(layer_id))
        except Exception:
            layer_name = str(layer_id)
        try:
            keys = [int(frame) for frame in lv.layer(layer_id).key_frame_indices()]
        except Exception as exc:
            lines.append(f"  {layer_name}: <failed to read keys: {exc}>")
            continue
        lines.append(f"  {layer_name}: {len(keys)} keys :: {_format_frame_values(keys)}")
    if len(layer_ids) > max_layers:
        lines.append(f"  ... {len(layer_ids) - max_layers} more layers")
    return lines


def _extend_timeline(scene, required_last_frame):
    current_last_frame = scene.model_viewer().data_viewer().get_animation_size() - 1
    if required_last_frame <= current_last_frame:
        return

    def mod(model, update, scene_updater, session):
        lv = scene.layers_viewer()
        all_layer_ids = list(lv.all_layer_ids())
        if not all_layer_ids:
            return
        le = model.layers_editor()
        le.set_section(csc.layers.layer.Section(), int(required_last_frame) + 1, all_layer_ids[0])
        model.fit_animation_size_by_layers()

    scene.modify_with_session(command_name(), mod)


def _seed_keyframes(scene, layer_ids, frame_indices):
    frames = sorted({int(frame) for frame in frame_indices})
    if not frames:
        return

    _extend_timeline(scene, frames[-1])

    def mod(model, update, scene_updater, session):
        le = model.layers_editor()
        for layer_id in layer_ids:
            for frame in frames:
                le.set_fixed_interpolation_or_key_if_need(layer_id, frame, True)
        le.normalize_sections(scene)

    scene.modify_with_session(command_name(), mod)


def _prepare_full_key_span(scene, layer_ids, first_frame, last_frame):
    frames = range(int(first_frame), int(last_frame) + 1)
    _seed_keyframes(scene, layer_ids, frames)

    def mod(model, update, scene_updater, session):
        le = model.layers_editor()
        for layer_id in layer_ids:
            try:
                le.set_fixed_interpolation_if_need(layer_id, int(first_frame), int(last_frame))
            except Exception:
                continue
        le.normalize_sections(scene)

    scene.modify_with_session(command_name(), mod)


def _scene_all_layer_ids(scene):
    return _ordered_unique(list(scene.layers_viewer().all_layer_ids()))


def _collect_transform_actual_data_ids(scene, object_ids):
    mv = scene.model_viewer()
    bv = mv.behaviour_viewer()
    actuals = set()
    for obj_id in object_ids:
        transform_beh = bv.get_behaviour_by_name(obj_id, "Transform")
        if transform_beh.is_null():
            continue
        for data_name in ("global_position", "global_rotation", "local_position", "local_rotation"):
            try:
                data_id = bv.get_behaviour_data(transform_beh, data_name)
            except Exception:
                continue
            if not data_id.is_null():
                actuals.add(data_id)
    return actuals


def _bake_transform_data_to_fixed_keys(scene, object_ids, first_frame, last_frame):
    actuals = _collect_transform_actual_data_ids(scene, object_ids)
    if not actuals:
        return

    _extend_timeline(scene, last_frame)

    def mod(model, update, scene_updater, session):
        for frame in range(int(first_frame), int(last_frame) + 1):
            model.set_fixed_interpolation_if_need(actuals, frame)
            scene_updater.run_update(actuals, frame)

    scene.modify_update_with_session(command_name(), mod)


def _run_retarget_copy(view_scene, first_frame, last_frame, scene_manager, action_manager, object_ids, layer_ids, primary_object_id):
    scene_manager.set_current_scene(view_scene)
    _ui_settle()
    _select_objects(view_scene.domain_scene(), object_ids, primary_object_id)
    _select_interval(view_scene.domain_scene(), first_frame, last_frame, layer_ids)
    action_manager.call_action("View.Retargeting_Copy")
    _ui_settle()


def _run_retarget_paste(view_scene, first_frame, last_frame, scene_manager, action_manager, object_ids, layer_ids, primary_object_id):
    scene_manager.set_current_scene(view_scene)
    _ui_settle()
    _select_objects(view_scene.domain_scene(), object_ids, primary_object_id)
    _select_interval(view_scene.domain_scene(), first_frame, last_frame, layer_ids)
    action_manager.call_action("View.Retargeting_Paste")
    _ui_settle()


def _run_timeline_fill_keys(view_scene, first_frame, last_frame, scene_manager, action_manager, object_ids, layer_ids, primary_object_id):
    scene_manager.set_current_scene(view_scene)
    _ui_settle()
    _select_objects(view_scene.domain_scene(), object_ids, primary_object_id)
    _select_interval(view_scene.domain_scene(), first_frame, last_frame, layer_ids)
    action_manager.call_action("Timeline.Add|Remove key on Interval")
    action_manager.call_action("Timeline.Fixed.Fixed on selected interval")
    _ui_settle()


def _get_joint_order(scene, rig_joint_ids):
    mv = scene.model_viewer()
    name_to_obj = {}
    for obj_id in rig_joint_ids:
        try:
            path_name = csc.model.PathName.get_path_name(obj_id, mv, "Joint")
            simple_name = csc.model.get_path_without_namespace(path_name).name
            name_to_obj[simple_name] = obj_id
        except Exception:
            continue

    missing = [name for name in SOMA_JOINT_NAMES if name not in name_to_obj]
    if missing:
        raise RuntimeError("Hidden Kimodo scene is missing expected SOMA joints: " + ", ".join(missing[:8]))

    return [name_to_obj[name] for name in SOMA_JOINT_NAMES]


def _get_scene_joint_order(scene, label):
    mv = scene.model_viewer()
    bv = mv.behaviour_viewer()
    name_to_obj = {}
    for joint_beh in bv.get_behaviours("Joint"):
        try:
            obj_id = bv.get_behaviour_owner(joint_beh)
            path_name = csc.model.PathName.get_path_name(obj_id, mv, "Joint")
            simple_name = csc.model.get_path_without_namespace(path_name).name
            name_to_obj[simple_name] = obj_id
        except Exception:
            continue

    missing = [name for name in SOMA_JOINT_NAMES if name not in name_to_obj]
    if missing:
        raise RuntimeError(f"{label} is missing expected SOMA joints: " + ", ".join(missing[:8]))

    return [name_to_obj[name] for name in SOMA_JOINT_NAMES]


def _get_joint_scene_context(scene, label):
    lv = scene.layers_viewer()
    joint_ids = _get_scene_joint_order(scene, label)
    joint_layer_ids = _ordered_unique(
        layer_id for layer_id in (lv.layer_id_by_obj_id(obj_id) for obj_id in joint_ids) if not layer_id.is_null()
    )
    if not joint_layer_ids:
        raise RuntimeError(f"Could not resolve joint animation layers for {label}.")
    return {
        "joint_ids": joint_ids,
        "joint_layer_ids": joint_layer_ids,
        "object_ids": joint_ids,
        "layer_ids": joint_layer_ids,
        "primary_object_id": joint_ids[0],
    }


def _get_transform_data_ids(bv, obj_id):
    transform_beh = bv.get_behaviour_by_name(obj_id, "Transform")
    if transform_beh.is_null():
        raise RuntimeError("Joint is missing Transform behaviour.")

    pos_id = bv.get_behaviour_data(transform_beh, "global_position")
    rot_id = bv.get_behaviour_data(transform_beh, "global_rotation")
    if pos_id.is_null() or rot_id.is_null():
        raise RuntimeError("Joint Transform is missing global transform data.")
    return pos_id, rot_id


def _get_local_transform_data_ids(bv, obj_id):
    transform_beh = bv.get_behaviour_by_name(obj_id, "Transform")
    if transform_beh.is_null():
        raise RuntimeError("Joint is missing Transform behaviour.")

    pos_id = bv.get_behaviour_data(transform_beh, "local_position")
    rot_id = bv.get_behaviour_data(transform_beh, "local_rotation")
    if pos_id.is_null() or rot_id.is_null():
        raise RuntimeError("Joint Transform is missing local transform data.")
    return pos_id, rot_id


def _get_parent_object_id(bv, obj_id):
    basic_beh = bv.get_behaviour_by_name(obj_id, "Basic")
    if basic_beh.is_null():
        return csc.model.ObjectId.null()
    return bv.get_behaviour_object(basic_beh, "parent")


def _project_pelvis_heading_rotation(rotation):
    pelvis_unit_z = rotation.to_quaternion() * c_dc.unit_z_vec3
    pelvis_triangle = csc.math.Triangle(c_dc.zero_vec3, c_dc.unit_y_vec3, pelvis_unit_z)
    return csc.math.basic_transform_from_triangle(pelvis_triangle).rotation


def _write_constraint_npz(


    scene,
    joint_ids,
    source_constraint_frames,
    first_frame,
    output_path,
    position_scale=1.0,
    position_offset=None,
    rotation_post_basis=None,
):
    mv = scene.model_viewer()
    bv = mv.behaviour_viewer()
    dv = mv.data_viewer()

    frame_indices_abs = list(source_constraint_frames)
    frame_indices_rel = np.asarray([frame - first_frame for frame in frame_indices_abs], dtype=np.int64)
    global_positions = np.zeros((len(frame_indices_abs), len(joint_ids), 3), dtype=np.float32)
    global_rot_mats = np.zeros((len(frame_indices_abs), len(joint_ids), 3, 3), dtype=np.float32)

    joint_data_ids = [_get_transform_data_ids(bv, obj_id) for obj_id in joint_ids]
    rotation_post_basis = (
        np.asarray(rotation_post_basis, dtype=np.float32)
        if rotation_post_basis is not None
        else None
    )
    position_offset = (
        np.asarray(position_offset, dtype=np.float32)
        if position_offset is not None
        else np.zeros(3, dtype=np.float32)
    )
    for frame_index, abs_frame in enumerate(frame_indices_abs):
        for joint_index, (pos_id, rot_id) in enumerate(joint_data_ids):
            position = dv.get_data_value(pos_id, abs_frame)
            rotation = dv.get_data_value(rot_id, abs_frame)
            global_positions[frame_index, joint_index] = (
                (np.asarray(position, dtype=np.float32) - position_offset) * float(position_scale)
            )
            rot_mat = np.asarray(rotation.to_rotation_matrix(), dtype=np.float32)
            if rotation_post_basis is not None:
                rot_mat = rot_mat @ rotation_post_basis
            global_rot_mats[frame_index, joint_index] = rot_mat

    np.savez(
        output_path,
        frame_indices=frame_indices_rel,
        global_positions=global_positions,
        global_rot_mats=global_rot_mats,
        position_offset=position_offset * float(position_scale),
    )
    return frame_indices_abs


def _get_global_position_at_frame(scene, obj_id, frame):
    mv = scene.model_viewer()
    bv = mv.behaviour_viewer()
    dv = mv.data_viewer()
    pos_id, _ = _get_transform_data_ids(bv, obj_id)
    return np.asarray(dv.get_data_value(pos_id, int(frame)), dtype=np.float32)


def _get_hierarchy_descendant_ids(scene, root_object_id):
    mv = scene.model_viewer()
    bv = mv.behaviour_viewer()
    children_by_parent = {}
    for obj_id in mv.get_objects():
        try:
            parent_id = _get_parent_object_id(bv, obj_id)
        except Exception:
            continue
        children_by_parent.setdefault(parent_id, []).append(obj_id)

    descendants = []
    stack = list(children_by_parent.get(root_object_id, []))
    seen = set()
    while stack:
        obj_id = stack.pop()
        key = _object_id_sort_key(obj_id)
        if key in seen:
            continue
        seen.add(key)
        descendants.append(obj_id)
        stack.extend(children_by_parent.get(obj_id, []))
    return descendants


def _get_rig_point_ids(scene, rig_owner, rig_object_ids):
    mv = scene.model_viewer()
    bv = mv.behaviour_viewer()
    candidate_ids = list(rig_object_ids)
    if rig_owner is not None and hasattr(rig_owner, "is_null") and not rig_owner.is_null():
        candidate_ids.extend(_get_hierarchy_descendant_ids(scene, rig_owner))

    point_ids = []
    for obj_id in _ordered_unique(candidate_ids):
        try:
            point_beh = bv.get_behaviour_by_name(obj_id, "Point")
        except Exception:
            continue
        if not point_beh.is_null():
            point_ids.append(obj_id)
    return _ordered_unique(point_ids)


def _capture_point_positions(scene, point_ids, frames):
    frame_list = [int(frame) for frame in _ordered_unique(frames)]
    captured = {}

    def mod(model, update, scene_updater, session):
        for obj_id in point_ids:
            try:
                point_node = update.get_object_by_id(obj_id).root_group().node_deep("Position")
            except Exception:
                continue
            if point_node is None:
                continue
            frame_positions = {}
            for frame in frame_list:
                frame_positions[int(frame)] = np.asarray(point_node.value(int(frame)), dtype=np.float32)
            if frame_positions:
                captured[obj_id] = frame_positions

    scene.modify_update_with_session(command_name(), mod)
    return captured


def _build_point_constraint_warp(source_anchor_positions, generated_positions, anchor_frames, start_frame, end_frame):
    anchor_frames = sorted(
        int(frame)
        for frame in _ordered_unique(anchor_frames)
        if int(start_frame) <= int(frame) <= int(end_frame)
    )
    corrected_positions = {}

    for obj_id, generated_frame_positions in generated_positions.items():
        source_frame_positions = source_anchor_positions.get(obj_id)
        if not source_frame_positions:
            continue

        usable_anchor_frames = [
            frame
            for frame in anchor_frames
            if frame in source_frame_positions and frame in generated_frame_positions
        ]
        if not usable_anchor_frames:
            continue

        corrected_frame_positions = {
            frame: np.asarray(source_frame_positions[frame], dtype=np.float32)
            for frame in usable_anchor_frames
        }

        for left_frame, right_frame in zip(usable_anchor_frames, usable_anchor_frames[1:]):
            span = int(right_frame) - int(left_frame)
            if span <= 1:
                continue
            left_delta = (
                np.asarray(source_frame_positions[left_frame], dtype=np.float32)
                - np.asarray(generated_frame_positions[left_frame], dtype=np.float32)
            )
            right_delta = (
                np.asarray(source_frame_positions[right_frame], dtype=np.float32)
                - np.asarray(generated_frame_positions[right_frame], dtype=np.float32)
            )
            for frame in range(int(left_frame) + 1, int(right_frame)):
                generated_position = generated_frame_positions.get(frame)
                if generated_position is None:
                    continue
                alpha = float(frame - int(left_frame)) / float(span)
                interpolated_delta = (1.0 - alpha) * left_delta + alpha * right_delta
                corrected_frame_positions[frame] = (
                    np.asarray(generated_position, dtype=np.float32) + interpolated_delta
                )

        if corrected_frame_positions:
            corrected_positions[obj_id] = corrected_frame_positions

    return corrected_positions


def _apply_point_positions(scene, corrected_positions):
    if not corrected_positions:
        return 0, 0

    frames_to_write = sorted(
        {
            int(frame)
            for frame_positions in corrected_positions.values()
            for frame in frame_positions.keys()
        }
    )
    if not frames_to_write:
        return 0, 0

    point_ids = list(corrected_positions.keys())
    total_writes = {"count": 0}

    def mod(model, update, scene_updater, session):
        lv = scene.layers_viewer()
        le = model.layers_editor()
        point_cache = []

        for obj_id in point_ids:
            try:
                point_node = update.get_object_by_id(obj_id).root_group().node_deep("Position")
            except Exception:
                continue
            if point_node is None:
                continue
            layer_id = lv.layer_id_by_obj_id(obj_id)
            point_cache.append((obj_id, point_node, layer_id))

        for frame in frames_to_write:
            actuals = set()
            for obj_id, point_node, layer_id in point_cache:
                frame_positions = corrected_positions.get(obj_id) or {}
                position = frame_positions.get(frame)
                if position is None:
                    continue
                if not layer_id.is_null():
                    le.set_fixed_interpolation_or_key_if_need(layer_id, frame, True)
                point_node.set_value(np.asarray(position, dtype=np.float32), frame)
                actuals.add(point_node.data_id())
                total_writes["count"] += 1
            if actuals:
                scene_updater.run_update(actuals, frame)

        try:
            le.normalize_sections(scene)
        except Exception:
            pass

    scene.modify_update_with_session(command_name(), mod)
    return len(point_ids), total_writes["count"]


def _run_final_point_constraint_pass(
    scene,
    rig,
    source_constraint_frames,
    source_point_anchor_positions,
    start_frame,
    end_frame,
    reporter,
):
    point_ids = _get_rig_point_ids(scene, rig["rig_owner"], rig["rig_object_ids"])
    if not point_ids:
        return "no point controllers found"

    generated_positions = _capture_point_positions(
        scene,
        point_ids,
        range(int(start_frame), int(end_frame) + 1),
    )
    corrected_positions = _build_point_constraint_warp(
        source_point_anchor_positions,
        generated_positions,
        source_constraint_frames,
        start_frame,
        end_frame,
    )
    if not corrected_positions:
        return "no usable point-controller anchors found"

    reporter.update("Applying final constraint-guided point-controller warp...")
    point_count, write_count = _apply_point_positions(scene, corrected_positions)
    return f"{point_count} point controllers, {write_count} frame writes"


def _resolve_kimodo_model_name(settings):
    return f"Kimodo-SOMA-{settings['dataset']}-v1"


def _open_browser_url(url):
    try:
        os.startfile(url)
        return
    except Exception:
        pass

    try:
        kwargs = {}
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = startupinfo
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(["cmd", "/c", "start", "", url], **kwargs)
    except Exception:
        pass


def _load_scene_into_view(data_source_manager, scene_manager, scene_view, file_path):
    scene_manager.set_current_scene(scene_view)
    _ui_settle()
    try:
        csc.app.ProjectLoader.load_from(file_path, scene_view.domain_scene())
    except Exception as exc:
        raise RuntimeError(f"Failed to load scene into existing tab: {file_path} :: {exc}") from exc
    scene_manager.set_current_scene(scene_view)
    _ui_settle()


def _close_scene_view(data_source_manager, scene_manager, current_view, target_view):
    if target_view is None:
        return
    try:
        if current_view is not None:
            scene_manager.set_current_scene(current_view)
    except Exception:
        pass
    try:
        data_source_manager.close_scene(target_view)
        return
    except Exception:
        pass
    try:
        scene_manager.remove_application_scene(target_view)
    except Exception:
        pass


def _scene_is_open(scene_manager, scene_view):
    if scene_view is None:
        return False
    try:
        return any(existing is scene_view for existing in scene_manager.scenes())
    except Exception:
        return False


def _get_or_create_session_temp_scene(scene_manager, key):
    cached = SESSION_TEMP_SCENES.get(key)
    if _scene_is_open(scene_manager, cached):
        return cached
    scene_view = scene_manager.create_application_scene()
    SESSION_TEMP_SCENES[key] = scene_view
    return scene_view


def _reset_session_temp_scenes(scene_manager, data_source_manager, original_view=None):
    for key in tuple(SESSION_TEMP_SCENES.keys()):
        scene_view = SESSION_TEMP_SCENES.get(key)
        SESSION_TEMP_SCENES[key] = None
        if not _scene_is_open(scene_manager, scene_view):
            continue
        try:
            if original_view is not None and _scene_is_open(scene_manager, original_view):
                scene_manager.set_current_scene(original_view)
        except Exception:
            pass
        try:
            scene_manager.remove_application_scene(scene_view)
            continue
        except Exception:
            pass
        try:
            data_source_manager.close_scene(scene_view)
        except Exception:
            pass


def _popen_kwargs():
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = startupinfo
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def _http_json_request(url, method="GET", payload=None, timeout=60):
    data = None
    headers = {"X-Client-Id": "cascadeur"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read()
            if not raw_body:
                return {}
            return json.loads(raw_body.decode("utf-8"))
    except urllib.error.HTTPError as error:
        raw_body = error.read()
        message = f"HTTP {error.code}"
        if raw_body:
            try:
                payload = json.loads(raw_body.decode("utf-8"))
                message = payload.get("error") or payload.get("message") or message
            except Exception:
                try:
                    message = raw_body.decode("utf-8", errors="replace")
                except Exception:
                    pass
        raise RuntimeError(message) from error
    except urllib.error.URLError as error:
        raise RuntimeError(str(error.reason)) from error


def _resolve_native_python(config):
    kimodo_root = _expand_win_path(config.get("paths", "kimodo_root"))
    python_exe_rel = (config.get("paths", "python_exe") or r"kimodo_env\Scripts\python.exe").strip()
    direct_path = os.path.join(kimodo_root, python_exe_rel)
    if os.path.isfile(direct_path):
        return direct_path
    expanded = _expand_win_path(python_exe_rel)
    if os.path.isfile(expanded):
        return expanded
    raise RuntimeError(
        "Native Python executable not found: check python_exe in kimodo_roundtrip.ini\n"
        f"Tried: {direct_path}\nTried: {expanded}"
    )


def _run_native_script(config, script_name, args, reporter, start_message, failure_message):
    kimodo_root = _expand_win_path(config.get("paths", "kimodo_root"))
    scripts_dir = config.get("paths", "backend_scripts_dir", fallback="scripts") or "scripts"
    script_dir = os.path.join(kimodo_root, _expand_win_path(scripts_dir))
    script_path = os.path.join(script_dir, script_name)
    if not os.path.isfile(script_path):
        candidate_py = os.path.join(script_dir, script_name.replace(".sh", ".py"))
        if os.path.isfile(candidate_py):
            script_path = candidate_py
        else:
            raise RuntimeError(f"Script not found: {script_path}")
    is_ps1 = script_path.lower().endswith(".ps1")
    if is_ps1:
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", script_path,
        ] + [str(arg) for arg in args]
    else:
        python_exe = _resolve_native_python(config)
        cmd = [python_exe, script_path] + [str(arg) for arg in args]
    reporter.update(start_message)
    kwargs = _popen_kwargs()
    process = subprocess.Popen(cmd, **kwargs)
    output_lines = []
    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            output_lines.append(line)
            if not line:
                continue
            if line.startswith("STATUS:"):
                reporter.update(line.split(":", 1)[1].strip())
            elif line.startswith("PROGRESS:"):
                reporter.progress(line.split(":", 1)[1].strip())
    return_code = process.wait()
    if return_code != 0:
        details = "\n".join(output_lines[-40:])
        raise RuntimeError(f"{failure_message}\n{details}".strip())
    return output_lines


def _run_wsl_script(config, script_name, args, reporter, start_message, failure_message):
    if _native_mode(config):
        native_name = script_name.replace(".sh", ".ps1") if script_name.endswith(".sh") else script_name
        return _run_native_script(config, native_name, args, reporter, start_message, failure_message)
    kimodo_root = _expand_win_path(config.get("paths", "kimodo_root"))
    wsl_exe = _expand_win_path(config.get("paths", "wsl_exe"))
    if not os.path.exists(wsl_exe):
        raise RuntimeError(f"WSL executable not found: {wsl_exe}")
    wsl_distro = _detect_wsl_distro(config)
    launcher = _to_wsl_path(os.path.join(kimodo_root, "scripts", script_name))
    bash_args = [shlex.quote(launcher)] + [shlex.quote(str(arg)) for arg in args]
    bash_command = " ".join(bash_args)
    reporter.update(start_message)
    output_lines = []
    wsl_command = [wsl_exe]
    if wsl_distro:
        wsl_command.extend(["-d", wsl_distro])
    wsl_command.extend(["--", "bash", "--noprofile", "--norc", "-c", bash_command])
    process = subprocess.Popen(wsl_command, **_popen_kwargs())
    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            output_lines.append(line)
            if not line:
                continue
            if line.startswith("STATUS:"):
                reporter.update(line.split(":", 1)[1].strip())
            elif line.startswith("PROGRESS:"):
                reporter.progress(line.split(":", 1)[1].strip())
    return_code = process.wait()
    if return_code != 0:
        details = "\n".join(output_lines[-40:])
        raise RuntimeError(f"{failure_message}\n{details}".strip())
    return output_lines


def _probe_wsl_distro(wsl_exe, distro_name):
    kwargs = _popen_kwargs()
    kwargs["stdout"] = subprocess.PIPE
    kwargs["stderr"] = subprocess.PIPE
    try:
        process = subprocess.run(
            [wsl_exe, "-d", distro_name, "--", "bash", "--noprofile", "--norc", "-c", "command -v python3.10 >/dev/null 2>&1"],
            timeout=20,
            **kwargs,
        )
    except Exception:
        return False
    return process.returncode == 0


def _probe_wsl_default(wsl_exe):
    kwargs = _popen_kwargs()
    kwargs["stdout"] = subprocess.PIPE
    kwargs["stderr"] = subprocess.PIPE
    try:
        process = subprocess.run(
            [wsl_exe, "--", "bash", "--noprofile", "--norc", "-c", "command -v python3.10 >/dev/null 2>&1"],
            timeout=20,
            **kwargs,
        )
    except Exception:
        return False
    return process.returncode == 0


def _detect_wsl_distro(config):
    configured = ""
    try:
        configured = _expand_win_path(config.get("paths", "wsl_distro"))
    except Exception:
        configured = ""
    if configured and configured.lower() not in {"auto", "default"}:
        if _probe_wsl_distro(_expand_win_path(config.get("paths", "wsl_exe")), configured):
            return configured
        raise RuntimeError(
            f"Configured WSL distro is not usable for Kimodo: {configured}\n\n"
            "Kimodo requires python3.10 inside WSL.\n"
            "Use Ubuntu-22.04 or set wsl_distro = auto after installing a compatible distro."
        )

    wsl_exe = _expand_win_path(config.get("paths", "wsl_exe"))
    if not os.path.exists(wsl_exe):
        raise RuntimeError(f"WSL executable not found: {wsl_exe}")

    if _probe_wsl_default(wsl_exe):
        return ""

    kwargs = _popen_kwargs()
    kwargs["stdout"] = subprocess.PIPE
    kwargs["stderr"] = subprocess.PIPE
    process = subprocess.run([wsl_exe, "-l", "-q"], **kwargs)
    stdout = process.stdout or ""
    stderr = process.stderr or ""
    combined = "\n".join(part for part in (stdout, stderr) if part).strip()

    distro_names = []
    for raw_line in combined.splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line:
            continue
        lowered = line.lower()
        if lowered in {"docker-desktop", "docker-desktop-data"}:
            continue
        if "windows subsystem for linux has no installed distributions" in lowered:
            continue
        if lowered.startswith("there is no distribution with the supplied name"):
            continue
        if lowered.startswith("error code:"):
            continue
        distro_names.append(line)

    if distro_names:
        for distro_name in distro_names:
            if _probe_wsl_distro(wsl_exe, distro_name):
                return distro_name
        return distro_names[0]

    raise RuntimeError(
        "No compatible WSL distro was found.\n\n"
        "Kimodo requires a WSL distro with python3.10.\n"
        "Install and initialize Ubuntu-22.04, for example:\n"
        "  wsl.exe --install -d Ubuntu-22.04\n\n"
        "Then open Ubuntu-22.04 once, finish first-time setup, rerun Install.bat, and retry."
    )


def _backend_snapshot():
    return _http_json_request(f"{KIMODO_BACKEND_URL}/health", timeout=3)


def _backend_is_running():
    try:
        snapshot = _backend_snapshot()
        return bool(snapshot.get("ok"))
    except Exception:
        return False



def _normalize_text_encoder_mode(value):
    mode = str(value or "llama").strip().lower()
    if mode in {"fallback", "llama-off", "llama_off", "off", "false", "0"}:
        return "fallback"
    if mode in {
        "llama-10gb",
        "llama_10gb",
        "llama (10gb vram)",
        "llama-8bit-lowvram",
        "llama_8bit_lowvram",
        "llama-8bit",
        "llama8",
        "8bit",
        "8-bit",
        "int8",
    }:
        return "llama-10gb"
    if mode in {"llama-4bit", "llama4", "4bit", "4-bit", "int4", "nf4"}:
        return "llama-4bit"
    return "llama"


def _text_encoder_mode_label(value):
    mode = _normalize_text_encoder_mode(value)
    return {
        "fallback": "LLAMA OFF",
        "llama-10gb": "LLAMA (10GB VRAM)",
        "llama-4bit": "LLAMA 4-bit",
        "llama": "LLAMA",
    }[mode]


def _start_kimodo_backend(config, preload_dataset, reporter, text_encoder_mode="llama"):
    if _backend_is_running():
        return _backend_snapshot()

    normalized_mode = _normalize_text_encoder_mode(text_encoder_mode)

    if _native_mode(config):
        profile = "fallback" if normalized_mode == "fallback" else "llama"
        ctl_args = [
            "start",
            "--profile", profile,
            "--preload-dataset", preload_dataset,
            "--port", str(KIMODO_BACKEND_PORT),
        ]
        lines = _run_native_script(
            config,
            "backend_ctl.py",
            ctl_args,
            reporter,
            "Starting Kimodo backend...",
            "Failed to start Kimodo backend.",
        )
        snapshot = _backend_snapshot()
        reporter.update(f"Kimodo backend is ready at {KIMODO_BACKEND_URL} with {_text_encoder_mode_label(normalized_mode)}")
        return snapshot

    llama_enabled = normalized_mode != "fallback"
    llama_quantization = "none"
    llama_max_gpu_memory_gb = ""
    if normalized_mode == "llama-10gb":
        llama_quantization = "8bit"
        llama_max_gpu_memory_gb = LLAMA_10GB_GPU_MEMORY_GB
    elif normalized_mode == "llama-4bit":
        llama_quantization = "4bit"

    lines = _run_wsl_script(
        config,
        "start_cascadeur_backend_service.sh",
        [
            "--preload-dataset",
            preload_dataset,
            "--port",
            str(KIMODO_BACKEND_PORT),
            "--llama-enabled",
            "1" if llama_enabled else "0",
            "--llama-quantization",
            llama_quantization,
            "--llama-max-gpu-memory-gb",
            llama_max_gpu_memory_gb,
        ],
        reporter,
        "Starting Kimodo backend...",
        "Failed to start Kimodo backend.",
    )
    snapshot = _backend_snapshot()
    backend_url = ""
    for line in lines:
        if line.startswith("BACKEND_URL:"):
            backend_url = line.split(":", 1)[1].strip()
            break
    if backend_url:
        reporter.update(f"Kimodo backend is ready at {backend_url}")
    return snapshot


def _stop_kimodo_backend(config, reporter):
    if not _backend_is_running():
        reporter.update("Kimodo backend is already stopped.")
        return

    if _native_mode(config):
        _run_native_script(
            config,
            "backend_ctl.py",
            ["stop", "--port", str(KIMODO_BACKEND_PORT)],
            reporter,
            "Stopping Kimodo backend...",
            "Failed to stop Kimodo backend.",
        )
        reporter.update("Kimodo backend stopped.")
        return

    _run_wsl_script(
        config,
        "stop_cascadeur_backend_service.sh",
        [],
        reporter,
        "Stopping Kimodo backend...",
        "Failed to stop Kimodo backend.",
    )
    reporter.update("Kimodo backend stopped.")


def _run_kimodo_generation(config, settings, constraints_path, output_path, output_fbx_path, log_path, reporter):
    if not _backend_is_running():
        raise RuntimeError("Kimodo is not started. Start Kimodo first.")
    snapshot = _backend_snapshot()
    if snapshot.get("warming_up"):
        raise RuntimeError("Kimodo is still warming up. Wait for model preload to finish.")

    payload = {
        "constraints": _to_wsl_path(constraints_path),
        "output": _to_wsl_path(output_path),
        "output_fbx": _to_wsl_path(output_fbx_path),
        "prompt": settings["prompt"],
        "num_frames": int(settings["num_frames"]),
        "num_samples": int(settings["samples_num"]),
        "sample_index": int(settings["sample_index"]),
        "diffusion_steps": int(settings["denoising_steps"]),
        "dataset": settings["dataset"],
        "seed": settings["seed"],
        "cfg_enabled": bool(settings["cfg_enabled"]),
        "text_weight": float(settings["text_weight"]),
        "constraint_weight": float(settings["constraint_weight"]),
        "log_path": _to_wsl_path(log_path),
    }
    reporter.update(f"Submitting generation job to Kimodo backend... Log: {log_path}")
    response = _http_json_request(f"{KIMODO_BACKEND_URL}/generate", method="POST", payload=payload, timeout=120)
    if not response.get("ok"):
        raise RuntimeError(response.get("error") or "Kimodo backend rejected the generation job.")

    job_id = int(response["job_id"])
    last_status = None
    last_progress = -1
    while True:
        snapshot = _http_json_request(f"{KIMODO_BACKEND_URL}/jobs/{job_id}", timeout=60)
        if not snapshot.get("ok"):
            raise RuntimeError(snapshot.get("error") or "Kimodo backend job lookup failed.")
        job = snapshot.get("job") or {}
        status = str(job.get("status") or "")
        progress = int(job.get("progress") or 0)
        if status and (status != last_status or progress != last_progress):
            if progress > 0:
                reporter.progress(f"{status}")
            else:
                reporter.update(status)
            last_status = status
            last_progress = progress
        if job.get("done"):
            if job.get("error"):
                raise RuntimeError(f"Kimodo headless generation failed. See log: {log_path}")
            break
        time.sleep(0.25)

    reporter.progress("Kimodo generation finished (100%)")


def _launch_kimodo_gui_inspector(
    config,
    settings,
    constraints_path,
    constraints_json_path,
    motion_path,
    log_path,
    reporter,
):
    kimodo_root = _expand_win_path(config.get("paths", "kimodo_root"))
    wsl_exe = _expand_win_path(config.get("paths", "wsl_exe"))
    if not os.path.exists(wsl_exe):
        raise RuntimeError(f"WSL executable not found: {wsl_exe}")

    launcher = _to_wsl_path(os.path.join(kimodo_root, "scripts", "launch_kimodo_constraints_inspector.sh"))
    args = [
        shlex.quote(launcher),
        "--constraints",
        shlex.quote(_to_wsl_path(constraints_path)),
        "--constraints-json",
        shlex.quote(_to_wsl_path(constraints_json_path)),
        "--motion",
        shlex.quote(_to_wsl_path(motion_path)),
        "--prompt",
        shlex.quote(settings["prompt"]),
        "--model",
        shlex.quote(_resolve_kimodo_model_name(settings)),
        "--port",
        str(KIMODO_INSPECTOR_PORT),
        "--log",
        shlex.quote(_to_wsl_path(log_path)),
    ]

    process = subprocess.Popen([wsl_exe, "bash", "-lc", " ".join(args)], **_popen_kwargs())
    inspect_url = f"http://127.0.0.1:{KIMODO_INSPECTOR_PORT}/"
    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if not line:
                continue
            if line.startswith("STATUS:"):
                reporter.update(line.split(":", 1)[1].strip())
            elif line.startswith("INSPECT_URL:"):
                inspect_url = line.split(":", 1)[1].strip()

    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"Kimodo GUI inspector failed to launch. See log: {log_path}")

    _open_browser_url(inspect_url)
    return inspect_url


def _import_generated_fbx_scene(scene_view, fbx_path):
    application = csc.app.get_application()
    tools_manager = application.get_tools_manager()
    fbx_loader = tools_manager.get_tool("FbxSceneLoader").get_fbx_loader(scene_view)
    fbx_loader.import_scene(fbx_path.replace("\\", "/"))


def _import_generated_fbx_animation(
    scene_view,
    fbx_path,
    scene_manager,
    layer_ids,
    debug_log_path,
    reporter,
):
    scene_manager.set_current_scene(scene_view)
    scene = scene_view.domain_scene()
    if debug_log_path:
        _append_debug_log(
            debug_log_path,
            "",
            "=" * 80,
            f"FBX IMPORT DEBUG START {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"fbx_path={fbx_path}",
            f"fbx_exists={os.path.exists(fbx_path)} size_bytes={os.path.getsize(fbx_path) if os.path.exists(fbx_path) else 'missing'}",
            f"scene_animation_size_before={int(scene.model_viewer().data_viewer().get_animation_size())}",
            "selection_before:",
            _selected_objects_summary(scene),
            "layer_keys_before:",
            *_layer_key_debug_summary(scene, layer_ids),
        )

    application = csc.app.get_application()
    tools_manager = application.get_tools_manager()
    fbx_loader = tools_manager.get_tool("FbxSceneLoader").get_fbx_loader(scene_view)
    import_method = "import_animation"
    takes = []
    get_takes = getattr(fbx_loader, "get_takes", None)
    if callable(get_takes):
        try:
            takes = list(get_takes(fbx_path.replace("\\", "/")))
        except Exception as exc:
            takes = [f"<get_takes_failed: {exc}>"]
    try:
        settings = csc.fbx.FbxSettings()
        settings.bake_animation = True
        settings.apply_euler_filter = False
        fbx_loader.set_settings(settings)
        _append_debug_log(
            debug_log_path,
            f"loader_settings_applied: bake_animation={settings.bake_animation}, apply_euler_filter={settings.apply_euler_filter}",
        )
    except Exception:
        _append_debug_log(debug_log_path, "loader_settings_applied: <failed>")
    _append_debug_log(
        debug_log_path,
        f"loader_method={import_method}",
        f"available_takes={takes}",
    )
    reporter.update("Importing generated FBX into the second temporary Kimodo scene...")
    try:
        fbx_loader.import_animation(fbx_path.replace("\\", "/"), 0)
    except TypeError:
        fbx_loader.import_animation(fbx_path.replace("\\", "/"))
    except Exception as exc:
        _append_debug_log(debug_log_path, f"import_exception={type(exc).__name__}: {exc}")
        raise
    _ui_settle()
    if debug_log_path:
        _append_debug_log(
            debug_log_path,
            f"scene_animation_size_after={int(scene.model_viewer().data_viewer().get_animation_size())}",
            "selection_after_import:",
            _selected_objects_summary(scene),
            "layer_keys_after:",
            *_layer_key_debug_summary(scene, layer_ids),
            f"FBX IMPORT DEBUG END {time.strftime('%Y-%m-%d %H:%M:%S')}",
        )


def _collect_keyframes_in_range(scene, layer_ids):
    lv = scene.layers_viewer()
    keyframes = set()
    for layer_id in layer_ids:
        try:
            layer = lv.layer(layer_id)
        except Exception:
            continue
        try:
            keyframes.update(int(frame) for frame in layer.key_frame_indices())
        except Exception:
            continue
    return sorted(keyframes)


def _collect_actual_keyframes_in_interval(scene, layer_ids, first_frame, last_frame):
    return [
        int(frame)
        for frame in _collect_keyframes_in_range(scene, layer_ids)
        if int(first_frame) <= int(frame) <= int(last_frame)
    ]


def _load_generated_npz(output_path):
    with np.load(output_path, allow_pickle=False) as data:
        local_rot_mats = np.asarray(data["local_rot_mats"], dtype=np.float32)
        root_positions = np.asarray(data["root_positions"], dtype=np.float32)
        global_rot_mats = np.asarray(data["global_rot_mats"], dtype=np.float32)
        posed_joints = np.asarray(data["posed_joints"], dtype=np.float32)
    return local_rot_mats, root_positions, global_rot_mats, posed_joints


def _apply_generated_motion(scene, joint_ids, start_frame, local_rot_mats, root_positions, global_rot_mats, posed_joints):
    if local_rot_mats.shape[0] != root_positions.shape[0]:
        raise RuntimeError("Generated motion output has inconsistent frame counts.")
    if local_rot_mats.shape[1] != len(joint_ids):
        raise RuntimeError("Generated motion joint count does not match the hidden Kimodo rig.")
    if global_rot_mats.shape[:2] != local_rot_mats.shape[:2]:
        raise RuntimeError("Generated motion rotation arrays do not match.")
    if posed_joints.shape[:2] != local_rot_mats.shape[:2]:
        raise RuntimeError("Generated motion position arrays do not match.")

    last_frame = start_frame + int(local_rot_mats.shape[0]) - 1

    def mod(model, update, scene_updater, session):
        mv = scene.model_viewer()
        bv = mv.behaviour_viewer()
        lv = scene.layers_viewer()
        le = model.layers_editor()
        de = model.data_editor()
        cached_ids = []
        actuals = set()
        layer_ids = []
        joint_index_by_id = {obj_id: idx for idx, obj_id in enumerate(joint_ids)}
        identity_rot = np.eye(3, dtype=np.float32)
        zero_pos = np.zeros(3, dtype=np.float32)

        for joint_index, obj_id in enumerate(joint_ids):
            local_pos_id, local_rot_id = _get_local_transform_data_ids(bv, obj_id)
            global_pos_id, global_rot_id = _get_transform_data_ids(bv, obj_id)
            parent_obj_id = _get_parent_object_id(bv, obj_id)
            parent_index = joint_index_by_id.get(parent_obj_id, -1)
            layer_id = lv.layer_id_by_obj_id(obj_id)
            cached_ids.append((local_pos_id, local_rot_id, global_pos_id, global_rot_id, layer_id, parent_index))
            actuals.add(local_pos_id)
            actuals.add(local_rot_id)
            actuals.add(global_pos_id)
            actuals.add(global_rot_id)
            if not layer_id.is_null():
                layer_ids.append(layer_id)

        if layer_ids:
            le.set_section(csc.layers.layer.Section(), last_frame + 1, layer_ids[0])
            model.fit_animation_size_by_layers()

        for rel_frame, abs_frame in enumerate(range(start_frame, last_frame + 1)):
            for joint_index, (
                local_pos_id,
                local_rot_id,
                _global_pos_id,
                _global_rot_id,
                layer_id,
                parent_index,
            ) in enumerate(cached_ids):
                if not layer_id.is_null():
                    le.set_fixed_interpolation_or_key_if_need(layer_id, abs_frame, True)

                joint_global_pos = np.asarray(posed_joints[rel_frame, joint_index], dtype=np.float32)
                joint_global_rot = np.asarray(global_rot_mats[rel_frame, joint_index], dtype=np.float32)
                if parent_index < 0:
                    parent_global_pos = zero_pos
                    parent_global_rot = identity_rot
                else:
                    parent_global_pos = np.asarray(posed_joints[rel_frame, parent_index], dtype=np.float32)
                    parent_global_rot = np.asarray(global_rot_mats[rel_frame, parent_index], dtype=np.float32)

                parent_global_rot_inv = parent_global_rot.T
                local_pos = parent_global_rot_inv @ (joint_global_pos - parent_global_pos)
                local_rot = parent_global_rot_inv @ joint_global_rot

                de.set_data_value(local_pos_id, abs_frame, local_pos)
                de.set_data_value(
                    local_rot_id,
                    abs_frame,
                    csc.math.Rotation.from_rotation_matrix(local_rot),
                )
            scene_updater.run_update(actuals, abs_frame)

        if layer_ids:
            le.unset_section(last_frame + 1, layer_ids[0])
            le.normalize_sections(scene)

    scene.modify_update_with_session(command_name(), mod)


def _build_job_dir(config):
    workspace_root = _expand_win_path(config.get("paths", "workspace_root"))
    os.makedirs(workspace_root, exist_ok=True)
    job_name = "kimodo_roundtrip_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    job_dir = os.path.join(workspace_root, job_name)
    os.makedirs(job_dir, exist_ok=True)
    return job_dir


def _write_stage_marker(job_dir, stage_name):
    with open(os.path.join(job_dir, "stage.txt"), "w", encoding="utf-8") as handle:
        handle.write(stage_name + "\n")


def _validate_paths(config):
    missing = []
    required_keys = ("kimodo_root", "cascadeur_root", "kimodo_scene")
    if not _native_mode(config):
        required_keys = required_keys + ("wsl_exe",)
    for key in required_keys:
        value = _expand_win_path(config.get("paths", key))
        if not os.path.exists(value):
            missing.append(f"{key}: {value}")
    if missing:
        raise RuntimeError("Fix kimodo_roundtrip.ini paths first:\n" + "\n".join(missing))


def _parse_settings(values):
    settings = {
        "prompt": str(values[0]).strip(),
        "samples_num": max(1, int(str(values[1]).strip() or "1")),
        "sample_index": max(0, int(str(values[2]).strip() or "0")),
        "seed": _parse_seed(values[3]),
        "denoising_steps": max(1, int(str(values[4]).strip() or "100")),
        "cfg_enabled": _parse_bool(values[5], True),
        "text_weight": float(str(values[6]).strip() or "2.0"),
        "constraint_weight": float(str(values[7]).strip() or "2.0"),
        "dataset": str(values[8]).strip().upper() or "RP",
        "keep_debug_scenes": False,
        "inspect_in_gui": False,
    }
    if settings["dataset"] not in {"RP", "SEED"}:
        raise RuntimeError("Dataset must be RP or SEED.")
    if settings["sample_index"] >= settings["samples_num"]:
        settings["sample_index"] = settings["samples_num"] - 1
    return settings


def _format_frame_list(frames, max_items=12):
    frames = list(frames)
    if len(frames) <= max_items:
        return ", ".join(str(frame) for frame in frames)
    head = ", ".join(str(frame) for frame in frames[:max_items])
    return f"{head}, ... ({len(frames)} total)"


def _normalize_dataset_name(value):
    dataset = str(value or "RP").strip().upper()
    return dataset if dataset in {"RP", "SEED"} else "RP"


def _backend_dialog_text(snapshot, config):
    lines = [
        f"Kimodo root: {_expand_win_path(config.get('paths', 'kimodo_root'))}",
        f"Backend URL: {KIMODO_BACKEND_URL}",
    ]
    if not snapshot:
        lines.append("Status: stopped")
        lines.append("Start Kimodo first. Generate is only available after the backend is running.")
        return "\n".join(lines)

    loaded_datasets = snapshot.get("loaded_datasets") or []
    profile = str(snapshot.get("text_encoder_profile") or "llama").strip().lower()
    if snapshot.get("busy"):
        status_text = "busy"
    elif snapshot.get("warming_up"):
        status_text = "warming up"
    else:
        status_text = "running"
    lines.append(f"Status: {status_text}")
    lines.append(f"Text encoder: {_text_encoder_mode_label(profile)}")
    lines.append(f"Loaded datasets: {', '.join(loaded_datasets) if loaded_datasets else '(none yet)'}")
    current_job = snapshot.get("current_job") or {}
    if snapshot.get("busy") and current_job:
        lines.append(f"Current job: {current_job.get('status', 'running')}")
        lines.append(f"Progress: {int(current_job.get('progress') or 0)}%")
        lines.append("Generate is disabled while Kimodo is busy.")
    elif snapshot.get("warming_up"):
        dataset = snapshot.get("warmup_dataset") or _normalize_dataset_name(config["defaults"].get("dataset", "RP"))
        lines.append(f"Warmup dataset: {dataset}")
        if snapshot.get("warmup_error"):
            lines.append("Warmup failed. Stop and start Kimodo again.")
        else:
            lines.append("Kimodo is preloading in the background. Generate will be enabled when warmup finishes.")
    else:
        lines.append("Generate is available.")
    return "\n".join(lines)


def _show_generate_dialog(scene, config):
    defaults = config["defaults"]
    field_names = [
        "Prompt",
        "Samples num",
        "Sample index",
        "Seed (-1 = random)",
        "Denoising steps",
        "Classifier free guidance [True/False]",
        "Text weight",
        "Constraint weight",
        "Training dataset [RP/SEED]",
    ]
    field_values = [
        defaults.get("prompt", ""),
        defaults.get("samples_num", "1"),
        defaults.get("sample_index", "0"),
        defaults.get("seed", "-1"),
        defaults.get("denoising_steps", "100"),
        defaults.get("cfg_enabled", "True"),
        defaults.get("text_weight", "2.0"),
        defaults.get("constraint_weight", "2.0"),
        _normalize_dataset_name(defaults.get("dataset", "RP")),
    ]

    def callback(input_values):
        reporter = _status_reporter(scene)
        try:
            try:
                snapshot = _backend_snapshot()
            except Exception:
                snapshot = None
            if not snapshot or not snapshot.get("ok"):
                raise RuntimeError("Kimodo is not started. Start Kimodo first.")
            if snapshot.get("busy"):
                raise RuntimeError("Kimodo is busy. Wait for the current job to finish or stop the backend.")
            settings = _parse_settings(input_values)
            _run_roundtrip_for_selected_characters(scene, config, settings, reporter)
        except Exception as error:
            reporter.update("Kimodo roundtrip failed.")
            details = "".join(traceback.format_exception_only(type(error), error)).strip()
            scene.error(details)
            csc.view.DialogManager.instance().show_info("Kimodo Roundtrip Error", details)
        finally:
            reporter.close()

    csc.view.DialogManager.instance().show_inputs_dialog(
        "Kimodo Generate",
        field_names,
        field_values,
        len(field_names),
        callback,
    )


def run_start_backend(scene, text_encoder_mode="llama"):
    config = _ensure_config()
    defaults = config["defaults"]
    reporter = _status_reporter(scene)
    dialog_manager = csc.view.DialogManager.instance()
    try:
        try:
            snapshot = _backend_snapshot()
        except Exception:
            snapshot = None
        if snapshot and snapshot.get("ok"):
            scene.info(f"Kimodo backend is already running at {KIMODO_BACKEND_URL}")
            return
        preload_dataset = _normalize_dataset_name(defaults.get("dataset", "RP"))
        normalized_mode = _normalize_text_encoder_mode(text_encoder_mode)
        snapshot = _start_kimodo_backend(config, preload_dataset, reporter, text_encoder_mode=normalized_mode)
        mode_label = _text_encoder_mode_label(normalized_mode)
        if snapshot.get("warming_up"):
            scene.info(f"Kimodo backend started at {KIMODO_BACKEND_URL} with {mode_label} and is warming up.")
        else:
            scene.info(f"Kimodo backend is ready at {KIMODO_BACKEND_URL} with {mode_label}.")
    except Exception as error:
        reporter.update("Kimodo backend start failed.")
        details = "".join(traceback.format_exception_only(type(error), error)).strip()
        scene.error(details)
        dialog_manager.show_info("Kimodo Backend Error", details)
    finally:
        reporter.close()


def run_stop_backend(scene):
    config = _ensure_config()
    reporter = _status_reporter(scene)
    dialog_manager = csc.view.DialogManager.instance()
    application = csc.app.get_application()
    scene_manager = application.get_scene_manager()
    data_source_manager = application.get_data_source_manager()
    try:
        try:
            snapshot = _backend_snapshot()
        except Exception:
            snapshot = None
        if not snapshot or not snapshot.get("ok"):
            _reset_session_temp_scenes(scene_manager, data_source_manager, scene_manager.current_scene())
            scene.info("Kimodo backend is already stopped.")
            return
        _stop_kimodo_backend(config, reporter)
        _reset_session_temp_scenes(scene_manager, data_source_manager, scene_manager.current_scene())
        scene.info("Kimodo backend stopped.")
    except Exception as error:
        reporter.update("Kimodo backend stop failed.")
        details = "".join(traceback.format_exception_only(type(error), error)).strip()
        scene.error(details)
        dialog_manager.show_info("Kimodo Backend Error", details)
    finally:
        reporter.close()


def _run_roundtrip(scene, config, settings, reporter, rig_owner=None, rig_label=None):
    _validate_paths(config)
    application = csc.app.get_application()
    scene_manager = application.get_scene_manager()
    action_manager = application.get_action_manager()
    data_source_manager = application.get_data_source_manager()

    original_view = scene_manager.current_scene()
    original_scene = original_view.domain_scene()
    original_frame = original_scene.get_current_frame()
    source_label = rig_label or "source"
    original_rig = _get_rig_context(original_scene, source_label, rig_owner=rig_owner)
    start_frame, end_frame = _get_interval(original_scene)
    num_frames = end_frame - start_frame + 1
    if num_frames <= 0:
        raise RuntimeError("Selected interval is empty.")
    local_start_frame = 0
    local_end_frame = num_frames - 1
    settings["num_frames"] = num_frames
    source_constraint_frames = _collect_source_constraint_frames(
        original_scene,
        start_frame,
        end_frame,
        original_rig["rig_layer_ids"],
    )
    local_constraint_frames = [int(frame) - int(start_frame) for frame in source_constraint_frames]
    original_point_ids = _get_rig_point_ids(
        original_scene,
        original_rig["rig_owner"],
        original_rig["rig_object_ids"],
    )
    source_point_anchor_positions = _capture_point_positions(
        original_scene,
        original_point_ids,
        source_constraint_frames,
    )
    reporter.update(f"Detected source constraint frames: {_format_frame_list(source_constraint_frames)}")
    _persist_defaults(config, settings)

    job_dir = _build_job_dir(config)
    debug_capture = bool(settings["inspect_in_gui"] or settings["keep_debug_scenes"])
    constraints_path = os.path.join(job_dir, "constraints.npz")
    constraints_json_path = os.path.join(job_dir, "constraints_gui.json") if settings["inspect_in_gui"] else ""
    output_path = os.path.join(job_dir, "generated_motion.npz") if settings["inspect_in_gui"] else ""
    output_fbx_path = os.path.join(job_dir, "generated_motion.fbx")
    log_path = os.path.join(job_dir, "kimodo_headless.log")
    inspector_log_path = os.path.join(job_dir, "kimodo_gui_inspector.log") if settings["inspect_in_gui"] else ""
    baked_scene_npz_path = os.path.join(job_dir, "hidden_kimodo_baked_scene.npz") if debug_capture else ""
    return_debug_log_path = os.path.join(job_dir, "return_import_debug.txt") if debug_capture else ""
    lifecycle_log_path = os.path.join(job_dir, "lifecycle_trace.log")
    _write_stage_marker(job_dir, "job_created")
    _append_lifecycle_log(
        lifecycle_log_path,
        "RUN START",
        f"rig_label={source_label}",
        f"original_view={getattr(original_view, 'name', lambda: '<unnamed>')()}",
        _scene_tabs_summary(scene_manager),
        f"interval={start_frame}..{end_frame}",
        f"constraint_frames={_format_frame_list(source_constraint_frames)}",
        f"local_interval={local_start_frame}..{local_end_frame}",
        f"local_constraint_frames={_format_frame_list(local_constraint_frames)}",
        f"settings.dataset={settings['dataset']}",
        f"settings.samples_num={settings['samples_num']}",
        f"settings.sample_index={settings['sample_index']}",
        f"settings.denoising_steps={settings['denoising_steps']}",
    )

    if not settings["keep_debug_scenes"]:
        _append_lifecycle_log(lifecycle_log_path, "resetting cached temp scenes before roundtrip")
        _reset_session_temp_scenes(scene_manager, data_source_manager, original_view)
        _append_lifecycle_log(lifecycle_log_path, _scene_tabs_summary(scene_manager))

    hidden_input_view = _get_or_create_session_temp_scene(scene_manager, "input")
    hidden_output_view = None
    inspect_url = None
    source_root_scene_offset = np.zeros(3, dtype=np.float32)
    try:
        reporter.update("Loading hidden Kimodo source working scene...")
        _write_stage_marker(job_dir, "loading_hidden_input_scene")
        _append_lifecycle_log(
            lifecycle_log_path,
            f"before load hidden input :: hidden_input_view={getattr(hidden_input_view, 'name', lambda: '<unnamed>')()}",
            _scene_tabs_summary(scene_manager),
        )
        _load_scene_into_view(
            data_source_manager,
            scene_manager,
            hidden_input_view,
            _expand_win_path(config.get("paths", "kimodo_scene")),
        )
        _append_lifecycle_log(
            lifecycle_log_path,
            "after load hidden input",
            _scene_tabs_summary(scene_manager),
        )
        hidden_input_scene = hidden_input_view.domain_scene()
        _wait_for_scene_ready(hidden_input_scene, lifecycle_log_path, "hidden_input_loaded")
        hidden_input_rig = _get_rig_context(hidden_input_scene, "hidden Kimodo source")

        reporter.update("Retargeting blocked interval into hidden Kimodo scene...")
        _write_stage_marker(job_dir, "retargeting_source_into_hidden_input")
        _extend_timeline(hidden_input_scene, local_end_frame)
        reporter.update("Seeding matching keyframes in hidden Kimodo scene...")
        _seed_keyframes(hidden_input_scene, hidden_input_rig["rig_layer_ids"], local_constraint_frames)
        _append_lifecycle_log(lifecycle_log_path, "before retarget copy source->hidden input")
        _run_retarget_copy(
            original_view,
            start_frame,
            end_frame,
            scene_manager,
            action_manager,
            original_rig["rig_object_ids"],
            original_rig["rig_layer_ids"],
            original_rig["primary_object_id"],
        )
        _append_lifecycle_log(lifecycle_log_path, "after retarget copy source->hidden input")
        _append_lifecycle_log(lifecycle_log_path, "before retarget paste source->hidden input")
        _run_retarget_paste(
            hidden_input_view,
            local_start_frame,
            local_end_frame,
            scene_manager,
            action_manager,
            hidden_input_rig["rig_object_ids"],
            hidden_input_rig["rig_layer_ids"],
            hidden_input_rig["primary_object_id"],
        )
        _append_lifecycle_log(lifecycle_log_path, "after retarget paste source->hidden input")
        _wait_for_scene_ready(hidden_input_scene, lifecycle_log_path, "hidden_input_after_retarget_paste")

        reporter.update("Extracting full-pose constraints from hidden Kimodo scene...")
        _write_stage_marker(job_dir, "extracting_hidden_input_constraints")
        joint_ids = _get_joint_order(hidden_input_scene, hidden_input_rig["joint_ids"])
        source_root_scene_offset = _get_global_position_at_frame(
            hidden_input_scene,
            joint_ids[0],
            local_constraint_frames[0],
        )
        source_root_scene_offset[1] = 0.0
        _append_lifecycle_log(
            lifecycle_log_path,
            "normalizing hidden input horizontal root offset for Kimodo export",
            f"source_root_scene_offset_horizontal={source_root_scene_offset.tolist()}",
        )
        constraint_frames = _write_constraint_npz(
            hidden_input_scene,
            joint_ids,
            local_constraint_frames,
            local_start_frame,
            constraints_path,
            position_scale=0.01,
            position_offset=source_root_scene_offset,
            rotation_post_basis=CASCADEUR_TO_KIMODO_ROT_BASIS,
        )

        reporter.update(
            f"Generating motion in Kimodo headlessly ({len(constraint_frames)} source constraint frames, {num_frames} total)..."
        )
        _write_stage_marker(job_dir, "running_kimodo_generation")
        _append_lifecycle_log(lifecycle_log_path, "before kimodo generation request")
        _run_kimodo_generation(config, settings, constraints_path, output_path, output_fbx_path, log_path, reporter)
        _append_lifecycle_log(lifecycle_log_path, "after kimodo generation request")

        if settings["inspect_in_gui"]:
            reporter.update("Launching Kimodo GUI debug inspector with generated motion...")
            _write_stage_marker(job_dir, "launching_kimodo_gui_inspector")
            inspect_url = _launch_kimodo_gui_inspector(
                config,
                settings,
                constraints_path,
                constraints_json_path,
                output_path,
                inspector_log_path,
                reporter,
            )
            _write_stage_marker(job_dir, "kimodo_gui_inspector_ready")
            reporter.update("Kimodo GUI debug inspector is ready. Continuing roundtrip...")

        reporter.update("Reloading the temporary Kimodo scene for generated output import...")
        _write_stage_marker(job_dir, "loading_hidden_output_scene")
        hidden_output_view = _get_or_create_session_temp_scene(scene_manager, "output")
        _append_lifecycle_log(
            lifecycle_log_path,
            f"before load hidden output :: hidden_output_view={getattr(hidden_output_view, 'name', lambda: '<unnamed>')()}",
            _scene_tabs_summary(scene_manager),
        )
        _load_scene_into_view(
            data_source_manager,
            scene_manager,
            hidden_output_view,
            _expand_win_path(config.get("paths", "kimodo_scene")),
        )
        _append_lifecycle_log(
            lifecycle_log_path,
            "after load hidden output",
            _scene_tabs_summary(scene_manager),
        )
        hidden_output_scene = hidden_output_view.domain_scene()
        _wait_for_scene_ready(hidden_output_scene, lifecycle_log_path, "hidden_output_loaded")
        hidden_output_rig = _get_rig_context(hidden_output_scene, "hidden Kimodo output")

        if return_debug_log_path:
            _append_debug_log(
                return_debug_log_path,
                "",
                "=" * 80,
                f"RETURN IMPORT DEBUG START {time.strftime('%Y-%m-%d %H:%M:%S')}",
                f"generated_motion_fbx={output_fbx_path}",
                "hidden_output_before_import:",
                _selected_objects_summary(hidden_output_scene),
                *_layer_key_debug_summary(hidden_output_scene, hidden_output_rig["rig_layer_ids"]),
            )
        reporter.update("Importing generated Kimodo FBX into the second temporary Kimodo scene...")
        _write_stage_marker(job_dir, "importing_generated_fbx_into_hidden_output")
        reporter.progress("Importing generated Kimodo FBX into second temporary Kimodo scene (0%)")
        _append_lifecycle_log(lifecycle_log_path, "before hidden output fbx import")
        _import_generated_fbx_animation(
            hidden_output_view,
            output_fbx_path,
            scene_manager,
            hidden_output_rig["rig_layer_ids"],
            return_debug_log_path,
            reporter,
        )
        _append_lifecycle_log(lifecycle_log_path, "after hidden output fbx import")
        _wait_for_scene_ready(hidden_output_scene, lifecycle_log_path, "hidden_output_after_fbx_import")
        reporter.progress("Importing generated Kimodo FBX into second temporary Kimodo scene (100%)")
        imported_frames = _collect_keyframes_in_range(hidden_output_scene, hidden_output_rig["rig_layer_ids"])
        imported_start_frame = imported_frames[0] if imported_frames else local_start_frame
        imported_end_frame = imported_frames[-1] if imported_frames else local_end_frame
        processing_output_start_frame = local_start_frame
        processing_output_end_frame = local_end_frame
        if return_debug_log_path:
            _append_debug_log(
                return_debug_log_path,
                f"imported_keyframe_range={imported_start_frame}..{imported_end_frame}",
                f"imported_keyframe_count={len(imported_frames)}",
                f"processing_output_range={processing_output_start_frame}..{processing_output_end_frame}",
                "hidden_output_after_import:",
                _selected_objects_summary(hidden_output_scene),
                *_layer_key_debug_summary(hidden_output_scene, hidden_output_rig["rig_layer_ids"]),
            )

        if baked_scene_npz_path:
            reporter.update("Sampling hidden Kimodo output scene...")
            _write_stage_marker(job_dir, "sampling_hidden_output_scene")
            _append_lifecycle_log(lifecycle_log_path, "before sampling hidden output scene")
            _write_constraint_npz(
                hidden_output_scene,
                _get_joint_order(hidden_output_scene, hidden_output_rig["joint_ids"]),
                range(processing_output_start_frame, processing_output_end_frame + 1),
                processing_output_start_frame,
                baked_scene_npz_path,
            )
            _append_lifecycle_log(lifecycle_log_path, "after sampling hidden output scene")

        reporter.update("Retargeting the generated Kimodo result back into the original scene...")
        _write_stage_marker(job_dir, "retargeting_hidden_output_back_to_source")
        if return_debug_log_path:
            _append_debug_log(
                return_debug_log_path,
                "",
                "=" * 80,
                "FINAL RETARGET COPY SOURCE SELECTION",
                _object_list_summary(hidden_output_scene, hidden_output_rig["rig_object_ids"]),
                _layer_list_summary(hidden_output_scene, hidden_output_rig["rig_layer_ids"]),
            )
        reporter.progress("Copying generated animation from hidden Kimodo scene (0%)")
        _append_lifecycle_log(lifecycle_log_path, "before retarget copy hidden output->source")
        _run_retarget_copy(
            hidden_output_view,
            processing_output_start_frame,
            processing_output_end_frame,
            scene_manager,
            action_manager,
            hidden_output_rig["rig_object_ids"],
            hidden_output_rig["rig_layer_ids"],
            hidden_output_rig["primary_object_id"],
        )
        _append_lifecycle_log(lifecycle_log_path, "after retarget copy hidden output->source")
        _wait_for_scene_ready(hidden_output_scene, lifecycle_log_path, "hidden_output_after_retarget_copy")
        reporter.progress("Copying generated animation from hidden Kimodo scene (100%)")
        if return_debug_log_path:
            _append_debug_log(
                return_debug_log_path,
                "",
                "=" * 80,
                "FINAL RETARGET PASTE TARGET SELECTION",
                _object_list_summary(original_scene, original_rig["rig_object_ids"]),
                _layer_list_summary(original_scene, original_rig["rig_layer_ids"]),
            )
        reporter.progress("Pasting generated animation into the current scene (0%)")
        _append_lifecycle_log(lifecycle_log_path, "before retarget paste hidden output->source")
        _run_retarget_paste(
            original_view,
            start_frame,
            end_frame,
            scene_manager,
            action_manager,
            original_rig["rig_object_ids"],
            original_rig["rig_layer_ids"],
            original_rig["primary_object_id"],
        )
        _append_lifecycle_log(lifecycle_log_path, "after retarget paste hidden output->source")
        _wait_for_scene_ready(original_scene, lifecycle_log_path, "original_scene_after_retarget_paste")
        reporter.update("Applying final source-constraint point correction pass...")
        _write_stage_marker(job_dir, "applying_final_point_constraint_pass")
        _append_lifecycle_log(lifecycle_log_path, "before final point constraint pass")
        point_pass_summary = _run_final_point_constraint_pass(
            original_scene,
            original_rig,
            source_constraint_frames,
            source_point_anchor_positions,
            start_frame,
            end_frame,
            reporter,
        )
        _append_lifecycle_log(
            lifecycle_log_path,
            "after final point constraint pass",
            f"point_pass_summary={point_pass_summary}",
        )
        _wait_for_scene_ready(original_scene, lifecycle_log_path, "original_scene_after_final_point_constraint_pass")
        if return_debug_log_path:
            _append_debug_log(
                return_debug_log_path,
                "",
                "=" * 80,
                "FINAL SOURCE SCENE AFTER RETARGET PASTE",
                _selected_objects_summary(original_scene),
                *_layer_key_debug_summary(original_scene, original_rig["rig_layer_ids"]),
                f"final_point_constraint_pass={point_pass_summary}",
            )
        _write_stage_marker(job_dir, "post_paste_debug_written")
        reporter.progress("Pasting generated animation into the current scene (100%)")
        _write_stage_marker(job_dir, "post_paste_progress_reported")
        _write_stage_marker(job_dir, "completed")
        _append_lifecycle_log(
            lifecycle_log_path,
            "after completed marker",
            _scene_tabs_summary(scene_manager),
        )

        _write_stage_marker(job_dir, "restoring_original_frame")
        try:
            original_scene.set_current_frame(original_frame)
        except Exception:
            pass
        _write_stage_marker(job_dir, "original_frame_restored")
        _append_lifecycle_log(lifecycle_log_path, "after original frame restore")
        if settings["keep_debug_scenes"]:
            _write_stage_marker(job_dir, "showing_debug_completion_dialog")
            scene_manager.set_current_scene(hidden_output_view)
            _write_stage_marker(job_dir, "debug_scene_shown")
            _write_stage_marker(job_dir, "completion_reported")
            _append_lifecycle_log(lifecycle_log_path, "after debug scene shown")
        else:
            _write_stage_marker(job_dir, "switching_to_original_scene")
            try:
                scene_manager.set_current_scene(original_view)
            except Exception:
                pass
            _ui_settle()
            _wait_for_scene_ready(original_scene, lifecycle_log_path, "original_scene_after_show")
            _write_stage_marker(job_dir, "original_scene_shown")
            _write_stage_marker(job_dir, "completion_reported")
            _append_lifecycle_log(
                lifecycle_log_path,
                "after original scene shown",
                _scene_tabs_summary(scene_manager),
            )
            _write_stage_marker(job_dir, "cleanup_start")
            _append_lifecycle_log(lifecycle_log_path, "cleanup_start")
            _reset_session_temp_scenes(scene_manager, data_source_manager, original_view)
            _write_stage_marker(job_dir, "cleanup_done")
            _append_lifecycle_log(
                lifecycle_log_path,
                "cleanup_done",
                _scene_tabs_summary(scene_manager),
            )
    finally:
        try:
            if not settings["keep_debug_scenes"]:
                _append_lifecycle_log(lifecycle_log_path, "finally cleanup finished")
        except Exception:
            pass


def _run_roundtrip_for_selected_characters(scene, config, settings, reporter):
    rig_owners = _get_selected_rig_owners(scene)
    if len(rig_owners) <= 1:
        rig_owner = rig_owners[0] if rig_owners else None
        rig_name = _describe_scene_object(scene, rig_owner) if rig_owner is not None else "current character"
        reporter.update(f"Generating for {rig_name}...")
        _run_roundtrip(scene, config, dict(settings), reporter, rig_owner=rig_owner, rig_label=rig_name)
        return

    total = len(rig_owners)
    for index, rig_owner in enumerate(rig_owners, 1):
        rig_name = _describe_scene_object(scene, rig_owner)
        reporter.update(f"Generating character {index}/{total}: {rig_name}")
        _run_roundtrip(scene, config, dict(settings), reporter, rig_owner=rig_owner, rig_label=rig_name)


def _remove_kimodo_generated_frames(scene):
    reporter = _status_reporter(scene)
    try:
        start_frame, end_frame = _get_interval(scene)
        rig_owners = _get_selected_rig_owners(scene)
        if not rig_owners:
            rig_owners = _get_all_rig_owners(scene)
        if not rig_owners:
            raise RuntimeError("Could not find any rigged characters in the current scene.")

        removed_total = 0
        processed = 0
        summaries = []
        for rig_owner in rig_owners:
            rig_name = _describe_scene_object(scene, rig_owner) if rig_owner is not None else "current character"
            reporter.update(f"Removing Kimodo-generated frames for {rig_name}...")
            rig = _get_rig_context(scene, rig_name, rig_owner=rig_owner)
            character_folder_id = _find_character_folder_id(scene, rig["rig_layer_ids"])
            if character_folder_id is not None:
                character_label = _layer_header_name(scene, character_folder_id) or rig_name
                character_layer_ids = _collect_descendant_layer_ids(scene, character_folder_id)
            else:
                character_label = rig_name
                character_layer_ids = list(rig["rig_layer_ids"])

            finger_layer_ids = [layer_id for layer_id in character_layer_ids if _is_finger_timeline_layer(scene, layer_id)]
            finger_layer_ids = _ordered_unique(layer_id for layer_id in finger_layer_ids if not layer_id.is_null())
            if not finger_layer_ids:
                raise RuntimeError(f"{character_label} has no finger layers. Cleanup cannot safely identify Kimodo-generated frames.")

            finger_frames = set(_collect_actual_keyframes_in_interval(scene, finger_layer_ids, start_frame, end_frame))
            nonfinger_layer_ids = [
                layer_id
                for layer_id in character_layer_ids
                if layer_id not in finger_layer_ids
            ]
            candidate_frames = set(_collect_actual_keyframes_in_interval(scene, nonfinger_layer_ids, start_frame, end_frame))
            frames_to_delete = sorted(candidate_frames - finger_frames)
            removed = _remove_frames_from_layers(scene, nonfinger_layer_ids, frames_to_delete)
            removed_total += removed
            processed += 1
            summaries.append(
                f"{character_label}: {len(frames_to_delete)} frames, {removed} layer-key removals"
            )

        reporter.update(f"Removed Kimodo-generated frames for {processed} character(s).")
        csc.view.DialogManager.instance().show_info(
            "Kimodo Cleanup",
            "\n".join(
                [f"Processed characters: {processed}", f"Selected interval: {start_frame}..{end_frame}", *summaries]
            ),
        )
    except Exception as error:
        reporter.update("Kimodo cleanup failed.")
        details = "".join(traceback.format_exception_only(type(error), error)).strip()
        scene.error(details)
        csc.view.DialogManager.instance().show_info("Kimodo Cleanup Error", details)
    finally:
        reporter.close()


def run(scene):
    config = _ensure_config()
    dialog_manager = csc.view.DialogManager.instance()

    try:
        snapshot = _backend_snapshot()
    except Exception:
        snapshot = None

    def start_llama_callback():
        run_start_backend(scene, text_encoder_mode="llama")
        run(scene)

    def start_no_llama_callback():
        run_start_backend(scene, text_encoder_mode="fallback")
        run(scene)

    def stop_callback():
        run_stop_backend(scene)
        run(scene)

    def refresh_callback():
        run(scene)

    def generate_callback():
        try:
            current_snapshot = _backend_snapshot()
        except Exception:
            current_snapshot = None
        if not current_snapshot or not current_snapshot.get("ok"):
            dialog_manager.show_info("Kimodo Roundtrip", "Start Kimodo first.")
            return
        if current_snapshot.get("warming_up"):
            dialog_manager.show_info("Kimodo Roundtrip", "Kimodo is still warming up. Wait for preload to finish.")
            return
        if current_snapshot.get("busy"):
            dialog_manager.show_info("Kimodo Roundtrip", "Kimodo is busy. Wait for the current job to finish.")
            return
        _show_generate_dialog(scene, config)

    def cleanup_callback():
        _remove_kimodo_generated_frames(scene)

    dialog_buttons = []
    if snapshot and snapshot.get("ok"):
        if not snapshot.get("busy") and not snapshot.get("warming_up"):
            dialog_buttons.append(csc.view.DialogButton("Generate", generate_callback))
            dialog_buttons.append(csc.view.DialogButton("Remove Kimodo Frames", cleanup_callback))
        dialog_buttons.append(csc.view.DialogButton("Refresh", refresh_callback))
        dialog_buttons.append(csc.view.DialogButton("Stop Kimodo", stop_callback))
    else:
        if _native_mode(config):
            dialog_buttons.append(csc.view.DialogButton("Start Kimodo (LLAMA NF4)", start_llama_callback))
            dialog_buttons.append(csc.view.DialogButton("Start Kimodo (LLAMA OFF)", start_no_llama_callback))
        else:
            dialog_buttons.append(csc.view.DialogButton("Start Kimodo (LLAMA)", start_llama_callback))
            dialog_buttons.append(csc.view.DialogButton("Start Kimodo (LLAMA 10GB VRAM)", start_llama_8bit_callback))
            dialog_buttons.append(csc.view.DialogButton("Start Kimodo (LLAMA OFF)", start_no_llama_callback))
    dialog_buttons.append(csc.view.DialogButton(csc.view.StandardButton.Cancel))

    dialog_manager.show_buttons_dialog(
        "Kimodo Roundtrip",
        _backend_dialog_text(snapshot, config),
        dialog_buttons,
    )
