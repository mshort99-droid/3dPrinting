from __future__ import annotations

import asyncio
import json
import logging

import websockets.exceptions
from websockets.asyncio.client import ClientConnection, connect

from .config import Controller

logger = logging.getLogger(__name__)

RECONNECT_MIN_DELAY = 1.0
RECONNECT_MAX_DELAY = 30.0


class WledClient:
    """Owns a single persistent WebSocket connection to one WLED controller.

    WLED accepts a very small number of simultaneous WebSocket clients, so
    the master keeps exactly one connection per controller and reuses it for
    every command, rather than opening a connection per request.
    """

    def __init__(self, controller: Controller) -> None:
        self.controller = controller
        self.last_state: dict | None = None
        self._connection: ClientConnection | None = None
        self._stop = False

    @property
    def connected(self) -> bool:
        return self._connection is not None

    async def run(self) -> None:
        """Connect and reconnect forever until stop() is called."""
        delay = RECONNECT_MIN_DELAY
        uri = f"ws://{self.controller.host}/ws"
        while not self._stop:
            try:
                async with connect(uri, open_timeout=5) as ws:
                    self._connection = ws
                    delay = RECONNECT_MIN_DELAY
                    logger.info("%s: connected (%s)", self.controller.name, uri)
                    await self._receive_loop(ws)
            except (OSError, websockets.exceptions.WebSocketException) as exc:
                logger.warning("%s: connection error: %s", self.controller.name, exc)
            finally:
                self._connection = None
            if self._stop:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)

    async def _receive_loop(self, ws: ClientConnection) -> None:
        async for message in ws:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                logger.debug("%s: non-JSON message ignored", self.controller.name)
                continue
            # WLED also sends small acks like {"success": true} after a
            # command; only real state snapshots (which carry "state") should
            # replace what we're tracking.
            if isinstance(data, dict) and "state" in data:
                self.last_state = data

    async def send(self, command: dict) -> bool:
        if self._connection is None:
            logger.warning(
                "%s: dropping command, not connected: %s", self.controller.name, command
            )
            return False
        await self._connection.send(json.dumps(command))
        return True

    def stop(self) -> None:
        self._stop = True
