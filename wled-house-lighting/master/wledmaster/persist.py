from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)
_yaml.width = 100


def _clean_action(action: dict) -> dict:
    """Drop unset fields so saved YAML stays readable (no `col: null` etc)."""
    keys = ("controller", "segment", "preset", "power", "col", "fx", "sx", "pal", "bri")
    return {k: action[k] for k in keys if action.get(k) is not None}


def _load(path: Path):
    return _yaml.load(path.read_text())


def _save(path: Path, doc) -> None:
    with path.open("w") as f:
        _yaml.dump(doc, f)


def save_scene(path: Path, zone_name: str, scene_name: str, actions: list[dict]) -> None:
    doc = _load(path)
    zone = doc["zones"][zone_name]
    if "scenes" not in zone or zone["scenes"] is None:
        zone["scenes"] = {}
    zone["scenes"][scene_name] = [_clean_action(a) for a in actions]
    _save(path, doc)


def rename_scene(path: Path, zone_name: str, old_name: str, new_name: str) -> None:
    if old_name == new_name:
        return
    doc = _load(path)
    scenes = doc["zones"][zone_name]["scenes"]
    if old_name in scenes:
        scenes[new_name] = scenes.pop(old_name)
    _save(path, doc)


def delete_scene(path: Path, zone_name: str, scene_name: str) -> None:
    doc = _load(path)
    scenes = doc["zones"][zone_name].get("scenes") or {}
    if scene_name in scenes:
        del scenes[scene_name]
    _save(path, doc)
