#!/bin/sh
# Renders /etc/icecast2/icecast.xml's ${ICECAST_PORT} placeholder and starts
# Icecast on the result.
#
# Icecast has no env-var configuration of its own -- the listen port is only
# ever read from the XML -- so a configurable port means substituting before
# start. The rendered copy goes to /tmp because this runs as the unprivileged
# `icecast2` user (see Dockerfile) and /etc/icecast2 is root-owned.
#
# envsubst is given an explicit variable list so nothing else in the config
# that happens to look like a shell expansion (a password containing `$`,
# say) is eaten silently.
set -eu

ICECAST_PORT="${ICECAST_PORT:-8000}"
export ICECAST_PORT

envsubst '${ICECAST_PORT}' < /etc/icecast2/icecast.xml > /tmp/icecast.xml

echo "icecast: listening on port ${ICECAST_PORT}" >&2
exec icecast2 -c /tmp/icecast.xml "$@"
