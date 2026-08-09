.PHONY: help up-offgrid up-hybrid dev dev-ui dev-stack down bench-channelizer sdr-devices fetch-models test test-stt-remote

.DEFAULT_GOAL := help

# Bare `make` prints this instead of starting the stack -- up-offgrid used to
# be the default goal (first target wins), which meant a bare `make` silently
# ran `docker compose up --build`.
help:
	@echo "Tocsin -- available make targets:"
	@echo ""
	@printf "  %-17s %s\n" "dev-ui" "Start frontend UI dev server with rich mock data (no Docker required)"
	@printf "  %-17s %s\n" "dev-stack" "Start full hybrid Docker stack for local dev (no SDR/mesh hardware required)"
	@printf "  %-17s %s\n" "up-offgrid" "Start the stack in offgrid mode (no network dependency)"
	@printf "  %-17s %s\n" "up-hybrid" "Start the stack in hybrid mode (adds network-only components)"
	@printf "  %-17s %s\n" "down" "Stop the stack"
	@printf "  %-17s %s\n" "test" "Run the test suite for every service that has one"
	@printf "  %-17s %s\n" "test-stt-remote" "Test remote Whisper HTTP transcription endpoint"
	@printf "  %-17s %s\n" "sdr-devices" "List rtlsdr device serials, for setting SDR_RX_DEVICES"
	@printf "  %-17s %s\n" "bench-channelizer" "Run the channelizer CPU throughput benchmark"
	@printf "  %-17s %s\n" "fetch-models" "Pre-stage STT model weights into ./models/ (offgrid-required)"
	@echo ""
	@echo "See README.md and docs/design/master-prompt.md for details."

# offgrid and hybrid are the two *deployment* modes -- both assume the SDR is
# attached, so both must map the USB bus. That mapping lives in
# compose.sdr.yaml, and `docker compose` picks its overlay list up from
# COMPOSE_FILE in .env -- which is also the single switch for the *mesh*
# overlay, so these targets can't just pass a fixed `-f` list without silently
# dropping a user's Meshtastic node. Read what .env asks for and append the SDR
# overlay if it's absent instead. An .env written before compose.sdr.yaml
# existed otherwise brings the stack up with no passthrough at all, and sdr-rx
# reports dongles it can't open (`rtlsdr_get_device_usb_strings failed`,
# `rtlsdr_get_index_by_serial - -3`) rather than anything naming the real cause.
# The dev-* targets below are the only hardware-free path, by design.
ENV_COMPOSE_FILE := $(shell sed -n 's/^[[:space:]]*COMPOSE_FILE[[:space:]]*=[[:space:]]*//p' .env 2>/dev/null | tail -1)
# compose.yaml alone is what `docker compose` itself defaults to when .env is
# absent or says nothing -- don't invent a mesh overlay nobody asked for.
BASE_COMPOSE_FILE := $(if $(ENV_COMPOSE_FILE),$(ENV_COMPOSE_FILE),compose.yaml)
SDR_COMPOSE_FILE := $(if $(findstring compose.sdr.yaml,$(BASE_COMPOSE_FILE)),$(BASE_COMPOSE_FILE),$(BASE_COMPOSE_FILE):compose.sdr.yaml)

# TOCSIN_MODE selects the compose profile; see docs/design/master-prompt.md §1, §8.
# COMPOSE_FILE is exported here rather than left to .env because a shell
# environment value takes precedence over .env's, which is what lets the
# append above actually win.
up-offgrid:
	TOCSIN_MODE=offgrid COMPOSE_FILE=$(SDR_COMPOSE_FILE) docker compose --profile offgrid up --build

up-hybrid:
	TOCSIN_MODE=hybrid COMPOSE_FILE=$(SDR_COMPOSE_FILE) docker compose --profile hybrid up --build

# Frontend-only dev server with realistic mock data & live SSE events (starts in < 1s)
dev-ui:
	cd web && npm run dev

dev: dev-ui

