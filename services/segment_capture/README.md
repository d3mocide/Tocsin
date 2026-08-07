# segment-capture

Not yet implemented -- milestone 4 (`docs/design-spec.md` §10, §4).

Starts on ZCZC detect (reading from `sdr-rx`'s tmpfs ring buffer, not racing
the ZMQ stream), ends on EOM or a hard timeout, and emits a WAV artifact
plus timing metadata marking where the attention tone ends and voice
begins.
