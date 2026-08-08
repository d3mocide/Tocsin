"""A minimal in-memory stand-in for the slice of the Redis Streams +
consumer-group API `redis_bus.py` actually uses -- no real Redis in this
authoring sandbox. Faithful to the two behaviors the design doc's
durability claim depends on: `">"` only ever delivers an entry once per
(stream, group, consumer), and `"0"` replays that same consumer's still-
unacked entries -- which is what makes crash recovery (`_replay_pending`)
actually testable rather than assumed.
"""

from __future__ import annotations


class FakeRedisStreams:
    def __init__(self):
        self._streams: dict[str, list[tuple[str, dict]]] = {}
        self._groups: dict[tuple[str, str], dict] = {}
        self._next_id = 1

    def xadd(self, stream, fields, maxlen=None, approximate=None):
        self._streams.setdefault(stream, [])
        entry_id = f"{self._next_id}-0"
        self._next_id += 1
        self._streams[stream].append((entry_id, dict(fields)))
        return entry_id

    def xgroup_create(self, stream, group, id="0", mkstream=False):
        self._streams.setdefault(stream, [])
        key = (stream, group)
        if key in self._groups:
            raise Exception("BUSYGROUP Consumer Group name already exists")
        start = 0 if id == "0" else len(self._streams[stream])
        self._groups[key] = {"last_delivered": start, "pel": {}}

    def xreadgroup(self, group, consumer, streams, count=None, block=None):
        result = []
        for stream, read_id in streams.items():
            key = (stream, group)
            state = self._groups[key]
            pel = state["pel"].setdefault(consumer, {})
            if read_id == ">":
                entries = self._streams[stream][state["last_delivered"] :]
                if count is not None:
                    entries = entries[:count]
                if entries:
                    state["last_delivered"] += len(entries)
                    for entry_id, fields in entries:
                        pel[entry_id] = fields
                    result.append((stream, entries))
            else:
                pending_ids = set(pel)
                pending_entries = [(eid, f) for eid, f in self._streams[stream] if eid in pending_ids]
                if pending_entries:
                    result.append((stream, pending_entries))
        return result

    def xack(self, stream, group, entry_id):
        key = (stream, group)
        for consumer_pel in self._groups[key]["pel"].values():
            consumer_pel.pop(entry_id, None)
