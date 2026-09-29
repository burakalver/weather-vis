from __future__ import annotations

import pytest

import app as app_module
import weather


@pytest.fixture
def client():
    return app_module.app.test_client()


def month_url(**overrides) -> str:
    params = {"lat": 42.3751, "lon": -71.1056, "year": 2026, "month": 9, "base_start": 2000, "base_end": 2020}
    params.update(overrides)
    return "/api/month?" + "&".join(f"{k}={v}" for k, v in params.items() if v is not None)


def test_healthz(client):
    assert client.get("/healthz").data == b"ok"


def test_index_serves_page_with_static_assets(client):
    html = client.get("/").data.decode()
    assert "/static/app.js" in html and "/static/app.css" in html and 'integrity="sha384-' in html
    assert client.get("/static/app.js").status_code == 200


def test_month_ok(client, fake_api):
    r = client.get(month_url())
    assert r.status_code == 200
    assert set(r.json) >= {"days", "daily", "smoothed", "last_date", "forecast_through"}


def test_coordinates_are_rounded_before_fetching(client, fake_api):
    client.get(month_url(lat=42.37512345, lon=-71.10561234))
    assert {(p["latitude"], p["longitude"]) for _, p in fake_api.calls} == {(42.375, -71.106)}


@pytest.mark.parametrize("overrides, message", [
    ({"lat": None}, "bad parameters"),
    ({"lat": "abc"}, "bad parameters"),
    ({"lat": 91}, "latitude/longitude out of range"),
    ({"lon": -181}, "latitude/longitude out of range"),
    ({"month": 13}, "month/year out of range"),
    ({"year": 1900}, "month/year out of range"),
    ({"year": 2999}, "month/year out of range"),
    ({"base_start": 2021, "base_end": 2020}, "baseline years out of range"),
    ({"base_start": 1800}, "baseline years out of range"),
])
def test_bad_parameters_are_rejected(client, overrides, message):
    r = client.get(month_url(**overrides))
    assert r.status_code == 400
    assert message in r.json["error"]


def test_open_meteo_failure_is_a_502_with_its_message(client, monkeypatch):
    def fail(*a, **k):
        raise weather.OpenMeteoError("Open-Meteo is rate-limiting requests; try again in a minute")
    monkeypatch.setattr(app_module, "month_comparison", fail)
    r = client.get(month_url())
    assert r.status_code == 502
    assert "rate-limiting" in r.json["error"]
