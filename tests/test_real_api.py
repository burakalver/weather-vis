"""Against the real Open-Meteo API. Manual only: `uv run pytest -m real_api`."""

from __future__ import annotations

import pytest

import weather

pytestmark = pytest.mark.real_api


def test_cambridge_january_2024_is_plausible(monkeypatch, tmp_path):
    monkeypatch.setattr(weather, "CACHE_DIR", tmp_path)
    r = weather.month_comparison(42.375, -71.106, 2024, 1, 2000, 2020)
    highs = [v for v in r["daily"]["high"]["actual"] if v is not None]
    assert len(highs) == 31
    assert -25 < min(highs) and max(highs) < 25  # °C, Boston-area January
    mean = r["daily"]["high"]["baseline"]["mean"]
    assert all(-10 < v < 10 for v in mean)


def test_current_month_has_a_forecast(monkeypatch, tmp_path):
    monkeypatch.setattr(weather, "CACHE_DIR", tmp_path)
    today = weather._utc_today()
    r = weather.month_comparison(42.375, -71.106, today.year, today.month, 2000, 2020)
    assert r["forecast_through"] is not None
