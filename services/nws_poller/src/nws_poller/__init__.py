"""nws-poller entrypoint: poll `api.weather.gov/alerts/active` per
configured area on an interval, publish new/updated CAP alerts to Redis
Streams for `fusion`.

hybrid-only per design doc §8 -- `compose.yaml` only defines this service
under the `hybrid` profile, so there is no offgrid code path to gate here;
this process simply never starts under `offgrid`.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

from . import heartbeat as heartbeat_module
from .client import NwsAlertsClient
from .redis_sink import LoggingCapAlertSink, RedisStreamCapAlertSink
from .service import Poller

DEFAULT_INTERVAL_SECONDS = 60.0


def _build_redis_client():
    """Built once in `main()` and shared by the CAP sink and the liveness
    heartbeat rather than each opening its own connection."""
    redis_url = os.environ.get("NWS_POLLER_REDIS_URL")
    if not redis_url:
        return None
    import redis as redis_lib

    return redis_lib.from_url(redis_url)


def _build_sink(redis_client):
    if redis_client is None:
        return LoggingCapAlertSink()
    return RedisStreamCapAlertSink(redis_client)


def main() -> None:
    user_agent = os.environ.get("NWS_POLLER_USER_AGENT")
    if not user_agent:
        print(
            "nws-poller: NWS_POLLER_USER_AGENT is required by api.weather.gov "
            "(e.g. 'tocsin (youremail@example.com)') -- refusing to start",
            file=sys.stderr,
        )
        sys.exit(1)

    areas = [a.strip() for a in os.environ.get("NWS_POLLER_AREAS", "").split(",") if a.strip()]
    if not areas:
        print(
            "nws-poller: NWS_POLLER_AREAS is empty -- nothing to poll, refusing to start",
            file=sys.stderr,
        )
        sys.exit(1)

    interval = float(os.environ.get("NWS_POLLER_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS))

    redis_client = _build_redis_client()
    client = NwsAlertsClient(user_agent=user_agent)
    poller = Poller(client, areas, sink=_build_sink(redis_client))
    heartbeat = heartbeat_module.build(redis_client)
    # A silently unreachable api.weather.gov and a genuinely quiet night
    # produce identical output from this service, so the heartbeat carries
    # last-success/last-error explicitly -- without them the status board
    # would show nws-poller as healthy right up until someone noticed no
    # CONFIRMED alerts had appeared in a week.
    last_success: str | None = None
    last_error: str | None = None
    print(f"nws-poller: polling {areas} every {interval}s", flush=True)
    while True:
        try:
            emitted = poller.poll_once()
            last_success = datetime.now(timezone.utc).isoformat()
            last_error = None
            if emitted:
                print(f"nws-poller: emitted {emitted} new/updated alert(s)", flush=True)
        except Exception as exc:
            # A single bad poll cycle (network blip, transient 5xx, a
            # malformed feature) must not crash-loop the whole process --
            # the design doc's connectivity contract (§8) treats network
            # flakiness as the expected case for every hybrid-only
            # component, not an exceptional one.
            last_error = str(exc)
            print(f"nws-poller: poll cycle failed: {exc}", file=sys.stderr)
        if heartbeat is not None:
            heartbeat.beat(areas=areas, last_success=last_success, last_error=last_error)
        time.sleep(interval)
