# weather-vis

A month of daily high/low temperatures for up to three cities, compared with a
multi-year baseline (default 2000–2020): baseline average, 10th–90th percentile
band, and — for the current month — the forecast to month end. Defaults to a
centered 7-day mean; a daily view is one click away.

Data comes from [Open-Meteo](https://open-meteo.com/) (free, no API key):
historical values are ERA5 reanalysis (a ~9–25 km modelled grid, not station
readings), recent days and the forecast come from its forecast API.

## Run locally

Needs [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run app.py          # opens http://127.0.0.1:5057
```

The view (cities, month, baseline, toggles) lives in the URL, so views can be
bookmarked; the last one is also remembered in the browser and restored when you
open the bare address. **Reset** returns to the defaults.

## Tests

```sh
uv run playwright install chromium   # once, for the browser tests
uv run pytest                        # unit, API and browser tests (what CI runs)
uv run pytest -m real_api            # against the real Open-Meteo API -- manual only
```

The browser tests fake Open-Meteo but load Plotly from its CDN, so they need
internet access.

## Deploy

Hosted on [Render](https://render.com) from `main` via `render.yaml` (Docker,
free plan). GitHub Actions runs the tests on every push, and Render deploys only
after they pass. The free plan sleeps after ~15 min idle, so the first visit
after a while takes 30–60 s.

## Layout

- `app.py` — Flask app: the page, `/api/month`, `/healthz`
- `weather.py` — Open-Meteo fetching, on-disk cache of complete years
  (`data/cache/`), baseline stats, smoothing, forecast split
- `templates/index.html`, `static/app.js`, `static/app.css` — the page (Plotly chart)
- `tests/` — pytest; `conftest.py` holds the fake Open-Meteo
