# dispatcher

Not yet implemented -- milestones 6-7 (`docs/design/master-prompt.md` §10, §7).

Two-stage emission: stage 1 fires at T+0 straight from the SAME header
(deterministic, zero dependencies), stage 2 enriches Tier A alerts with an
LLM-compressed impact clause after STT completes, with hard guards (3s
timeout, circuit breaker, output validation) so a stage-2 failure never
blocks stage-1 delivery. Egress in `egress/{meshtastic_serial,
meshtastic_mqtt,mqtt}.py`, keyed on Meshtastic ack rather than connection
state, with a Redis-persisted idempotency key and an airtime rate budget.
