"""E series (IEC 60063) tables and nearest()."""
import pytest

from circuit_bench.bench_core import eseries
from circuit_bench.bench_core.contracts import BenchError

E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5,
       8.2, 9.1]


def test_tables():
    assert eseries.values("E12") == E12
    assert eseries.values("E24") == E24
    assert eseries.values("E6") == [1.0, 1.5, 2.2, 3.3, 4.7, 6.8]
    assert set(eseries.values("E12")) <= set(E24) and set(eseries.values("E6")) <= set(E24)
    assert eseries.SERIES == ("E6", "E12", "E24")
    assert eseries.SOURCE_ID == "iec-60063"


@pytest.mark.parametrize(("value", "series", "mode", "want"), [
    (130.0, "E12", "up", 150.0),
    (130.0, "E24", "up", 130.0),
    (130.0, "E12", "down", 120.0),
    (130.0, "E12", "near", 120.0),
    (150.0, "E12", "up", 150.0),
    (150.0000000001, "E12", "up", 150.0),  # float noise counts as equal
    (149.9999999999, "E12", "down", 150.0),
    (966.67, "E12", "up", 1000.0),
    (8300.0, "E12", "up", 10000.0),  # next decade
    (0.95, "E12", "down", 0.82),  # previous decade
    (4700.0, "E12", "near", 4700.0),
    (5100.0, "E12", "near", 4700.0),  # log distance: 5100/4700 < 5600/5100
    (5150.0, "E12", "near", 5600.0),
    (0.0047, "E12", "near", 0.0047),
    (2.6e-9, "E12", "up", 2.7e-9),
    (1.23e6, "E24", "up", 1.3e6),
    (9.5, "E24", "up", 10.0),
    (1.0, "E6", "down", 1.0),
])
def test_nearest(value, series, mode, want):
    got = eseries.nearest(value, series, mode)
    assert got == pytest.approx(want, rel=1e-12)


def test_results_are_clean_floats():
    assert eseries.nearest(0.0047, "E12", "near") == 0.0047
    assert eseries.nearest(130, "E12", "up") == 150.0
    assert eseries.nearest(2.6e-9, "E12", "up") == 2.7e-9


def test_near_tie_goes_up():
    # geometric middle between 1.0 and 1.2 in E12
    mid = (1.0 * 1.2) ** 0.5
    assert eseries.nearest(mid, "E12", "near") == 1.2


def test_series_name_is_case_insensitive():
    assert eseries.nearest(130, "e12", "up") == 150.0


def test_values_between():
    assert eseries.values_between(966.67, 11802.0, "E12") == [1000.0, 1200.0, 1500.0, 1800.0, 2200.0, 2700.0, 3300.0,
                                                               3900.0, 4700.0, 5600.0, 6800.0, 8200.0, 10000.0]
    assert eseries.values_between(1300, 1400, "E12") == []
    assert eseries.values_between(1500, 1500, "E12") == [1500.0]


@pytest.mark.parametrize(("value", "series", "mode"), [
    (0, "E12", "up"), (-1, "E12", "up"), (float("nan"), "E12", "up"), (float("inf"), "E12", "up"),
    (100, "E13", "up"), (100, "E12", "sideways"), ("100", "E12", "up"), (True, "E12", "up"),
])
def test_bad_arguments(value, series, mode):
    with pytest.raises(BenchError) as e:
        eseries.nearest(value, series, mode)
    assert e.value.code == "invalid_args"
