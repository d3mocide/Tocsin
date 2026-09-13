#!/usr/bin/env bash
# Bounces a compose service after udev sees its assigned RTL-SDR dongle
# enumerate (see 61-rtlsdr-tocsin-hotplug.rules). compose.sdr.yaml bind-mounts
# the whole `/dev/bus/usb` tree, and that mount goes stale -- missing a
# dongle that just got a new bus/device number, still listing one that's
# gone -- across a USB bus renumbering while the container keeps running.
# Restarting re-reads it fresh; sdr-rx's own by-serial selection
# (SDR_RX_DEVICES, capture.py) does the rest.
#
# Runs detached from the udev worker (see the RUN+= line in the .rules
# file) since `docker compose restart` can take a few seconds and udev
# workers are not meant to block on that.
set -u

service="${1:?usage: rtlsdr-hotplug.sh <compose-service>}"
cd /opt/Tocsin || exit 1

lock="/run/lock/rtlsdr-hotplug-${service}.lock"
exec 9>"$lock"
flock -n 9 || exit 0  # a restart for this service is already in flight

if [ -z "$(docker compose ps -q "$service" 2>/dev/null)" ]; then
  exit 0  # stack isn't up yet -- nothing to bounce
fi

docker compose restart "$service" >>/var/log/rtlsdr-hotplug.log 2>&1
