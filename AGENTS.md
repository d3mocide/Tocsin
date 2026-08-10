# AGENTS.md

Tool-agnostic version of `CLAUDE.md` — same guidance, for any coding agent working in this
repository.

## Read this first

`docs/design/master-prompt.md` is the design specification and source of truth for this project.
Read the relevant section before making architectural changes; this file only summarizes
the rules most likely to be violated by an agent unfamiliar with the codebase.

## The one rule that overrides convenience

**Tocsin must remain fully functional with no internet connection.** Any change that adds
a hard dependency on network access for a core code path (SAME decode, local STT, stage-1
dispatch, serial Meshtastic) is a regression, not a feature. Network-only components must
be gated behind `TOCSIN_MODE=hybrid` and degrade silently in `offgrid` mode — see
`docs/design/master-prompt.md` §8.

## Build order

`docs/design/master-prompt.md` §10 lists eight ordered, independently-verifiable milestones. Prove
milestone N (tests passing, or for hardware-dependent steps, documented verification on
target hardware) before building on top of it. `docs/design/roadmap.md` has the
phase-by-phase plan (exit criteria, dependencies); `docs/design/tracking.md` is the living
status doc — update it whenever you finish or materially advance a phase.

## Service boundaries

Each `services/<name>/` directory is an independent Python project (uv-managed). Services
talk to each other over ZMQ, Redis, and HTTP as described in `docs/design/master-prompt.md`
§2 — never by importing one service's package from another. Shared reference data
(event-code tiers, FIPS mapping, SAME↔CAP mapping) lives in `data/*.yaml` / `data/*.csv`,
checked in, not hardcoded per-service.

## Signal-processing correctness

`services/sdr_rx` implements the polyphase channelizer in `docs/design/master-prompt.md` §3. The
three "implementation hazards" listed there (odd-stacked phase correction, batched FFTs,
DC blocking before channelizing) are correctness requirements, not optimizations. Changes
to `channelizer.py` must keep `uv run pytest tests/test_channelizer.py` green without
weakening its amplitude/phase assertions.

## Style

No comments unless they explain a non-obvious *why*. No speculative abstractions for
services or providers that don't exist yet. Keep comments to one line, rarely two or
three — no history, no alternatives considered. Especially in `.env.example` and
`compose.yaml`: an operator reads those first, and a wall of prose per line buries the
one thing they need.
