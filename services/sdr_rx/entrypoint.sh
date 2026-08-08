#!/bin/bash
# `make sdr-devices` runs this image with SDR_RX_LIST_DEVICES=1 for a
# one-shot device enumeration (see Makefile) -- it wants exactly sdr-rx's
# own listing codepath, not the whole stack. `exec`, not a backgrounded
# job: this replaces the entrypoint outright and returns control to
# `docker compose run` the moment sdr-rx's main() exits, rather than
# leaving same-decoder/live-audio/segment-capture's loops below running
# forever underneath a `docker compose run --rm` that's supposed to be
# a quick diagnostic.
if [ -n "$SDR_RX_LIST_DEVICES" ]; then
    cd /app/sdr_rx || exit 1
    exec uv run sdr-rx
fi

# All four run as independent, self-restarting background processes --
# none of them owns this container's lifecycle via `exec` the way fusion
# does for nws-poller (services/fusion/entrypoint.sh), because none of the
# four is the sole "always required" process here: same-decoder,
# live-audio, and segment-capture are all designed to stay up and idle
# even when sdr-rx has no dongle configured at all (README.md's "Bring
# the stack up without a dongle first" bring-up step explicitly expects
# this). `set -m` gives each backgrounded job its own process group, so
# `cleanup` below can signal an entire service's process tree (its
# while-loop subshell, `uv`, and the real python process under it) in one
# `kill`, not just the outermost loop shell.
set -m

pids=()

# sdr-rx: on-failure semantics, not unless-stopped -- main() reports "no
# devices configured" and exits 0 as a deliberately supported state (this
# repo already found and fixed the bug class where a blanket
# always-restart policy crash-loops a container that isn't actually
# crashing -- see docs/design/tracking.md's 2026-08-08 entry on
# compose.yaml's old `restart: unless-stopped` for this exact service).
# Exit 1 (bad serial/device error) retries.
(
    cd /app/sdr_rx || exit 1
    while true; do
        uv run sdr-rx
        code=$?
        if [ "$code" -eq 0 ]; then
            echo "entrypoint: sdr-rx exited 0 (no devices configured) -- not retrying" >&2
            break
        fi
        echo "entrypoint: sdr-rx exited (code $code), retrying in 5s" >&2
        sleep 5
    done
) &
pids+=("$!")

# same-decoder, live-audio, segment-capture: unless-stopped semantics --
# always retry, no deliberate clean-exit path for any of the three (see
# each one's old, now-removed standalone Dockerfile). They connect to
# sdr-rx over localhost now that they're the same container, not
# tcp://sdr-rx:5555 -- compose.yaml sets each *_ZMQ_CONNECT accordingly.
for entry in same_decoder:same-decoder live_audio:live-audio segment_capture:segment-capture; do
    dir="/app/${entry%%:*}"
    cmd="${entry#*:}"
    (
        cd "$dir" || exit 1
        while true; do
            uv run "$cmd" || echo "entrypoint: $cmd exited (code $?), retrying in 5s" >&2
            sleep 5
        done
    ) &
    pids+=("$!")
done

# `kill -TERM -- "-$pid"`, not `kill -TERM "$pid"`: the negative PID form
# targets the whole process group `set -m` gave that job, which is what
# actually reaches the currently-running `uv run <cmd>` (and the real
# python process below it), not just the now-otherwise-orphaned loop
# shell. Without this, `docker stop` would hang the full stop-timeout and
# fall back to SIGKILL instead of shutting down promptly.
cleanup() {
    trap - TERM INT
    for pid in "${pids[@]}"; do
        kill -TERM -- "-$pid" 2>/dev/null
    done
    wait
}
trap cleanup TERM INT

wait
