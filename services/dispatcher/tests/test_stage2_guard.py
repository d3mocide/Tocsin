from dispatcher.stage2_guard import check_stage2_output


def test_valid_short_ascii_text_passes():
    result = check_stage2_output("Flash flooding possible near Johnson Creek.")
    assert result.passed is True
    assert result.reason is None


def test_empty_text_fails():
    result = check_stage2_output("")
    assert result.passed is False
    assert "empty" in result.reason


def test_newline_fails():
    result = check_stage2_output("line one\nline two")
    assert result.passed is False
    assert "newline" in result.reason


def test_carriage_return_fails():
    result = check_stage2_output("line one\rline two")
    assert result.passed is False


def test_non_ascii_fails():
    result = check_stage2_output("Flooding near Cañon City")
    assert result.passed is False
    assert "ASCII" in result.reason


def test_exceeds_max_bytes_fails():
    result = check_stage2_output("x" * 201, max_bytes=200)
    assert result.passed is False
    assert "200" in result.reason


def test_exactly_at_max_bytes_passes():
    result = check_stage2_output("x" * 200, max_bytes=200)
    assert result.passed is True
