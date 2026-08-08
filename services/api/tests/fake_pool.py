"""A minimal in-memory stand-in for `asyncpg.Pool`'s `execute`/`fetch`
subset -- no real Postgres in this authoring sandbox. Faithful enough for
`db.py`'s own logic: `execute()` records every statement+args (so tests
can assert on the SQL that would have run), and `fetch()` is scripted
per-test with the rows a real query would have returned, since actually
parsing/evaluating SQL is not this fake's job.
"""

from __future__ import annotations


class FakePool:
    def __init__(self, fetch_results=None):
        self.executed: list[tuple[str, tuple]] = []
        self._fetch_results = fetch_results or []
        self.fetch_calls: list[tuple[str, tuple]] = []

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "OK"

    async def fetch(self, query, *args):
        self.fetch_calls.append((query, args))
        if not self._fetch_results:
            return []
        return self._fetch_results.pop(0)
