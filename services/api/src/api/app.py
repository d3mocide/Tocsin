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

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import db, reference as reference_module, spectrum as spectrum_module, status as status_module, streams as streams_module
from .config import ApiConfig
from .sse import Broadcaster, format_sse


async def _default_http_get(url: str) -> str | None:
    """Injectable so `/streams` is testable without a running Icecast (and
    so tests never open a socket). Imported lazily: httpx is only needed
    for this one LAN call, and an `api` that can't reach Icecast must
    still serve every other route."""
    import httpx

    async with httpx.AsyncClient(timeout=streams_module.DEFAULT_TIMEOUT_SECONDS) as client:
        response = await client.get(url)
        if response.status_code != 200:
            return None
        return response.text


class _UpstreamAudioStream:
    """What `/stream/{mount_path}` needs from an upstream response,
    independent of whether it's a real httpx stream or a test fake --
    status code, content type, an async byte iterator, and a way to
    release both the response and the client that made it."""

    def __init__(self, status_code: int, content_type: str | None, chunks, closer) -> None:
        self.status_code = status_code
        self.content_type = content_type
        self._chunks = chunks
        self._closer = closer

    def __aiter__(self):
        return self._chunks.__aiter__()

    async def aclose(self) -> None:
        await self._closer()


async def _default_open_audio_stream(url: str) -> _UpstreamAudioStream | None:
    """Injectable so `/stream/{mount_path}` is testable without a running
    Icecast. Unlike `_default_http_get`, this streams rather than buffers
    the response -- a live audio feed has no end, so reading the whole
    body first isn't an option. Returns `None` if Icecast can't be
    reached at all (connection refused, DNS, timeout); a reachable-but-
    erroring response (404, 500) is instead returned with its real
    `status_code` so the route can tell the two apart, same split as
    `streams.fetch_icecast_status`."""
    import httpx

    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None))
    request = client.build_request("GET", url)
    try:
        response = await client.send(request, stream=True)
    except httpx.RequestError:
        await client.aclose()
        return None

    async def close() -> None:
        await response.aclose()
        await client.aclose()

    return _UpstreamAudioStream(response.status_code, response.headers.get("content-type"), response.aiter_bytes(), close)


