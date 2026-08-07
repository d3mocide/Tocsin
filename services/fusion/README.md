# fusion

Not yet implemented -- milestone 5 (`docs/design-spec.md` §10, §5).

Correlates SAME/NWR events with NWS CAP alerts using the mapping in
`data/same_to_cap.yaml`, without hard-merging the two sources -- one
`Alert` with a `sources[]` array and an `RF_ONLY` / `API_ONLY` /
`CONFIRMED` state. Confidence must be mode-relative (§5): deployment mode
is an input to the confidence calculation, not just to which sources are
active.
