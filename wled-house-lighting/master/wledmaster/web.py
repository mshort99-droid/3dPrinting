from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp import web

from .manager import Manager

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(manager: Manager) -> web.Application:
    app = web.Application()
    app["manager"] = manager

    async def get_state(request: web.Request) -> web.Response:
        return web.json_response(manager.dashboard_state())

    async def get_effects(request: web.Request) -> web.Response:
        return web.json_response(manager.effects_meta())

    async def apply_scene(request: web.Request) -> web.Response:
        zone = request.match_info["zone"]
        scene = request.match_info["scene"]
        result = await manager.apply_scene(zone, scene)
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def toggle_power(request: web.Request) -> web.Response:
        zone = request.match_info["zone"]
        result = await manager.toggle_zone_power(zone)
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def set_brightness(request: web.Request) -> web.Response:
        zone = request.match_info["zone"]
        body = await request.json()
        result = await manager.set_zone_brightness(zone, body.get("bri", 128))
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def preview(request: web.Request) -> web.Response:
        zone = request.match_info["zone"]
        action = await request.json()
        result = await manager.preview(zone, action)
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def save_scene(request: web.Request) -> web.Response:
        zone = request.match_info["zone"]
        scene = request.match_info["scene"]
        body = await request.json()
        result = manager.save_scene(zone, scene, body.get("actions", []))
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def rename_scene(request: web.Request) -> web.Response:
        zone = request.match_info["zone"]
        scene = request.match_info["scene"]
        body = await request.json()
        result = manager.rename_scene(zone, scene, body.get("new_name", ""))
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def delete_scene(request: web.Request) -> web.Response:
        zone = request.match_info["zone"]
        scene = request.match_info["scene"]
        result = manager.delete_scene(zone, scene)
        return web.json_response(result, status=200 if result.get("ok") else 400)

    def _asset_url(name: str) -> str:
        # Cache-bust static assets with their own mtime, so a phone that
        # cached an old app.js/style.css picks up a deploy immediately
        # instead of needing a manual hard-refresh (bit us more than once).
        try:
            version = int((STATIC_DIR / name).stat().st_mtime)
        except OSError:
            version = 0
        return f"/static/{name}?v={version}"

    async def index(request: web.Request) -> web.Response:
        html = (STATIC_DIR / "index.html").read_text()
        html = html.replace("/static/style.css", _asset_url("style.css"))
        html = html.replace("/static/app.js", _asset_url("app.js"))
        # The HTML shell itself must never be cached, or the browser won't
        # even see the new asset URLs above after a deploy.
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})

    app.router.add_get("/", index)
    app.router.add_get("/api/state", get_state)
    app.router.add_get("/api/effects", get_effects)
    app.router.add_post("/api/zones/{zone}/preview", preview)
    app.router.add_post("/api/zones/{zone}/toggle-power", toggle_power)
    app.router.add_post("/api/zones/{zone}/brightness", set_brightness)
    app.router.add_post("/api/zones/{zone}/scenes/{scene}/apply", apply_scene)
    app.router.add_post("/api/zones/{zone}/scenes/{scene}", save_scene)
    app.router.add_post("/api/zones/{zone}/scenes/{scene}/rename", rename_scene)
    app.router.add_delete("/api/zones/{zone}/scenes/{scene}", delete_scene)
    app.router.add_static("/static", STATIC_DIR)

    return app


async def run_web_server(manager: Manager, host: str, port: int) -> None:
    app = create_app(manager)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
