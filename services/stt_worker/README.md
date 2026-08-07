# stt-worker

Not yet implemented -- milestone 4 (`docs/design-spec.md` §10, §6).

Pluggable transcription with a uniform 16 kHz mono s16le WAV input
contract across providers (`providers/whispercpp.py`,
`providers/faster_whisper.py`, `providers/remote_http.py`). See §6 for the
race-don't-chain selection strategy and the two preprocessing steps
(trim before inference, guard against hallucination) that matter more than
model size.
