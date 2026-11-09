import pytest

from circuit_bench.bench_core import contracts as c


def test_envelope_shape_and_validation():
    env = c.envelope("pins.check", "ok", {"x": 1}, checks=[c.check("a", "passed")],
                     warnings=[c.warning("laser_safety", "danger", "eyes")],
                     assumptions=[c.assumption("v_be", "0.7 V", "typical")],
                     sources=[{"id": "s", "title": "t", "url": None, "retrieved": "2026-11-05"}])
    assert c.validate_envelope(env) == []
    assert env["ok"] is True and env["error"] is None and env["simulated"] is False


def test_fail_envelope():
    env = c.fail("board.flash", "flash_disabled", "flashing is off", "enable allow_flash")
    assert env["ok"] is False
    assert env["error"] == {"code": "flash_disabled", "message": "flashing is off", "hint": "enable allow_flash"}
    assert c.validate_envelope(env) == []


@pytest.mark.parametrize("bad", [
    lambda: c.envelope("nope.action", "x"),
    lambda: c.check("a", "ok"),
    lambda: c.warning("w", "high", "x"),
    lambda: c.BenchError("made_up", "x"),
])
def test_unknown_vocabulary_is_rejected(bad):
    with pytest.raises(ValueError):
        bad()


def test_from_error():
    err = c.BenchError("tool_missing", "pio not found", "install PlatformIO")
    env = c.from_error("board.build", err)
    assert env["error"]["code"] == "tool_missing" and env["summary"] == "pio not found"


@pytest.mark.parametrize(("value", "unit", "digits", "text"), [
    (0.0026, "A", 3, "2.60 mA"),
    (0.00676, "W", 3, "6.76 mW"),
    (1000, "Ω", 3, "1.00 kΩ"),
    (4700, "Ω", 2, "4.7 kΩ"),
    (0, "A", 3, "0 A"),
    (0.99996, "A", 3, "1.00 A"),
    (3.3, "V", 3, "3.30 V"),
    (-0.0125, "A", 3, "-12.5 mA"),
    (2.2e-9, "F", 2, "2.2 nF"),
    (100e-12, "F", 3, "100 pF"),
    (5.1, "x", 2, "5.1 x"),
    (12.5, "%", 3, "12.5 %"),
])
def test_qty_display(value, unit, digits, text):
    q = c.qty(value, unit, digits)
    assert q == {"value": value, "unit": unit, "display": text}


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "1"])
def test_qty_rejects_non_numbers(bad):
    with pytest.raises(ValueError):
        c.qty(bad, "A")


def test_validate_envelope_reports_problems():
    assert c.validate_envelope([]) == ["envelope is not an object"]
    env = c.envelope("doctor.run", "ok")
    env["checks"] = [{"id": "x", "status": "maybe"}]
    assert any("bad check" in p for p in c.validate_envelope(env))
