#!/bin/bash
# fusion runs in both offgrid and hybrid; nws-poller is hybrid-only and
# used to be its own compose service, gated by `profiles: [hybrid]`
# (design doc §8) -- now that it shares this container, TOCSIN_MODE is
# the gate instead, checked here at container start rather than at
# compose-up time. Off-grid, this block simply never runs, same end
# result as nws-poller not being started at all.
if [ "$TOCSIN_MODE" = "hybrid" ]; then
    (
        cd /app/nws_poller || exit 1
        # Self-restarting, not a single `uv run nws-poller`: a bad/missing
        # NWS_POLLER_USER_AGENT or _AREAS makes it exit 1 immediately (see
        # nws_poller/__init__.py), and that must not take fusion's own
        # process down with it -- fusion is the container's foreground
        # process below and owns the container's exit status.
        while true; do
            uv run nws-poller || echo "entrypoint: nws-poller exited (code $?), retrying in 5s" >&2
            sleep 5
        done
    ) &
fi

cd /app/fusion || exit 1
# exec, not a third backgrounded job: fusion becomes PID 1, so `docker
# stop`'s SIGTERM reaches it directly and the container's exit status is
# fusion's -- matching its prior standalone-container restart semantics.
# The kernel tears down the nws-poller subshell (if any) along with the
# rest of this PID namespace when PID 1 exits; nothing to wait() for.
exec uv run fusion
