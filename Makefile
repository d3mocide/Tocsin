.PHONY: help up-offgrid up-hybrid down bench-channelizer sdr-devices fetch-models test

.DEFAULT_GOAL := help

# Bare `make` prints this instead of starting the stack -- up-offgrid used to
# be the default goal (first target wins), which meant a bare `make` silently
# ran `docker compose up --build`.
help:
	@echo "Tocsin -- available make targets:"
	@echo ""
	@printf "  %-17s %s\n" "up-offgrid" "Start the stack in offgrid mode (no network dependency)"
	@printf "  %-17s %s\n" "up-hybrid" "Start the stack in hybrid mode (adds network-only components)"
	@printf "  %-17s %s\n" "down" "Stop the stack"
	@printf "  %-17s %s\n" "test" "Run the test suite for every service that has one"
	@printf "  %-17s %s\n" "sdr-devices" "List rtlsdr device serials, for setting SDR_RX_DEVICES"
	@printf "  %-17s %s\n" "bench-channelizer" "Run the channelizer CPU throughput benchmark"
	@printf "  %-17s %s\n" "fetch-models" "Pre-stage STT model weights into ./models/ (offgrid-required)"
	@echo ""
	@echo "See README.md and docs/design/master-prompt.md for details."

# TOCSIN_MODE selects the compose profile; see docs/design/master-prompt.md §1, §8.
up-offgrid:
	TOCSIN_MODE=offgrid docker compose --profile offgrid up --build

up-hybrid:
	TOCSIN_MODE=hybrid docker compose --profile hybrid up --build

# Both profiles, always. Every service in compose.yaml declares
# `profiles:`, and a profiled service is not selected unless its profile is
# active -- so a bare `docker compose down` matched nothing and exited 0
# having stopped nothing, whichever mode was actually up. Naming both here
# means one `make down` tears down the stack regardless of how it started.
# --remove-orphans also clears containers left behind by an earlier
# compose.yaml (e.g. the retired standalone web/nginx service).
down:
	docker compose --profile offgrid --profile hybrid down --remove-orphans

# CPU throughput benchmark for the channelizer, per docs/design/master-prompt.md §6
# ("to be benchmarked rather than trusted") and hazard #2 in §3.
bench-channelizer:
	cd services/sdr_rx && uv sync && uv run python bench_channelizer.py

# List rtlsdr device serials SoapySDR can see, for setting SDR_RX_DEVICES
# (services/sdr_rx/README.md "Configuration") without guessing. Runs inside
# the sdr-rx image so it sees the same SoapySDR install the real service
# will use; requires the dongle plugged in and the host prerequisites in
# that README already done (module blacklist, udev rule).
sdr-devices:
	docker compose build sdr-rx
	docker compose run --rm -e SDR_RX_LIST_DEVICES=1 sdr-rx

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
