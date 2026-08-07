# same-decoder

Not yet implemented -- milestone 2 (`docs/design/master-prompt.md` §10, §4).

Pipes the 22050 Hz stream from `sdr-rx` to `multimon-ng -t raw -a EAS -` and
parses `ZCZC` SAME headers into structured events, using the tier table in
`data/same_event_codes.yaml`.
