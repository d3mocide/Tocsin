# CLAUDE.md

Guidance for Claude (or any agent) working in this repository. See `AGENTS.md` for the
tool-agnostic version of these notes, and `docs/design/master-prompt.md` for the full design
document that governs every decision here — read it before making architectural changes.

## The one rule that overrides convenience

**Tocsin must remain fully functional with no internet connection.** Any change that adds
a hard dependency on network access for a core code path (SAME decode, local STT, stage-1
dispatch, serial Meshtastic) is a regression, not a feature. Network-only components must
be gated behind `TOCSIN_MODE=hybrid` and degrade silently in `offgrid` mode — see
`docs/design/master-prompt.md` §8 for the exact connectivity contract.

## Build order

Milestones in `docs/design/master-prompt.md` §10 are ordered and each is independently verifiable.
Don't start milestone N+1's implementation assuming milestone N works — prove it first
(unit tests for signal-processing stages, recorded fixtures for decode/correlation logic).
`docs/design/roadmap.md` expands each milestone into a phase with exit criteria and
dependencies; `docs/design/tracking.md` is the living status doc — update it (status,
per-phase notes, and the Session Log) whenever you finish or materially advance a phase.

## Working in `services/`

Each service under `services/` is an independent Python project (uv-managed:
`pyproject.toml` + `uv.lock`, src layout). Don't reach across service boundaries by
importing another service's package directly — they communicate over ZMQ, Redis, and HTTP
per the architecture in `docs/design/master-prompt.md` §2, not Python imports. Shared
reference data (event code tiers, FIPS mapping, SAME↔CAP mapping) lives in checked-in YAML
under `data/`, not duplicated per-service.

Within a service:

```sh
cd services/<name>
uv sync
uv run pytest
```

## Signal-processing correctness

Code under `services/sdr_rx` implements the polyphase channelizer described in
`docs/design/master-prompt.md` §3. The three "implementation hazards" called out there (odd-stacked
phase correction, batched FFTs, DC blocking before channelizing) are not optional
optimizations — omitting any of them produces a channelizer that passes a casual smoke test
and fails in the field. If you touch `channelizer.py`, re-run
`uv run pytest tests/test_channelizer.py` and don't weaken the swept-tone amplitude/phase
assertions to make a change pass — fix the implementation instead.

## Data files

`data/same_event_codes.yaml`, `data/same_to_cap.yaml`, and `data/fips.csv` are checked-in
reference data, not code. NWS revises the event code list periodically — see
`docs/design/master-prompt.md` §12 for the standing "confirm against current NWS list" item.

## Comments and abstractions

Default to no comments; when you do write one, explain a non-obvious *why* (a hidden
invariant, a hazard from the design doc, a workaround), not what the code does. Don't
build abstractions for services or providers that don't exist yet — `stt_worker`'s
provider interface, for instance, should stay concrete until there are two real providers
to generalize from, not before.

Keep comments short — one line, rarely two or three for something that genuinely needs it.
Skip the surrounding history and alternatives considered; state the current reason only.
This matters most in `.env.example` and `compose.yaml`: they're what an operator reads
first, and a wall of prose per line buries the one thing they need (the value to set or the
gotcha to avoid).
