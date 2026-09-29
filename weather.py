"""Open-Meteo fetching (with an on-disk per-year cache) and the month-vs-baseline stats."""

from __future__ import annotations

import calendar
import json
import os
import statistics
from datetime import date, timedelta
from pathlib import Path

import requests

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_DIR = Path(__file__).parent / "data" / "cache"

# Archive (ERA5) values within this many days of today may still be revised or
# missing, so years overlapping this window are never cached.
STABLE_AFTER_DAYS = 30
# The forecast API only serves recent past days.
FORECAST_PAST_DAYS = 90
# Forecast horizon, counting today.
FORECAST_DAYS = 16
# Centered 7-day mean -> 3 days on each side.
HALF_WINDOW = 3

Daily = dict[date, tuple[float | None, float | None]]  # date -> (high, low) in °C


def _fetch(url: str, lat: float, lon: float, start: date, end: date) -> Daily:
    resp = requests.get(
        url,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": "auto",
        },
        timeout=60,
    )
    resp.raise_for_status()
    d = resp.json()["daily"]
    return {
        date.fromisoformat(t): (hi, lo)
        for t, hi, lo in zip(d["time"], d["temperature_2m_max"], d["temperature_2m_min"])
    }


def _cache_path(lat: float, lon: float, year: int) -> Path:
    return CACHE_DIR / f"{lat:.3f}_{lon:.3f}" / f"{year}.json"


def _load_year(lat: float, lon: float, year: int) -> Daily:
    raw = json.loads(_cache_path(lat, lon, year).read_text())
    return {date.fromisoformat(k): tuple(v) for k, v in raw.items()}


def _save_years(lat: float, lon: float, daily: Daily) -> None:
    by_year: dict[int, dict[str, list]] = {}
    for d, v in daily.items():
        by_year.setdefault(d.year, {})[d.isoformat()] = list(v)
    for year, rows in by_year.items():
        path = _cache_path(lat, lon, year)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a concurrent reader (another server worker) never sees a partial file.
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(rows))
        os.replace(tmp, path)


def _fetch_recent(lat: float, lon: float, start: date, end: date) -> Daily:
    """Archive data, with gaps (the archive lags ~5 days) filled from the forecast API."""
    out = _fetch(ARCHIVE_URL, lat, lon, start, end)
    gaps = [d for d, (hi, lo) in out.items() if hi is None or lo is None]
    fc_start = max(start, date.today() - timedelta(days=FORECAST_PAST_DAYS))
    if gaps and max(gaps) >= fc_start:
        fc = _fetch(FORECAST_URL, lat, lon, max(min(gaps), fc_start), end)
        for d in gaps:
            if d in fc:
                out[d] = fc[d]
    return out


def get_range(lat: float, lon: float, start: date, end: date) -> Daily:
    """Daily (high, low) °C for [start, end], clipped to yesterday."""
    yesterday = date.today() - timedelta(days=1)
    end = min(end, yesterday)
    if start > end:
        return {}

    stable_cutoff = date.today() - timedelta(days=STABLE_AFTER_DAYS)
    stable_years = [y for y in range(start.year, end.year + 1) if date(y, 12, 31) < stable_cutoff]
    missing = [y for y in stable_years if not _cache_path(lat, lon, y).exists()]
    if missing:
        # One request for the whole span of missing years.
        _save_years(lat, lon, _fetch(ARCHIVE_URL, lat, lon, date(min(missing), 1, 1), date(max(missing), 12, 31)))

    out: Daily = {}
    for y in stable_years:
        out.update(_load_year(lat, lon, y))

    recent_start = date(stable_years[-1] + 1, 1, 1) if stable_years else start
    recent_start = max(recent_start, start)
    if recent_start <= end:
        out.update(_fetch_recent(lat, lon, recent_start, end))

    return {d: v for d, v in out.items() if start <= d <= end}


def get_forecast(lat: float, lon: float, start: date, end: date) -> Daily:
    """Forecast (high, low) °C for the part of [start, end] from today to the forecast horizon."""
    start = max(start, date.today())
    end = min(end, date.today() + timedelta(days=FORECAST_DAYS - 1))
    if start > end:
        return {}
    return _fetch(FORECAST_URL, lat, lon, start, end)


