from __future__ import annotations

import statistics
from datetime import date, timedelta

import pytest
import requests
from conftest import fake_high, fake_low

import weather
from weather import (
    OpenMeteoError,
    _baseline,
    _forecast_days,
    _month_values,
    _split,
    get_range,
    month_comparison,
)


def days(start: date, n: int) -> list[date]:
    return [start + timedelta(days=k) for k in range(n)]


# ---- smoothing / per-day values ----

def test_month_values_daily_returns_raw_values():
    daily = {d: (float(d.day), -float(d.day)) for d in days(date(2025, 4, 1), 30)}
    assert _month_values(daily, 2025, 4, 0, smooth=False) == [float(k) for k in range(1, 31)]
    assert _month_values(daily, 2025, 4, 1, smooth=False)[0] == -1.0


def test_smoothed_is_centered_7_day_mean_and_needs_the_full_window():
    # Values = day number, available Mar 29 .. Apr 20 only.
    daily = {d: (float(d.toordinal()), 0.0) for d in days(date(2025, 3, 29), 23)}
    out = _month_values(daily, 2025, 4, 0, smooth=True)
    # Apr 1 window = Mar 29 .. Apr 4, centered on Apr 1.
    assert out[0] == pytest.approx(date(2025, 4, 1).toordinal())
    assert out[16] == pytest.approx(date(2025, 4, 17).toordinal())  # window ends Apr 20
    assert out[17] is None  # Apr 18 window needs Apr 21


def test_smoothing_crosses_the_year_boundary():
    daily = {d: (1.0 if d.year == 2024 else 8.0, 0.0) for d in days(date(2024, 12, 20), 20)}
    dec31 = _month_values(daily, 2024, 12, 0, smooth=True)[30]
    assert dec31 == pytest.approx((4 * 1.0 + 3 * 8.0) / 7)  # Dec 28-31 + Jan 1-3


# ---- baseline ----

def test_baseline_mean_and_percentiles_across_years():
    years = range(2000, 2021)
    # Every day of June in year y has high = y - 2000 (0..20).
    daily = {d: (float(y - 2000), 0.0) for y in years for d in days(date(y, 5, 25), 45)}
    b = _baseline(daily, years, 6, 30, 0, smooth=False)
    q = statistics.quantiles(range(21), n=10, method="inclusive")
    assert b["mean"] == [pytest.approx(10.0)] * 30
    assert b["p10"] == [pytest.approx(q[0])] * 30
    assert b["p90"] == [pytest.approx(q[8])] * 30


def test_feb_29_baseline_uses_only_leap_years():
    years = range(2000, 2009)  # leap years: 2000, 2004, 2008
    daily = {d: (float(y), 0.0) for y in years for d in days(date(y, 1, 25), 45)}
    b = _baseline(daily, years, 2, 29, 0, smooth=False)
    assert b["mean"][27] == pytest.approx(statistics.fmean(years))  # Feb 28: all years
    assert b["mean"][28] == pytest.approx(statistics.fmean([2000, 2004, 2008]))


def test_baseline_with_a_single_year_has_no_band():
    daily = {d: (5.0, 0.0) for d in days(date(2010, 2, 20), 45)}
    b = _baseline(daily, range(2010, 2011), 3, 31, 0, smooth=False)
    assert b["mean"][0] == 5.0 and b["p10"][0] is None and b["p90"][0] is None


# ---- forecast split ----

def test_forecast_days_daily_vs_smoothed():
    fc = {date(2026, 9, 29), date(2026, 9, 30)}
    daily = _forecast_days(2026, 9, fc, smooth=False)
    smoothed = _forecast_days(2026, 9, fc, smooth=True)
    assert [k + 1 for k, f in enumerate(daily) if f] == [29, 30]
    assert [k + 1 for k, f in enumerate(smoothed) if f] == [26, 27, 28, 29, 30]  # windows touch Sep 29


def test_split_partitions_values():
    observed, forecast = _split([1.0, 2.0, 3.0, None], [False, False, True, True])
    assert observed == [1.0, 2.0, None, None]
    assert forecast == [None, None, 3.0, None]


# ---- fetching + cache ----

