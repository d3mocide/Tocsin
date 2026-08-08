"""Opening the Postgres pool at startup, separated from `db.py`'s queries
because the interesting part isn't the connection -- it's telling the two
reasons it fails apart.

`timescaledb` accepts TCP connections a moment before it has finished
initializing on a cold `docker compose up`, so "connection refused" and
"the database system is starting up" are *normal* for the first few
seconds and must be waited out, not crashed on. A rejected password is the
opposite: no amount of retrying fixes it, and the restart loop it produces
buries the one line that explains what to do under a repeating asyncpg
traceback. So: retry the transient ones against a deadline, and turn the
permanent ones into a `PostgresStartupError` carrying operator-facing
instructions.
"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit

DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_RETRY_INTERVAL_SECONDS = 2.0


class PostgresStartupError(RuntimeError):
    """Message is written for whoever is reading `docker compose logs`, and
    is printed verbatim by `main()` -- no traceback."""


def _dsn_parts(dsn: str) -> tuple[str, str, str]:
    """(user, database, host:port), each falling back to its compose default
    -- this only ever feeds an error message, so an unparseable DSN must
    not itself raise."""
    try:
        parts = urlsplit(dsn)
        return (
            parts.username or "tocsin",
            parts.path.lstrip("/") or "tocsin",
            f"{parts.hostname or 'timescaledb'}:{parts.port or 5432}",
        )
    except ValueError:
        return "tocsin", "tocsin", "timescaledb:5432"


def _password_help(user: str) -> str:
    alter = f"ALTER USER {user} PASSWORD 'the-value-in-your-.env'"
    return f"""api: Postgres rejected the password for user {user!r}.
     POSTGRES_PASSWORD in .env has to match the password the `timescale-data`
     volume was initialized with. Postgres reads POSTGRES_PASSWORD only when it
     creates an empty data directory, so editing .env after the first `up`
     leaves the stored password behind and every later start fails exactly like
     this. Either restore the original value in .env, or change the stored
     password to match the new one:

       docker compose exec timescaledb psql -U {user} -c "{alter}"

     (`docker compose down -v` also clears it, by destroying stored history.)"""


def _missing_database_help(user: str, database: str) -> str:
    return f"""api: Postgres has no database named {database!r} for user {user!r}.
     The `timescale-data` volume was initialized under a different POSTGRES_DB,
     and that name is fixed at first init. Point API_POSTGRES_DB at the database
     that does exist, or `docker compose down -v` to re-initialize (destroying
     stored history)."""


def _unreachable_help(where: str, timeout_seconds: float, exc: Exception) -> str:
    return f"""api: Postgres at {where} was still unreachable after {timeout_seconds:.0f}s: {exc}
     Is the `timescaledb` service running? Check `docker compose ps timescaledb`."""


async def create_pool(
    dsn: str,
    *,
    connect=None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    retry_interval_seconds: float = DEFAULT_RETRY_INTERVAL_SECONDS,
    sleep=asyncio.sleep,
    clock=time.monotonic,
):
    """Returns a connected `asyncpg` pool, or raises `PostgresStartupError`
    with a message meant to be printed as-is. `connect` is the injection
    seam for tests; production passes nothing and gets `asyncpg`."""
    import asyncpg

    if connect is None:

        async def connect():
            return await asyncpg.create_pool(dsn=dsn)

    user, database, where = _dsn_parts(dsn)
    deadline = clock() + timeout_seconds
    while True:
        try:
            return await connect()
        except asyncpg.InvalidPasswordError as exc:
            raise PostgresStartupError(_password_help(user)) from exc
        except asyncpg.InvalidAuthorizationSpecificationError as exc:
            # Same 28xxx family as a bad password, different cause: no such
            # role, or pg_hba refusing this client outright.
            raise PostgresStartupError(
                f"api: Postgres refused authorization for user {user!r}: {exc}"
            ) from exc
        except asyncpg.InvalidCatalogNameError as exc:
            raise PostgresStartupError(_missing_database_help(user, database)) from exc
        except (OSError, asyncpg.CannotConnectNowError) as exc:
            if clock() >= deadline:
                raise PostgresStartupError(
                    _unreachable_help(where, timeout_seconds, exc)
                ) from exc
            await sleep(retry_interval_seconds)