# Full hybrid docker stack with no hardware attached. Explicit `-f compose.yaml`
# so it ignores COMPOSE_FILE entirely: this is the one target that must come up
# on a machine with neither a dongle nor a mesh node (and on Windows/Mac, where
# /dev/bus/usb doesn't exist and Docker refuses to start a container whose
# `devices:` host path is missing). sdr-rx runs here with no SDR_RX_DEVICES and
# exits 0 -- same-decoder, live-audio, and segment-capture keep running.
dev-stack:
	TOCSIN_MODE=hybrid docker compose -f compose.yaml --profile hybrid up --build

up-dev: dev-stack


# Both profiles, always. Every service in compose.yaml declares
# `profiles:`, and a profiled service is not selected unless its profile is
# active -- so a bare `docker compose down` matched nothing and exited 0
# having stopped nothing, whichever mode was actually up. Naming both here
# means one `make down` tears down the stack regardless of how it started.
# --remove-orphans also clears containers left behind by an earlier
# compose.yaml (e.g. the retired standalone web/nginx service).
# Same COMPOSE_FILE the up-* targets use, so tear-down sees exactly the service
# set bring-up created. Safe on a machine with no USB bus: `down` never starts a
# container, so an unsatisfiable `devices:` mapping is only ever parsed here.
down:
	COMPOSE_FILE=$(SDR_COMPOSE_FILE) docker compose --profile offgrid --profile hybrid down --remove-orphans

# CPU throughput benchmark for the channelizer, per docs/design/master-prompt.md §6
# ("to be benchmarked rather than trusted") and hazard #2 in §3.
bench-channelizer:
	cd services/sdr_rx && uv sync && uv run python bench_channelizer.py

# List rtlsdr device serials SoapySDR can see, for setting SDR_RX_DEVICES
# (services/sdr_rx/README.md "Configuration") without guessing. Runs inside
# the sdr-rx image so it sees the same SoapySDR install the real service
# will use; requires the dongle plugged in and the host prerequisites in
# that README already done (module blacklist, udev rule).
# Explicit `-f`, not $(SDR_COMPOSE_FILE): enumerating dongles needs exactly the
# base file plus the USB passthrough and nothing else, so this diagnostic works
# the same whether or not .env exists and never drags in the mesh overlay's
# serial-device mapping, which has nothing to do with finding an RTL-SDR.
sdr-devices:
	docker compose -f compose.yaml -f compose.sdr.yaml build sdr-rx
	docker compose -f compose.yaml -f compose.sdr.yaml run --rm -e SDR_RX_LIST_DEVICES=1 sdr-rx

# Pre-stage STT model weights into ./models/ (bind-mounted read-only into
# stt-worker, see compose.yaml) while network is still available -- offgrid
# means pre-staged, never download-on-first-boot (docs/design/master-prompt.md
# §8). Defaults to base.en, master-prompt.md §6's suggested off-grid default;
# override with `make fetch-models STT_MODEL=small.en` for hybrid-local, and
# set STT_WORKER_MODEL_FILE to match if it's not base.en.
STT_MODEL ?= base.en
fetch-models:
	mkdir -p models
	curl -fL -o models/ggml-$(STT_MODEL).bin \
		https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$(STT_MODEL).bin
	@echo "fetch-models: models/ggml-$(STT_MODEL).bin ready."
	@echo "If STT_MODEL isn't base.en, also set STT_WORKER_MODEL_FILE=ggml-$(STT_MODEL).bin (see services/stt_worker/README.md)."

# Run the test suite for every service that has one.
test:
	cd services/sdr_rx && uv sync && uv run pytest
	cd services/same_decoder && uv sync && uv run pytest
	cd services/live_audio && uv sync && uv run pytest
	cd services/segment_capture && uv sync && uv run pytest
	cd services/stt_worker && uv sync && uv run pytest
	cd services/nws_poller && uv sync && uv run pytest
	cd services/fusion && uv sync && uv run pytest
	cd services/dispatcher && uv sync && uv run pytest
	cd services/api && uv sync && uv run pytest
	cd web && npm install && npm run build

# Diagnostic CLI tool for testing remote Whisper HTTP endpoints
test-stt-remote:
	cd services/stt_worker && uv sync && uv run python -m stt_worker.test_remote $(WAV)

