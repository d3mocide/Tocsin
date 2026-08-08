from stt_worker import await_model


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_returns_immediately_when_the_model_is_already_there(tmp_path, capsys):
    model = tmp_path / "ggml-base.en.bin"
    model.write_bytes(b"x")
    clock = FakeClock()

    await_model(str(model), sleep=clock.sleep, clock=clock)

    assert clock.now == 0.0
    assert capsys.readouterr().err == ""


def test_waits_for_a_model_dropped_in_later(tmp_path):
    """The recovery `restart: on-failure` used to provide -- a model
    appearing in ./models/ starts the worker with no intervention -- has to
    survive the move to waiting in-process."""
    model = tmp_path / "ggml-base.en.bin"
    clock = FakeClock()
    polls = []

    def sleep(seconds):
        polls.append(seconds)
        clock.sleep(seconds)
        if len(polls) == 3:
            model.write_bytes(b"x")

    await_model(str(model), poll_interval_seconds=15.0, sleep=sleep, clock=clock)

    assert len(polls) == 3


def test_says_so_periodically_instead_of_waiting_silently(tmp_path, capsys):
    model = tmp_path / "ggml-base.en.bin"
    clock = FakeClock()

    def sleep(seconds):
        clock.sleep(seconds)
        if clock.now >= 600.0:
            model.write_bytes(b"x")

    await_model(
        str(model),
        poll_interval_seconds=15.0,
        reminder_interval_seconds=300.0,
        sleep=sleep,
        clock=clock,
    )

    err = capsys.readouterr().err
    assert "waiting for one" in err
    assert err.count("still waiting") == 2
    assert "appeared" in err
