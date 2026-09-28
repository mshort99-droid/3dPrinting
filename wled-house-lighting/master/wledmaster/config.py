from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Controller:
    name: str
    host: str
    # segment name -> WLED segment id, as configured on the controller itself
    segments: dict[str, int]
    # friendlier label for the UI - falls back to `name` when unset. Purely
    # cosmetic: every scene/action still addresses the controller by `name`.
    display_name: str | None = None


@dataclass
class SceneAction:
    controller: str
    segment: str | None = None  # None = whole-controller action
    preset: int | None = None
    on: bool | None = None
    col: list[list[int]] | None = None  # up to 3 slots: [primary, secondary, tertiary]
    fx: int | None = None  # WLED effect id (0 = Solid)
    sx: int | None = None  # effect speed, 0-255
    pal: int | None = None  # palette id
    bri: int | None = None

    def __post_init__(self) -> None:
        if self.preset is not None and self.segment is not None:
            raise ValueError("a scene action can't set both 'preset' and 'segment'")
        if self.preset is None and self.segment is None and self.on is None:
            raise ValueError(
                "a scene action needs 'preset', or 'segment' with at least 'on'/'col'/'fx'/'bri'"
            )

    def to_dict(self) -> dict:
        d: dict = {"controller": self.controller}
        if self.segment is not None:
            d["segment"] = self.segment
        if self.preset is not None:
            d["preset"] = self.preset
        if self.on is not None:
            d["power"] = self.on
        if self.col is not None:
            d["col"] = self.col
        if self.fx is not None:
            d["fx"] = self.fx
        if self.sx is not None:
            d["sx"] = self.sx
        if self.pal is not None:
            d["pal"] = self.pal
        if self.bri is not None:
            d["bri"] = self.bri
        return d


@dataclass
class Zone:
    name: str
    controllers: dict[str, Controller]
    scenes: dict[str, list[SceneAction]]
    # segment name -> friendlier label for the UI, e.g. "shelf21" -> "Shelf 1".
    # Flat (not per-controller) since segment names are already unique within
    # a zone; falls back to the segment's own name when unset. Cosmetic only -
    # scenes still address segments by their real name.
    segment_names: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    zones: dict[str, Zone]

    def all_controllers(self) -> list[Controller]:
        return [c for zone in self.zones.values() for c in zone.controllers.values()]


def parse_action(raw: dict) -> SceneAction:
    # YAML 1.1 parses bare `on`/`off` as booleans, so a literal "on: false" key
    # becomes {True: False}, not {"on": False}. Use "power" in the config file
    # instead and translate it to the SceneAction.on field here.
    col = raw.get("col")
    if col and not isinstance(col[0], (list, tuple)):
        # Older scenes (saved before multi-color-slot support) store a single
        # flat [r, g, b] triplet instead of a list of slots - treat that as
        # "just a primary color" rather than requiring a house.yaml migration.
        col = [col]
    return SceneAction(
        controller=raw["controller"],
        segment=raw.get("segment"),
        preset=raw.get("preset"),
        on=raw.get("power"),
        col=col,
        fx=raw.get("fx"),
        sx=raw.get("sx"),
        pal=raw.get("pal"),
        bri=raw.get("bri"),
    )


def validate_action(zone: Zone, action: SceneAction) -> None:
    controller = zone.controllers.get(action.controller)
    if controller is None:
        raise ValueError(
            f"zone '{zone.name}' has no controller '{action.controller}'"
        )
    if action.segment is not None and action.segment not in controller.segments:
        raise ValueError(
            f"controller '{action.controller}' has no segment '{action.segment}'"
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
                display_name=ctrl_raw.get("display_name"),
            )
            for ctrl_name, ctrl_raw in (zone_raw.get("controllers") or {}).items()
        }
        zone = Zone(
            name=zone_name,
            controllers=controllers,
            scenes={},
            segment_names=zone_raw.get("segment_names") or {},
        )

        for scene_name, actions_raw in (zone_raw.get("scenes") or {}).items():
            actions = [parse_action(a) for a in actions_raw]
            for action in actions:
                try:
                    validate_action(zone, action)
                except ValueError as exc:
                    raise ValueError(
                        f"zone '{zone_name}' scene '{scene_name}': {exc}"
                    ) from exc
            zone.scenes[scene_name] = actions

        zones[zone_name] = zone
    return Config(zones=zones)
