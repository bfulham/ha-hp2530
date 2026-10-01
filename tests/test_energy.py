"""The kWh accumulator."""

from __future__ import annotations

import pytest

from custom_components.hp2530.energy import MAX_GAP_SECONDS, EnergyMeter


def test_trapezoid() -> None:
    meter = EnergyMeter()
    assert meter.add(6.0, 0) == 0
    # 6 W then 8 W over six minutes averages 7 W: 0.7 Wh
    assert meter.add(8.0, 360) == pytest.approx(0.0007)


def test_constant_power_for_a_day() -> None:
    meter = EnergyMeter()
    for second in range(0, 86_400 + 1, 30):
        meter.add(40.0, second)
    assert meter.kwh == pytest.approx(0.96)


def test_continues_from_a_restored_total() -> None:
    meter = EnergyMeter(kwh=1.5)
    meter.add(10.0, 0)
    assert meter.add(10.0, 360) == pytest.approx(1.501)


def test_missing_reading_is_a_gap() -> None:
    meter = EnergyMeter()
    meter.add(10.0, 0)
    meter.add(None, 30)
    meter.add(10.0, 60)
    # Nothing counted across the missing reading, only from 60 on
    assert meter.kwh == 0
    assert meter.add(10.0, 420) == pytest.approx(0.001)


def test_long_gap_is_not_counted() -> None:
    meter = EnergyMeter()
    meter.add(100.0, 0)
    assert meter.add(100.0, MAX_GAP_SECONDS + 1) == 0
    # ...but the reading after the gap starts a new run
    assert meter.add(100.0, MAX_GAP_SECONDS + 37) == pytest.approx(0.001)


def test_same_timestamp_counts_once() -> None:
    meter = EnergyMeter()
    meter.add(10.0, 0)
    first = meter.add(10.0, 360)
    assert meter.add(10.0, 360) == first
    assert meter.add(10.0, 720) == pytest.approx(first * 2)


def test_negative_power_is_ignored() -> None:
    meter = EnergyMeter()
    meter.add(10.0, 0)
    assert meter.add(-1.0, 30) == 0
