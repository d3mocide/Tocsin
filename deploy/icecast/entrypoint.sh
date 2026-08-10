#!/bin/sh
# Renders /etc/icecast2/icecast.xml's ${ICECAST_PORT}/${ICECAST_SOURCE_PASSWORD}/
# ${ICECAST_ADMIN_PASSWORD} placeholders and starts Icecast on the result.
#
# Icecast has no env-var configuration of its own -- these are only ever read
# from the XML -- so configuring any of them means substituting before start.
# The rendered copy goes to /tmp because this runs as the unprivileged
# `icecast2` user (see Dockerfile) and /etc/icecast2 is root-owned.
#
# envsubst is given an explicit variable list so nothing else in the config
# that happens to look like a shell expansion (a password containing `$`,
# say) is eaten silently.
set -eu

ICECAST_PORT="${ICECAST_PORT:-8000}"
export ICECAST_PORT

# Matches services/live_audio's own ICECAST_SOURCE_PASSWORD default -- the
# two must agree, since that's what live-audio authenticates to this
# server with (see live_audio/README.md's Configuration table).
ICECAST_SOURCE_PASSWORD="${ICECAST_SOURCE_PASSWORD:-hackme}"
export ICECAST_SOURCE_PASSWORD

ICECAST_ADMIN_PASSWORD="${ICECAST_ADMIN_PASSWORD:-hackme}"
export ICECAST_ADMIN_PASSWORD

envsubst '${ICECAST_PORT} ${ICECAST_SOURCE_PASSWORD} ${ICECAST_ADMIN_PASSWORD}' \
    < /etc/icecast2/icecast.xml > /tmp/icecast.xml

echo "icecast: listening on port ${ICECAST_PORT}" >&2
exec icecast2 -c /tmp/icecast.xml "$@"
