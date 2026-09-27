from __future__ import annotations

import argparse
import asyncio
import json

from .manager import DEFAULT_SOCKET_PATH


async def send_command(socket_path: str, line: str) -> dict:
    reader, writer = await asyncio.open_unix_connection(socket_path)
    writer.write((line + "\n").encode())
    await writer.drain()
    response = await reader.readline()
    writer.close()
    return json.loads(response.decode())


async def main() -> None:
    parser = argparse.ArgumentParser(description="Talk to a running wledmaster daemon")
    parser.add_argument("--socket", default=DEFAULT_SOCKET_PATH)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")

    apply_scene = sub.add_parser("apply-scene")
    apply_scene.add_argument("zone")
    apply_scene.add_argument("scene")

    args = parser.parse_args()

    if args.cmd == "status":
        line = "status"
    else:
        line = f"apply_scene {args.zone} {args.scene}"

    response = await send_command(args.socket, line)
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
