"""Browser tests: the real page against the Flask app, with Open-Meteo faked on both sides
(server-side data via conftest's fake; the page's own geocoding calls via Playwright routing).
Plotly still loads from its CDN, so these need internet access."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, expect, sync_playwright
from werkzeug.serving import make_server

import app as app_module
from conftest import install_fake

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
KEYS = [f"{k}.{kind}" for k in ("high", "low") for kind in ("actual", "forecast", "mean", "band")]

PLACES = {
    "phoenix": {"name": "Phoenix", "admin1": "Arizona", "country": "United States", "country_code": "US",
                "latitude": 33.448, "longitude": -112.074},
    "istanbul": {"name": "Istanbul", "admin1": "Istanbul", "country": "Republic of Türkiye", "country_code": "TR",
                 "latitude": 41.014, "longitude": 28.95},
}


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def server(monkeypatch, tmp_path):
    # The browser runs in UTC too, so its "this month" matches the fake's today.
    install_fake(monkeypatch, tmp_path, datetime.now(timezone.utc).date())
    srv = make_server("127.0.0.1", 0, app_module.app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/"
    srv.shutdown()


def fake_geocode(route):
    name = parse_qs(urlparse(route.request.url).query)["name"][0].lower()
    results = [p for key, p in PLACES.items() if key.startswith(name)]
    route.fulfill(content_type="application/json", body=json.dumps({"results": results}))


@pytest.fixture
def page(browser, server):
    ctx = browser.new_context(timezone_id="UTC", viewport={"width": 1400, "height": 900})
    pg = ctx.new_page()
    errors: list = []
    pg.on("pageerror", lambda e: errors.append(e))
    pg.route("https://geocoding-api.open-meteo.com/**", fake_geocode)
    pg.goto(server)
    wait_loaded(pg)
    yield pg
    ctx.close()
    assert errors == []


def wait_loaded(pg: Page):
    expect(pg.locator("#status")).to_be_hidden()
    expect(pg.locator("#legend input").first).to_be_visible()


def add_city(pg: Page, query: str):
    pg.fill("#loc", query)
    pg.locator("#results li[data-i]").first.dispatch_event("mousedown")
    wait_loaded(pg)


def shown(pg: Page) -> set[str]:
    return {k for k in KEYS if pg.locator(f'input[data-k="{k}"]').count() and pg.is_checked(f'input[data-k="{k}"]')}


def query(pg: Page) -> dict:
    return parse_qs(urlparse(pg.url).query)


def test_defaults(page):
    now = datetime.now(timezone.utc)
    expect(page.locator("#title")).to_contain_text(f"{MONTHS[now.month - 1]} {now.year}")
    expect(page.locator("#mode .on")).to_have_text("7-day mean")
    expect(page.locator("#units .on")).to_have_text("°F")
    expect(page.locator("#chips")).to_have_text("Cambridge, MA")
    assert query(page)["view"] == ["smoothed"]
    assert shown(page) == set(KEYS)  # current month -> forecast rows exist too


def test_current_month_draws_the_forecast_area(page):
    shapes = page.evaluate("document.getElementById('chart').layout.shapes")
    assert len(shapes) == 1 and shapes[0]["type"] == "rect"
    expect(page.locator("#subtitle")).to_contain_text("forecast through")


def test_second_city_autohides_all_but_averages_and_removing_it_restores(page):
    add_city(page, "Pho")
    expect(page.locator("#chips")).to_contain_text("Phoenix, AZ")
    assert shown(page) == {"high.mean", "low.mean"}
    assert len(query(page)["c"]) == 2

    page.locator("#chips button").nth(1).click()
    wait_loaded(page)
    assert shown(page) == set(KEYS)
    assert len(query(page)["c"]) == 1


def test_non_us_labels_use_short_country_names(page):
    add_city(page, "Ist")
    expect(page.locator("#chips")).to_contain_text("Istanbul, Turkey")


def test_prev_and_back_button(page):
    title = page.inner_text("#title")
    page.click("#prev")
    wait_loaded(page)
    assert page.inner_text("#title") != title
    page.go_back()
    wait_loaded(page)
    assert page.inner_text("#title") == title


def test_last_view_is_restored_on_a_bare_url_and_reset_restores_defaults(page, server):
    page.click('#mode button[data-v="daily"]')
    page.click('#units button[data-v="C"]')
    page.goto(server)
    wait_loaded(page)
    expect(page.locator("#mode .on")).to_have_text("Daily")
    expect(page.locator("#units .on")).to_have_text("°C")
    assert query(page)["view"] == ["daily"]

    page.click("#reset")
    wait_loaded(page)
    expect(page.locator("#mode .on")).to_have_text("7-day mean")
    expect(page.locator("#units .on")).to_have_text("°F")


def test_url_parsing_falls_back_to_defaults_and_round_trips(page):
    same_as_defaults = page.evaluate("""() => {
        const a = fromQuery('c=Bogus&m=2099-13&base=2020-2000&view=zzz&u=K'), d = defaults();
        return JSON.stringify(a) === JSON.stringify(d);
    }""")
    assert same_as_defaults
    add_city(page, "Pho")
    page.click('#mode button[data-v="daily"]')
    round_trip = page.evaluate("JSON.stringify(fromQuery(toQuery())) === JSON.stringify(state)")
    assert round_trip


def test_out_of_range_year_is_clamped(page):
    page.fill("#year", "2100")
    page.locator("#year").dispatch_event("change")
    wait_loaded(page)
    max_year, max_month = page.evaluate("[Math.floor(MAX_INDEX / 12), MAX_INDEX % 12 + 1]")
    assert page.input_value("#year") == str(max_year)
    assert page.input_value("#month") == str(max_month)
