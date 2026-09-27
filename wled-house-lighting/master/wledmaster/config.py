from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Controller:
    name: str
    host: str


@dataclass
class Zone:
    name: str
    controllers: dict[str, Controller]
    # scene name -> {controller name -> preset id}
    scenes: dict[str, dict[str, int]]


@dataclass
class Config:
    zones: dict[str, Zone]

    def all_controllers(self) -> list[Controller]:
        return [c for zone in self.zones.values() for c in zone.controllers.values()]


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text())
    zones: dict[str, Zone] = {}
    for zone_name, zone_raw in (raw.get("zones") or {}).items():
        controllers = {
            ctrl_name: Controller(name=ctrl_name, host=ctrl_raw["host"])
            for ctrl_name, ctrl_raw in (zone_raw.get("controllers") or {}).items()
        }
        scenes = zone_raw.get("scenes") or {}
        for scene_name, preset_map in scenes.items():
            unknown = set(preset_map) - set(controllers)
            if unknown:
                raise ValueError(
                    f"zone '{zone_name}' scene '{scene_name}' references "
                    f"unknown controller(s): {sorted(unknown)}"
                )
        zones[zone_name] = Zone(name=zone_name, controllers=controllers, scenes=scenes)
    return Config(zones=zones)
