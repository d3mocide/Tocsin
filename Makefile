.PHONY: up-offgrid up-hybrid down bench-channelizer fetch-models test

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
