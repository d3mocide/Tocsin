# No official Icecast image exists on Docker Hub (checked before adding
# this) -- building our own from Debian's icecast2 package, consistent with
# how sdr-rx and same_decoder pull SoapySDR/multimon-ng from apt, rather
# than depending on an unverified third-party image.
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
# gettext-base is only for envsubst, which entrypoint.sh uses to render
# icecast.xml's ${ICECAST_PORT} -- Icecast reads its listen port from the
# XML and nowhere else.
RUN apt-get update && apt-get install -y --no-install-recommends \
        icecast2 \
        gettext-base \
    && rm -rf /var/lib/apt/lists/*

# icecast.xml here is the template the entrypoint renders from; it also
# gives the image a working default so it runs standalone (e.g. `docker
# build` + `docker run` without compose), where ICECAST_PORT is unset and
# the entrypoint falls back to 8000.
COPY icecast.xml /etc/icecast2/icecast.xml
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Documentation only, and necessarily static -- EXPOSE can't read a runtime
# env var. The port actually listened on is ICECAST_PORT; compose.yaml
# publishes that, not this.
EXPOSE 8000

# icecast2 refuses to start as root (a built-in safety check, not something
# a <changeowner> directive is needed to avoid) unless explicitly told
# otherwise. The Debian package already creates a dedicated `icecast2`
# system user with correct ownership on /var/log/icecast2. Note this caps
# ICECAST_PORT at the unprivileged range: an unprivileged user cannot bind
# below 1024, so a port there needs the container run as root (which
# icecast2 itself then refuses) rather than just a different env var.
USER icecast2

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
