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
	@printf "  %-17s %s\n" "fetch-models" "Pre-stage STT model weights (not yet implemented)"
	@echo ""
	@echo "See README.md and docs/design/master-prompt.md for details."

# TOCSIN_MODE selects the compose profile; see docs/design/master-prompt.md §1, §8.
up-offgrid:
	TOCSIN_MODE=offgrid docker compose --profile offgrid up --build

up-hybrid:
	TOCSIN_MODE=hybrid docker compose --profile hybrid up --build

down:
	docker compose down

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

# Pre-stage STT model weights into a mounted volume while network is still
# available -- offgrid means pre-staged, never download-on-first-boot
# (docs/design/master-prompt.md §8). Not yet implemented: stt_worker (milestone 4)
# doesn't exist yet, so there's no model manifest to fetch against.
fetch-models:
	@echo "fetch-models: not yet implemented -- stt_worker (milestone 4) doesn't exist yet."
	@echo "See docs/design/master-prompt.md §8 and the build order in README.md."
	@exit 1

# Run the test suite for every service that has one.
test:
	cd services/sdr_rx && uv sync && uv run pytest
	cd services/same_decoder && uv sync && uv run pytest
	cd services/live_audio && uv sync && uv run pytest
