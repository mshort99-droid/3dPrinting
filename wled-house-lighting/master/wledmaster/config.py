from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Controller:
    name: str
    host: str
    # segment name -> WLED segment id, as configured on the controller itself
    segments: dict[str, int]


@dataclass
class SceneAction:
    controller: str
    segment: str | None = None  # None = whole-controller action
    preset: int | None = None
    on: bool | None = None
    col: list[int] | None = None  # [r, g, b]
    fx: int | None = None
    bri: int | None = None

    def __post_init__(self) -> None:
        if self.preset is not None and self.segment is not None:
            raise ValueError("a scene action can't set both 'preset' and 'segment'")
        if self.preset is None and self.segment is None and self.on is None:
            raise ValueError(
                "a scene action needs 'preset', or 'segment' with at least 'on'/'col'/'fx'/'bri'"
            )


@dataclass
class Zone:
    name: str
    controllers: dict[str, Controller]
    scenes: dict[str, list[SceneAction]]


@dataclass
class Config:
    zones: dict[str, Zone]

    def all_controllers(self) -> list[Controller]:
        return [c for zone in self.zones.values() for c in zone.controllers.values()]


def _parse_action(raw: dict) -> SceneAction:
    # YAML 1.1 parses bare `on`/`off` as booleans, so a literal "on: false" key
    # becomes {True: False}, not {"on": False}. Use "power" in the config file
    # instead and translate it to the SceneAction.on field here.
    return SceneAction(
        controller=raw["controller"],
        segment=raw.get("segment"),
        preset=raw.get("preset"),
        on=raw.get("power"),
        col=raw.get("col"),
        fx=raw.get("fx"),
        bri=raw.get("bri"),
    )


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text())
    zones: dict[str, Zone] = {}
    for zone_name, zone_raw in (raw.get("zones") or {}).items():
        controllers = {
            ctrl_name: Controller(
                name=ctrl_name,
                host=ctrl_raw["host"],
                segments=ctrl_raw.get("segments") or {},
            )
            for ctrl_name, ctrl_raw in (zone_raw.get("controllers") or {}).items()
        }

        scenes: dict[str, list[SceneAction]] = {}
        for scene_name, actions_raw in (zone_raw.get("scenes") or {}).items():
            actions = [_parse_action(a) for a in actions_raw]
            for action in actions:
                controller = controllers.get(action.controller)
                if controller is None:
                    raise ValueError(
                        f"zone '{zone_name}' scene '{scene_name}' references "
                        f"unknown controller '{action.controller}'"
                    )
                if action.segment is not None and action.segment not in controller.segments:
                    raise ValueError(
                        f"zone '{zone_name}' scene '{scene_name}' references "
                        f"unknown segment '{action.segment}' on controller "
                        f"'{action.controller}'"
                    )
            scenes[scene_name] = actions

        zones[zone_name] = Zone(name=zone_name, controllers=controllers, scenes=scenes)
    return Config(zones=zones)