def _month_values(daily: Daily, year: int, month: int, idx: int, smooth: bool) -> list[float | None]:
    """Per-day values (idx 0 = high, 1 = low) for the month, optionally a centered 7-day mean.

    A smoothed value needs all 7 days present, so the last 3 days of an
    in-progress month have no smoothed value yet.
    """
    ndays = calendar.monthrange(year, month)[1]
    first = date(year, month, 1)

    def val(d: date) -> float | None:
        v = daily.get(d)
        return v[idx] if v else None

    out = []
    for k in range(ndays):
        d = first + timedelta(days=k)
        if not smooth:
            out.append(val(d))
            continue
        window = [val(d + timedelta(days=j)) for j in range(-HALF_WINDOW, HALF_WINDOW + 1)]
        out.append(None if None in window else sum(window) / len(window))
    return out


def _baseline(daily: Daily, years: range, month: int, ndays: int, idx: int, smooth: bool) -> dict:
    """Mean / p10 / p90 across baseline years for each day of month.

    When smoothed, each year is smoothed first, so the band is the spread of
    7-day means (comparable to the smoothed selected-year line).
    Feb 29 draws only on the leap years in the baseline.
    """
    per_day: list[list[float]] = [[] for _ in range(ndays)]
    for y in years:
        for k, v in enumerate(_month_values(daily, y, month, idx, smooth)[:ndays]):
            if v is not None:
                per_day[k].append(v)

    mean, p10, p90 = [], [], []
    for vals in per_day:
        if len(vals) < 2:
            mean.append(vals[0] if vals else None)
            p10.append(None)
            p90.append(None)
            continue
        q = statistics.quantiles(vals, n=10, method="inclusive")
        mean.append(statistics.fmean(vals))
        p10.append(q[0])
        p90.append(q[8])
    return {"mean": mean, "p10": p10, "p90": p90}


def _forecast_days(year: int, month: int, fc_dates: set[date], smooth: bool) -> list[bool]:
    """Which days of the month are (daily) or lean on (smoothed: any day in the window) forecast data."""
    first = date(year, month, 1)
    half = HALF_WINDOW if smooth else 0
    return [
        any(first + timedelta(days=k + j) in fc_dates for j in range(-half, half + 1))
        for k in range(calendar.monthrange(year, month)[1])
    ]


def _split(values: list[float | None], is_fc: list[bool]) -> tuple[list, list]:
    """Split one series into observed and forecast parts."""
    observed = [None if f else v for v, f in zip(values, is_fc)]
    forecast = [v if f else None for v, f in zip(values, is_fc)]
    return observed, forecast


def month_comparison(lat: float, lon: float, year: int, month: int, base_start: int, base_end: int) -> dict:
    ndays = calendar.monthrange(year, month)[1]
    pad = timedelta(days=HALF_WINDOW)

    sel = get_range(lat, lon, date(year, month, 1) - pad, date(year, month, ndays) + pad)
    sel = {d: v for d, v in sel.items() if None not in v}
    fc = get_forecast(lat, lon, date(year, month, 1) - pad, date(year, month, ndays) + pad)
    fc = {d: v for d, v in fc.items() if d not in sel and None not in v}
    fc_dates = set(fc)
    combined = {**fc, **sel}
    base_last_day = calendar.monthrange(base_end, month)[1]
    base = get_range(lat, lon, date(base_start, month, 1) - pad, date(base_end, month, base_last_day) + pad)
    base_years = range(base_start, base_end + 1)

    in_month = [d for d in sel if d.month == month]
    fc_in_month = [d for d in fc if d.month == month]

    result = {
        "days": list(range(1, ndays + 1)),
        "last_date": max(in_month).isoformat() if in_month else None,
        "forecast_through": max(fc_in_month).isoformat() if fc_in_month else None,
    }
    for mode, smooth in (("daily", False), ("smoothed", True)):
        is_fc = _forecast_days(year, month, fc_dates, smooth)
        result[mode] = {}
        for name, idx in (("high", 0), ("low", 1)):
            actual, forecast = _split(_month_values(combined, year, month, idx, smooth), is_fc)
            result[mode][name] = {
                "actual": actual,
                "forecast": forecast,
                "baseline": _baseline(base, base_years, month, ndays, idx, smooth),
            }
    return result
