from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from .config import load_config
from .manager import DEFAULT_SOCKET_PATH, Manager
from .web import run_web_server

logger = logging.getLogger(__name__)


async def main() -> None:
    parser = argparse.ArgumentParser(description="WLED house lighting master")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "config" / "house.yaml",
    )
    parser.add_argument("--socket", default=DEFAULT_SOCKET_PATH)
    parser.add_argument("--web-host", default="0.0.0.0")
    parser.add_argument("--web-port", type=int, default=8080)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = load_config(args.config)
    manager = Manager(config, args.config)
    await manager.start_clients()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    socket_task = asyncio.create_task(manager.serve_control_socket(args.socket))
    web_task = asyncio.create_task(run_web_server(manager, args.web_host, args.web_port))
    logger.info("web UI listening on http://%s:%s", args.web_host, args.web_port)

    await stop_event.wait()
    logger.info("shutting down")
    socket_task.cancel()
    web_task.cancel()
    await manager.stop_clients()


if __name__ == "__main__":
    asyncio.run(main())
