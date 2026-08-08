# No official Icecast image exists on Docker Hub (checked before adding
# this) -- building our own from Debian's icecast2 package, consistent with
# how sdr-rx and same_decoder pull SoapySDR/multimon-ng from apt, rather
# than depending on an unverified third-party image.
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        icecast2 \
    && rm -rf /var/lib/apt/lists/*

# icecast.xml is bind-mounted at runtime (compose.yaml), same pattern as
# deploy/mosquitto's config -- this COPY just gives the image a working
# default so it also runs standalone (e.g. `docker build` + `docker run`
# without compose).
COPY icecast.xml /etc/icecast2/icecast.xml

EXPOSE 8000

# icecast2 refuses to start as root (a built-in safety check, not something
# a <changeowner> directive is needed to avoid) unless explicitly told
# otherwise. The Debian package already creates a dedicated `icecast2`
# system user with correct ownership on /var/log/icecast2 -- port 8000 is
# unprivileged, so running as that user needs no other changes.
USER icecast2

CMD ["icecast2", "-c", "/etc/icecast2/icecast.xml"]
