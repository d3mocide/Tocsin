import asyncpg
import pytest

from api.connect import PostgresStartupError, create_pool

DSN = "postgresql://tocsin:secret@timescaledb:5432/tocsin"


class FakeClock:
    """Monotonic time under test control -- `sleep` advances it, so the
    retry deadline is reached without the test actually waiting."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


async def test_returns_the_pool_on_the_first_successful_connect():
    async def connect():
        return "pool"

    assert await create_pool(DSN, connect=connect) == "pool"


async def test_retries_while_postgres_is_still_starting():
    clock = FakeClock()
    attempts = []

    async def connect():
        attempts.append(clock.now)
        if len(attempts) < 3:
            raise ConnectionRefusedError(111, "Connection refused")
        return "pool"

    pool = await create_pool(DSN, connect=connect, sleep=clock.sleep, clock=clock)

    assert pool == "pool"
    assert len(attempts) == 3


async def test_retries_cannot_connect_now_too():
    """57P03 is what Postgres answers *after* it accepts the socket but
    before it finishes initializing -- transient like a refused connection,
    not a misconfiguration."""
    clock = FakeClock()
    calls = []

    async def connect():
        calls.append(None)
        if len(calls) < 2:
            raise asyncpg.CannotConnectNowError("the database system is starting up")
        return "pool"

    assert await create_pool(DSN, connect=connect, sleep=clock.sleep, clock=clock) == "pool"


async def test_gives_up_on_an_unreachable_database_after_the_timeout():
    clock = FakeClock()

    async def connect():
        raise ConnectionRefusedError(111, "Connection refused")

    with pytest.raises(PostgresStartupError) as excinfo:
        await create_pool(
            DSN,
            connect=connect,
            timeout_seconds=10.0,
            retry_interval_seconds=2.0,
            sleep=clock.sleep,
            clock=clock,
        )

    assert "timescaledb:5432" in str(excinfo.value)
    assert clock.now >= 10.0


async def test_a_rejected_password_fails_immediately_with_instructions():
    """The whole point of separating this from the transient cases: no
    number of retries fixes a password mismatch, and the message has to
    name the stale-volume cause, since that is what produces it."""
    clock = FakeClock()
    attempts = []

    async def connect():
        attempts.append(None)
        raise asyncpg.InvalidPasswordError('password authentication failed for user "tocsin"')

    with pytest.raises(PostgresStartupError) as excinfo:
        await create_pool(DSN, connect=connect, sleep=clock.sleep, clock=clock)

    message = str(excinfo.value)
    assert len(attempts) == 1
    assert "POSTGRES_PASSWORD" in message
    assert "ALTER USER tocsin" in message
    assert clock.now == 0.0


async def test_a_missing_database_names_the_database_it_looked_for():
    async def connect():
        raise asyncpg.InvalidCatalogNameError('database "tocsin" does not exist')

    with pytest.raises(PostgresStartupError) as excinfo:
        await create_pool(DSN, connect=connect)

    assert "'tocsin'" in str(excinfo.value)


async def test_an_unknown_role_is_not_reported_as_a_bad_password():
    async def connect():
        raise asyncpg.InvalidAuthorizationSpecificationError('role "tocsin" does not exist')

    with pytest.raises(PostgresStartupError) as excinfo:
        await create_pool(DSN, connect=connect)

    message = str(excinfo.value)
    assert "refused authorization" in message
    assert "POSTGRES_PASSWORD" not in message