def create_app(
    pool: db.PoolLike,
    redis_client,
    broadcaster: Broadcaster | None = None,
    static_dir: Path | None = None,
    config: ApiConfig | None = None,
    http_get=_default_http_get,
    open_audio_stream=_default_open_audio_stream,
) -> FastAPI:
    app = FastAPI(title="Tocsin API")
    app.state.pool = pool
    app.state.redis = redis_client
    app.state.broadcaster = broadcaster or Broadcaster()
    app.state.config = config
    app.state.http_get = http_get
    app.state.open_audio_stream = open_audio_stream
    app.state.reference = reference_module.load(
        config.data_dir if config else None,
        config.latitude if config else None,
        config.longitude if config else None,
    )

    mode = config.mode if config else None
    captures_dir = config.captures_dir if config else None
    icecast_base = (
        streams_module.public_base_url(config.icecast_host, config.icecast_port) if config else None
    )

    # Defaults to `*` (config.py's DEFAULT_CORS_ALLOWED_ORIGINS) -- fine for
    # the localhost/LAN use this repo has shipped for so far (design doc
    # §11, non-goals), same posture as deploy/mosquitto's and
    # deploy/icecast's default-open configs. Set CORS_ALLOWED_ORIGINS once
    # this is reachable from the internet; see .env.example. `config` is
    # only ever `None` in tests that don't care about this, so falling
    # back to the same `*` default there keeps their behavior unchanged.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_allowed_origins) if config else ["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/alerts")
    async def get_alerts(limit: int = Query(100, ge=1, le=1000), state: str | None = None):
        return await db.list_alerts(app.state.pool, limit=limit, state=state)

    @app.get("/health")
    async def get_health():
        return await db.latest_health(app.state.pool)

    @app.get("/health/history")
    async def get_health_history(
        since_seconds: int = Query(3600, ge=60, le=604_800),
        buckets: int = Query(60, ge=2, le=500),
    ):
        return await db.health_history(app.state.pool, since_seconds=since_seconds, buckets=buckets)

    @app.get("/transcripts")
    async def get_transcripts(
        limit: int = Query(100, ge=1, le=1000),
        raw_header: str | None = None,
    ):
        return await db.list_transcripts(app.state.pool, limit=limit, raw_header=raw_header)

    @app.get("/dispatches")
    async def get_dispatches(
        limit: int = Query(100, ge=1, le=1000),
        raw_header: str | None = None,
    ):
        return await db.list_dispatches(app.state.pool, limit=limit, raw_header=raw_header)

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
            "dispatch": await db.dispatch_summary(app.state.pool),
        }

    @app.get("/system")
    async def get_system():
        """Mode and the browser-facing Icecast base URL. `mode` is on its
        own endpoint rather than folded into `/stats` because the UI needs
        it before it can render anything honestly -- an empty API-source
        column means "no network by design" under offgrid and "the poller
        is broken" under hybrid, and the page cannot tell those apart
        without this."""
        return {
            "mode": mode,
            "icecast_public_url": config.icecast_public_url if config else None,
            "icecast_port": config.icecast_port if config else None,
            "captures_available": captures_dir is not None and captures_dir.is_dir(),
        }

    @app.get("/services")
    async def get_services():
        return await status_module.list_services(app.state.redis, mode)

    @app.get("/reference")
    async def get_reference():
        return app.state.reference.as_dict()

    @app.get("/streams")
    async def get_streams():
        if icecast_base is None:
            return {"icecast_reachable": False, "streams": []}
        heartbeats = await status_module.read_heartbeats(app.state.redis)
        known = streams_module.mounts_from_heartbeat(heartbeats.get("live_audio"))
        icecast = await streams_module.fetch_icecast_status(app.state.http_get, icecast_base)
        public_base = (config.icecast_public_url if config else None) or icecast_base
        return {
            "icecast_reachable": icecast is not None,
            "streams": streams_module.merge(known, icecast, public_base),
        }

    @app.get("/stream/{mount_path:path}")
    async def proxy_stream(mount_path: str):
        """Relays one Icecast mount through this process's own port,
        instead of the browser dialing Icecast directly (`streams.py`'s
        normal, cheaper path). Exists for deployments behind an external
        reverse proxy that only forwards this service's port -- set
        `ICECAST_PUBLIC_URL=/stream` (a relative path, not a host) to
        point the UI's playback URLs here; see .env.example. Off by
        default: this pins one open connection per listener for as long
        as they listen, the exact cost `streams.py`'s module docstring
        already calls out, so a LAN/direct deployment should leave
        `ICECAST_PUBLIC_URL` unset or absolute and never hit this route.

        `mount_path` is appended to the fixed internal `icecast_base`
        (`http://icecast:8000`) by plain string concatenation rather than
        `urljoin` -- a value starting `//` or containing `://` still lands
        as a *path* on that fixed host this way, not a redirect to some
        other one, so there's no open-proxy/SSRF surface here beyond what
        talking to this stack's own Icecast already allows.
        """
        if icecast_base is None:
            raise HTTPException(status_code=404, detail="icecast not configured")
        upstream = await app.state.open_audio_stream(f"{icecast_base}/{mount_path}")
        if upstream is None:
            raise HTTPException(status_code=502, detail="icecast unreachable")
        if upstream.status_code != 200:
            await upstream.aclose()
            raise HTTPException(status_code=502, detail="icecast returned an error")

        async def body():
            try:
                async for chunk in upstream:
                    yield chunk
            finally:
                await upstream.aclose()

        return StreamingResponse(
            body(),
            media_type=upstream.content_type or "application/ogg",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/captures/{name}")
    async def get_capture(name: str):
        """Serves one finished capture WAV so a transcript can be checked
        against the audio it came from -- the guard-failed ones especially,
        where the text was deliberately dropped.

        Only the basename of the requested path is used, and the result is
        re-checked to be inside `captures_dir` after resolution. `wav_path`
        reaches the browser from a Redis payload, so treating it as a
        trusted filesystem path would make this endpoint an arbitrary-file
        read on the container."""
        if captures_dir is None:
            raise HTTPException(status_code=404, detail="captures not configured")
        candidate = (captures_dir / Path(name).name).resolve()
        if candidate.parent != captures_dir.resolve() or not candidate.is_file():
            raise HTTPException(status_code=404, detail="no such capture")
        return FileResponse(candidate, media_type="audio/wav")

    @app.get("/events")
    async def stream_events():
        """One SSE stream carrying every named event type (see `sse.py`) --
        alerts, health samples, transcripts, and dispatch outcomes. Clients
        use `addEventListener(name, ...)` rather than `onmessage`, which
        only fires for unnamed events."""
        queue = app.state.broadcaster.subscribe()

        async def event_generator():
            try:
                while True:
                    event, item = await queue.get()
                    yield format_sse(event, item)
            finally:
                app.state.broadcaster.unsubscribe(queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            # Without this an intermediary (a reverse proxy someone puts
            # in front of this per design doc §9) will buffer the stream
            # and defeat the point of it being live.
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Mounted last and at "/": FastAPI/Starlette match routes in
    # registration order, so every route declared above (e.g. GET /alerts)
    # still wins over this catch-all for its exact path -- only requests
    # that don't match an API route fall through to the built web/ SPA
    # (design doc §9's "Vite + TypeScript UI", formerly its own nginx
    # container -- see web/README.md).
    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")

    return app
