from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from .config import load_config
from .manager import DEFAULT_SOCKET_PATH, Manager

logger = logging.getLogger(__name__)


async def main() -> None:
    parser = argparse.ArgumentParser(description="WLED house lighting master")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "config" / "house.yaml",
    )
    parser.add_argument("--socket", default=DEFAULT_SOCKET_PATH)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = load_config(args.config)
    manager = Manager(config)
    await manager.start_clients()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    server_task = asyncio.create_task(manager.serve_control_socket(args.socket))
    await stop_event.wait()
    logger.info("shutting down")
    server_task.cancel()
    await manager.stop_clients()


if __name__ == "__main__":
    asyncio.run(main())
