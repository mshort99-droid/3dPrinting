from __future__ import annotations

import asyncio
import json
import logging

from .config import Config, SceneAction, Zone
from .wled_client import WledClient

logger = logging.getLogger(__name__)

DEFAULT_SOCKET_PATH = "/run/wled-master/control.sock"


class Manager:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.clients: dict[str, WledClient] = {
            controller.name: WledClient(controller) for controller in config.all_controllers()
        }
        self._tasks: list[asyncio.Task] = []

    async def start_clients(self) -> None:
        for client in self.clients.values():
            self._tasks.append(asyncio.create_task(client.run()))

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

        # Group actions by controller so multiple segment actions for the same
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
                seg["col"] = [action.col]
            if action.fx is not None:
                seg["fx"] = action.fx
            if action.bri is not None:
                seg["bri"] = action.bri
            segments.append(seg)
        if segments:
            command["seg"] = segments
        return command

    def status(self) -> dict:
        return {
            name: {
                "connected": client.connected,
                "last_state": client.last_state,
            }
            for name, client in self.clients.items()
        }

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
