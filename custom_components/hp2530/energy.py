"""Energy from power readings, accumulated in the integration itself.

Trapezoidal integration of watts over time, so a PoE port gets a kWh sensor
without a Riemann sum helper per port. No Home Assistant imports.
"""

from __future__ import annotations

from dataclasses import dataclass

# Longer than this between two readings and the interval is not counted.
# Integrating across an outage would assume the power stayed constant
# throughout, which is a guess presented as a measurement.
MAX_GAP_SECONDS = 600.0


@dataclass(slots=True)
class EnergyMeter:
    kwh: float = 0.0
    _last_watts: float | None = None
    _last_time: float | None = None

    def add(self, watts: float | None, timestamp: float) -> float:
        """Take one reading; return the running total in kWh.

        `timestamp` is in seconds on any monotonic clock. A missing reading
        ends the current run, so the gap around it is not counted. The same
        timestamp twice counts nothing the second time.
        """
        if watts is None or watts < 0:
            self._last_watts = self._last_time = None
            return self.kwh
        if self._last_watts is not None and self._last_time is not None:
            elapsed = timestamp - self._last_time
            if 0 < elapsed <= MAX_GAP_SECONDS:
                self.kwh += (self._last_watts + watts) / 2 * elapsed / 3_600_000
            elif elapsed <= 0:
                return self.kwh
        self._last_watts = watts
        self._last_time = timestamp
        return self.kwh
