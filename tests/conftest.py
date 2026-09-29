"""Shared fixtures: a fake Open-Meteo so tests never touch the network (except the real_api tier)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import pytest

import weather


def fake_high(d: date) -> float:
    """Deterministic seasonal curve plus a small per-year trend, °C."""
    doy = d.timetuple().tm_yday
    return round(20 + 10 * math.sin(2 * math.pi * (doy - 110) / 365) + 0.1 * (d.year - 2000), 2)


def fake_low(d: date) -> float:
    return round(fake_high(d) - 10, 2)


@dataclass
class FakeOpenMeteo:
    """Stands in for weather._get. `today` is the city's local date; the archive
    has no values for its last `archive_lag` days, like the real one."""

    today: date
    archive_lag: int = 3
    calls: list[tuple[str, dict]] = field(default_factory=list)

    def __call__(self, url: str, params: dict) -> dict:
        self.calls.append((url, params))
        if url == weather.ARCHIVE_URL:
            start, end = date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"])
            last_available = self.today - timedelta(days=self.archive_lag + 1)
            return self._payload(start, end, available=lambda d: d <= last_available)
        if "forecast_days" in params:  # fetch_forecast: today .. horizon
            start = self.today
            end = self.today + timedelta(days=params["forecast_days"] - 1)
        else:  # recent-past gap fill
            start, end = date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"])
        return self._payload(start, end, available=lambda d: True)

    @staticmethod
    def _payload(start: date, end: date, available) -> dict:
        days = [start + timedelta(days=k) for k in range((end - start).days + 1)]
        return {"daily": {
            "time": [d.isoformat() for d in days],
            "temperature_2m_max": [fake_high(d) if available(d) else None for d in days],
            "temperature_2m_min": [fake_low(d) if available(d) else None for d in days],
        }}

    def archive_calls(self) -> list[dict]:
        return [p for u, p in self.calls if u == weather.ARCHIVE_URL]

    def forecast_calls(self) -> list[dict]:
        return [p for u, p in self.calls if u == weather.FORECAST_URL]


@pytest.fixture
def fake_api(monkeypatch, tmp_path):
    """Fake Open-Meteo with a fixed 'today' of 2026-09-29, and an empty cache dir."""
    return install_fake(monkeypatch, tmp_path, date(2026, 9, 29))


def install_fake(monkeypatch, tmp_path, today: date) -> FakeOpenMeteo:
    fake = FakeOpenMeteo(today=today)
    monkeypatch.setattr(weather, "_get", fake)
    monkeypatch.setattr(weather, "_utc_today", lambda: today)
    monkeypatch.setattr(weather, "CACHE_DIR", tmp_path / "cache")
    return fake
