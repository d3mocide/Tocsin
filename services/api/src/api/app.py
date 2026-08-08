"""FastAPI app: REST + SSE feed over the canonical alert store (design doc
§10 milestone 8). Takes an already-constructed `pool`/`redis_client`
rather than building them itself or via a `lifespan` callback -- keeps
route logic trivially testable (pass fakes straight to `create_app`, no
async context manager to trigger or bypass in tests). Real construction
(including `db.ensure_schema` and starting the background Redis consumer
tasks) happens once in `__init__.py`'s `main()`, before this is ever
called.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import db, spectrum as spectrum_module
from .sse import Broadcaster


def create_app(
    pool: db.PoolLike,
    redis_client,
    broadcaster: Broadcaster | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Tocsin API")
    app.state.pool = pool
    app.state.redis = redis_client
    app.state.broadcaster = broadcaster or Broadcaster()

    # Personal/emergency use (design doc §11, non-goals), same posture as
    # deploy/mosquitto's and deploy/icecast's default-open configs -- not
    # meant to be exposed past localhost/LAN as shipped.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/alerts")
    async def get_alerts(limit: int = Query(100, ge=1, le=1000), state: str | None = None):
        return await db.list_alerts(app.state.pool, limit=limit, state=state)

    @app.get("/health")
    async def get_health():
        return await db.latest_health(app.state.pool)

    @app.get("/spectrum/{site}")
    async def get_spectrum(site: str):
        snapshot = await spectrum_module.get_spectrum(app.state.redis, site)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"no spectrum data for site {site!r}")
        return snapshot

    @app.get("/spectrum")
    async def get_spectrum_sites():
        return await spectrum_module.list_spectrum_sites(app.state.redis)

    @app.get("/stats")
    async def get_stats():
        counts = await db.alert_state_counts(app.state.pool)
        total = sum(counts.values())
        divergent = counts.get("RF_ONLY", 0) + counts.get("API_ONLY", 0)
        return {
            "counts": counts,
            "total": total,
            # design doc §5: "The RF_ONLY/API_ONLY divergence rate over
            # time is the best single health metric for the whole system."
            "divergence_rate": (divergent / total) if total else 0.0,
        }

    @app.get("/alerts/stream")
    async def stream_alerts():
        queue = app.state.broadcaster.subscribe()

        async def event_generator():
            try:
                while True:
                    item = await queue.get()
                    yield f"data: {json.dumps(item)}\n\n"
            finally:
                app.state.broadcaster.unsubscribe(queue)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # Mounted last and at "/": FastAPI/Starlette match routes in
    # registration order, so every route declared above (e.g. GET /alerts)
    # still wins over this catch-all for its exact path -- only requests
    # that don't match an API route fall through to the built web/ SPA
    # (design doc §9's "Vite + TypeScript UI", formerly its own nginx
    # container -- see web/README.md).
    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")

    return app