def test_get_range_caches_complete_years_and_refetches_the_current_year(fake_api):
    today = fake_api.today
    get_range(1.0, 2.0, date(2019, 12, 1), date(2026, 9, 15), today)
    archive = fake_api.archive_calls()
    # One request for all complete years (2019-2025), one for this year's slice.
    assert [(p["start_date"], p["end_date"]) for p in archive] == [
        ("2019-01-01", "2025-12-31"), ("2026-01-01", "2026-09-15")]

    fake_api.calls.clear()
    out = get_range(1.0, 2.0, date(2019, 12, 1), date(2026, 9, 15), today)
    assert [(p["start_date"], p["end_date"]) for p in fake_api.archive_calls()] == [("2026-01-01", "2026-09-15")]
    assert out[date(2020, 7, 4)] == (fake_high(date(2020, 7, 4)), fake_low(date(2020, 7, 4)))
    assert min(out) == date(2019, 12, 1) and max(out) == date(2026, 9, 15)


def test_get_range_clips_to_yesterday_and_fills_the_archive_lag_from_the_forecast_api(fake_api):
    today = fake_api.today
    out = get_range(1.0, 2.0, date(2026, 9, 1), date(2026, 10, 3), today)
    assert max(out) == today - timedelta(days=1)
    assert all(None not in v for v in out.values())  # lag days filled
    assert len(fake_api.forecast_calls()) == 1


def test_get_range_returns_nothing_for_the_future(fake_api):
    assert get_range(1.0, 2.0, date(2026, 10, 1), date(2026, 10, 31), fake_api.today) == {}


# ---- month_comparison ----

def test_current_month_has_observed_then_forecast(fake_api):
    r = month_comparison(42.375, -71.106, 2026, 9, 2000, 2020)
    assert r["last_date"] == "2026-09-28"
    assert r["forecast_through"] == "2026-09-30"
    high = r["daily"]["high"]
    assert high["actual"][27] == fake_high(date(2026, 9, 28)) and high["actual"][28] is None
    assert high["forecast"][28] == fake_high(date(2026, 9, 29)) and high["forecast"][27] is None
    # 7-day line reaches month end thanks to the forecast (+ Oct 1-3 from the forecast too).
    sm = r["smoothed"]["high"]
    assert sm["actual"][24] is not None and sm["actual"][25] is None
    assert all(v is not None for v in sm["forecast"][25:])
    assert r["days"] == list(range(1, 31))


def test_past_month_skips_the_forecast(fake_api):
    r = month_comparison(42.375, -71.106, 2025, 3, 2000, 2020)
    assert fake_api.forecast_calls() == []
    assert r["forecast_through"] is None
    assert all(v is None for v in r["smoothed"]["low"]["forecast"])
    assert r["daily"]["low"]["actual"][0] == fake_low(date(2025, 3, 1))


def test_today_is_the_city_local_date_not_the_servers(fake_api, monkeypatch):
    # Server (UTC) says Sep 29, but it's already Sep 30 in this city.
    fake_api.today = date(2026, 9, 30)
    monkeypatch.setattr(weather, "_utc_today", lambda: date(2026, 9, 29))
    r = month_comparison(35.676, 139.65, 2026, 9, 2000, 2020)
    assert r["last_date"] == "2026-09-29"
    assert [k + 1 for k, v in enumerate(r["daily"]["high"]["forecast"]) if v is not None] == [30]


# ---- HTTP retries / errors ----

class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None):
        self.status_code, self._payload = status, payload or {}
        self.ok = status < 400

    def json(self):
        return self._payload


@pytest.fixture
def http(monkeypatch):
    """Scripted requests.get: pops one response (or exception) per call."""
    script: list = []
    calls: list = []

    def get(url, params, timeout):
        calls.append(url)
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(weather.time, "sleep", lambda s: None)
    return script, calls


def test_get_retries_once_on_rate_limit_then_succeeds(http):
    script, calls = http
    script += [FakeResponse(429), FakeResponse(200, {"ok": 1})]
    assert weather._get("u", {}) == {"ok": 1}
    assert len(calls) == 2


def test_get_gives_a_friendly_error_when_rate_limited_twice(http):
    script, _ = http
    script += [FakeResponse(429), FakeResponse(429)]
    with pytest.raises(OpenMeteoError, match="rate-limiting"):
        weather._get("u", {})


def test_get_retries_network_errors(http):
    script, calls = http
    script += [requests.ConnectionError("boom"), FakeResponse(200, {"ok": 1})]
    assert weather._get("u", {}) == {"ok": 1}
    script += [requests.Timeout("slow"), requests.Timeout("slow")]
    with pytest.raises(OpenMeteoError, match="couldn't reach"):
        weather._get("u", {})


def test_get_does_not_retry_client_errors(http):
    script, calls = http
    script += [FakeResponse(400, {"reason": "Parameter 'latitude' is invalid"})]
    with pytest.raises(OpenMeteoError, match="HTTP 400 Parameter 'latitude' is invalid"):
        weather._get("u", {})
    assert len(calls) == 1
