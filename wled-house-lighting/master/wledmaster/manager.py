from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import aiohttp

from . import persist
from .config import Config, SceneAction, Zone, load_config, parse_action, validate_action
from .wled_client import WledClient

logger = logging.getLogger(__name__)

DEFAULT_SOCKET_PATH = "/run/wled-master/control.sock"


class Manager:
    def __init__(self, config: Config, config_path: Path) -> None:
        self.config = config
        self.config_path = config_path
        self.clients: dict[str, WledClient] = {
            controller.name: WledClient(controller) for controller in config.all_controllers()
        }
        self._tasks: list[asyncio.Task] = []
        self.effects: list[str] = []
        self.palettes: list[str] = []

    async def start_clients(self) -> None:
        for client in self.clients.values():
            self._tasks.append(asyncio.create_task(client.run()))

    async def load_effects_and_palettes(self) -> None:
        """WLED's built-in effect/palette names, fetched once from whichever
        controller answers first (they all run the same firmware version).
        Best-effort: the scene editor just won't offer effects by name if
        this fails, everything else still works."""
        for controller in self.config.all_controllers():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"http://{controller.host}/json/eff", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        self.effects = await resp.json()
                    async with session.get(f"http://{controller.host}/json/pal", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        self.palettes = await resp.json()
                logger.info(
                    "loaded %d effects and %d palettes from %s",
                    len(self.effects), len(self.palettes), controller.name,
                )
                return
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning("couldn't fetch effects/palettes from %s: %s", controller.name, exc)
        logger.warning("no controller answered for effects/palettes; scene editor will skip effect names")

    async def stop_clients(self) -> None:
        for client in self.clients.values():
            client.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def apply_scene(self, zone_name: str, scene_name: str) -> dict:
        zone = self.config.zones.get(zone_name)
        if zone is None:
            return {"ok": False, "error": f"unknown zone '{zone_name}'"}
        actions = zone.scenes.get(scene_name)
        if actions is None:
            return {"ok": False, "error": f"unknown scene '{scene_name}' in zone '{zone_name}'"}
        return await self._send_actions(zone, actions)

    async def toggle_zone_power(self, zone_name: str) -> dict:
        """Turn every controller in the zone fully off, or back on.

        Uses each WLED controller's top-level "on" switch rather than
        touching individual segments - WLED keeps every segment's own
        color/effect/on-state in memory while the controller is off, so
        turning it back on restores exactly what was showing before,
        including scenes that had some segments off (e.g. "Top Shelves
        Off") - no need to remember which scene was last applied.
        """
        zone = self.config.zones.get(zone_name)
        if zone is None:
            return {"ok": False, "error": f"unknown zone '{zone_name}'"}
        any_on = any(
            (self.clients[c.name].last_state or {}).get("state", {}).get("on")
            for c in zone.controllers.values()
        )
        turn_on = not any_on
        results = {}
        for controller in zone.controllers.values():
            sent = await self.clients[controller.name].send({"on": turn_on})
            results[controller.name] = "sent" if sent else "not connected"
        return {"ok": True, "on": turn_on, "results": results}

    async def set_zone_brightness(self, zone_name: str, bri: int) -> dict:
        """Master dimmer: set overall brightness on every controller in the
        zone. Doesn't touch per-segment colors/on-state, same as the power
        toggle - just WLED's top-level "bri"."""
        zone = self.config.zones.get(zone_name)
        if zone is None:
            return {"ok": False, "error": f"unknown zone '{zone_name}'"}
        bri = max(1, min(255, int(bri)))
        results = {}
        for controller in zone.controllers.values():
            sent = await self.clients[controller.name].send({"bri": bri})
            results[controller.name] = "sent" if sent else "not connected"
        return {"ok": True, "bri": bri, "results": results}

    async def preview(self, zone_name: str, action_raw: dict) -> dict:
        zone = self.config.zones.get(zone_name)
        if zone is None:
            return {"ok": False, "error": f"unknown zone '{zone_name}'"}
        try:
            action = parse_action(action_raw)
            validate_action(zone, action)
        except (ValueError, KeyError) as exc:
            return {"ok": False, "error": str(exc)}
        return await self._send_actions(zone, [action])

    async def _send_actions(self, zone: Zone, actions: list[SceneAction]) -> dict:
        # Group by controller so multiple segment actions for the same
        # controller go out as one WLED command instead of racing each other.
        by_controller: dict[str, list[SceneAction]] = {}
        for action in actions:
            by_controller.setdefault(action.controller, []).append(action)

        results = {}
        for controller_name, controller_actions in by_controller.items():
            command = self._build_command(zone, controller_actions)
            client = self.clients[controller_name]
            sent = await client.send(command)
            results[controller_name] = "sent" if sent else "not connected"
        return {"ok": True, "results": results}

    def _build_command(self, zone: Zone, actions: list[SceneAction]) -> dict:
        """Combine same-controller scene actions into one WLED JSON command."""
        command: dict = {}
        segments = []
        for action in actions:
            if action.preset is not None:
                command["ps"] = action.preset
                continue
            controller = zone.controllers[action.controller]
            seg: dict = {"id": controller.segments[action.segment]}
            if action.on is not None:
                seg["on"] = action.on
            if action.col is not None:
                seg["col"] = action.col
            if action.fx is not None:
                seg["fx"] = action.fx
            if action.sx is not None:
                seg["sx"] = action.sx
            if action.pal is not None:
                seg["pal"] = action.pal
            if action.bri is not None:
                seg["bri"] = action.bri
            segments.append(seg)
        if segments:
            command["seg"] = segments
        return command

    # -- scene CRUD, persisted to house.yaml and hot-reloaded ---------------

    def save_scene(self, zone_name: str, scene_name: str, actions_raw: list[dict]) -> dict:
        zone = self.config.zones.get(zone_name)
        if zone is None:
            return {"ok": False, "error": f"unknown zone '{zone_name}'"}
        try:
            actions = [parse_action(a) for a in actions_raw]
            for action in actions:
                validate_action(zone, action)
        except (ValueError, KeyError) as exc:
            return {"ok": False, "error": str(exc)}

        persist.save_scene(self.config_path, zone_name, scene_name, actions_raw)
        self._reload()
        return {"ok": True}

    def rename_scene(self, zone_name: str, old_name: str, new_name: str) -> dict:
        zone = self.config.zones.get(zone_name)
        if zone is None:
            return {"ok": False, "error": f"unknown zone '{zone_name}'"}
        if old_name not in zone.scenes:
            return {"ok": False, "error": f"unknown scene '{old_name}'"}
        if new_name in zone.scenes:
            return {"ok": False, "error": f"scene '{new_name}' already exists"}
        persist.rename_scene(self.config_path, zone_name, old_name, new_name)
        self._reload()
        return {"ok": True}

    def delete_scene(self, zone_name: str, scene_name: str) -> dict:
        zone = self.config.zones.get(zone_name)
        if zone is None:
            return {"ok": False, "error": f"unknown zone '{zone_name}'"}
        if scene_name not in zone.scenes:
            return {"ok": False, "error": f"unknown scene '{scene_name}'"}
        persist.delete_scene(self.config_path, zone_name, scene_name)
        self._reload()
        return {"ok": True}

    def _reload(self) -> None:
        """Re-read house.yaml. Only scenes are expected to change this way;
        controllers/segments still require a service restart to take effect."""
        self.config = load_config(self.config_path)

    def effects_meta(self) -> dict:
        return {"effects": self.effects, "palettes": self.palettes}

    # -- status for the web UI -----------------------------------------------

    def status(self) -> dict:
        return {
            name: {
                "connected": client.connected,
                "last_state": client.last_state,
            }
            for name, client in self.clients.items()
        }

    def dashboard_state(self) -> dict:
        """Friendly, small per-segment state for the web UI (vs. status()'s
        raw WLED dump used by the CLI)."""
        zones = {}
        for zone_name, zone in self.config.zones.items():
            controllers = {}
            for cname, controller in zone.controllers.items():
                client = self.clients[cname]
                live_segs = {}
                if client.last_state:
                    for seg in client.last_state.get("state", {}).get("seg", []):
                        live_segs[seg.get("id")] = seg
                segments = {}
                for seg_name, seg_id in controller.segments.items():
                    live = live_segs.get(seg_id, {})
                    col = live.get("col") or [[0, 0, 0]]
                    segments[seg_name] = {
                        "id": seg_id,
                        "display_name": zone.segment_names.get(seg_name, seg_name),
                        "on": live.get("on"),
                        "col": col,  # up to 3 slots: [primary, secondary, tertiary]
                        "fx": live.get("fx", 0),
                        "sx": live.get("sx", 128),
                        "pal": live.get("pal", 0),
                    }
                live_state = (client.last_state or {}).get("state", {})
                controllers[cname] = {
                    "host": controller.host,
                    "display_name": controller.display_name or cname,
                    "connected": client.connected,
                    "on": live_state.get("on"),
                    "bri": live_state.get("bri"),
                    "segments": segments,
                }
            zones[zone_name] = {
                "controllers": controllers,
                "scenes": {
                    sname: {
                        "actions": [a.to_dict() for a in actions],
                        "active": self._scene_is_active(zone, actions),
                    }
                    for sname, actions in zone.scenes.items()
                },
            }
        return zones

    def _scene_is_active(self, zone: Zone, actions: list[SceneAction]) -> bool:
        """Whether the live device state currently matches every action in
        this scene - used to highlight which scene (if any) is "on" right
        now, rather than just previewing each scene's own configured colors."""
        for action in actions:
            client = self.clients[action.controller]
            live_state = (client.last_state or {}).get("state")
            if live_state is None:
                return False
            if action.preset is not None:
                if live_state.get("ps") != action.preset:
                    return False
                continue
            controller = zone.controllers[action.controller]
            seg_id = controller.segments[action.segment]
            live_seg = next((s for s in live_state.get("seg", []) if s.get("id") == seg_id), None)
            if live_seg is None:
                return False
            if action.on is not None and bool(live_seg.get("on")) != bool(action.on):
                return False
            if action.on and action.col is not None:
                live_col = live_seg.get("col") or [[0, 0, 0]]
                # Only compare the slots this action actually sets - an action
                # that only specifies a primary color shouldn't fail to match
                # just because the live secondary/tertiary happen to differ.
                for i, slot in enumerate(action.col):
                    live_slot = live_col[i] if i < len(live_col) else [0, 0, 0]
                    if list(live_slot) != list(slot):
                        return False
            if action.on and action.fx is not None and live_seg.get("fx") != action.fx:
                return False
            if action.on and action.sx is not None and live_seg.get("sx") != action.sx:
                return False
            if action.on and action.pal is not None and live_seg.get("pal") != action.pal:
                return False
        return True

    async def serve_control_socket(self, socket_path: str) -> None:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                line = await reader.readline()
                response = await self._handle_command(line.decode().strip())
            except Exception as exc:  # keep the socket server alive regardless
                logger.exception("error handling control command")
                response = {"ok": False, "error": str(exc)}
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
            writer.close()

        server = await asyncio.start_unix_server(handle, path=socket_path)
        logger.info("control socket listening at %s", socket_path)
        async with server:
            await server.serve_forever()

    async def _handle_command(self, line: str) -> dict:
        parts = line.split(maxsplit=2)
        if not parts:
            return {"ok": False, "error": "empty command"}
        cmd, *args = parts
        if cmd == "status":
            return {"ok": True, "status": self.status()}
        if cmd == "apply_scene":
            if len(args) != 2:
                return {"ok": False, "error": "usage: apply_scene <zone> <scene name>"}
            zone_name, scene_name = args
            return await self.apply_scene(zone_name, scene_name)
        return {"ok": False, "error": f"unknown command '{cmd}'"}
