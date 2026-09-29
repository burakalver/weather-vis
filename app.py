"""Web app: compare a month's daily high/low temperatures against a baseline period.

Usage:
    uv run app.py            # local dev: opens http://127.0.0.1:5057 in your browser
    uv run app.py --no-open

Hosted on Render (see Dockerfile / render.yaml), served by gunicorn.
"""

from __future__ import annotations

import argparse
import threading
import webbrowser
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, render_template, request

from weather import FORECAST_DAYS, OpenMeteoError, month_comparison

FIRST_YEAR = 1941  # Open-Meteo's archive starts in 1940; 1941 leaves room for the smoothing pad

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True  # page edits show up on refresh, no restart


@app.get("/healthz")
def healthz():
    return "ok"


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/month")
def api_month():
    try:
        lat = float(request.args["lat"])
        lon = float(request.args["lon"])
        year = int(request.args["year"])
        month = int(request.args["month"])
        base_start = int(request.args.get("base_start", 2000))
        base_end = int(request.args.get("base_end", 2020))
    except (KeyError, ValueError) as e:
        return jsonify(error=f"bad parameters: {e}"), 400

    # Latest month with any data: the one the forecast horizon reaches (+1 day for time zones).
    horizon = datetime.now(timezone.utc).date() + timedelta(days=FORECAST_DAYS)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify(error="latitude/longitude out of range"), 400
    if not (1 <= month <= 12 and FIRST_YEAR <= year and (year, month) <= (horizon.year, horizon.month)):
        return jsonify(error="month/year out of range"), 400
    if not FIRST_YEAR <= base_start <= base_end <= horizon.year:
        return jsonify(error="baseline years out of range"), 400

    # ~100 m precision is plenty for a ~10 km grid, and keeps near-identical
    # coordinates from creating separate cache folders.
    lat, lon = round(lat, 3), round(lon, 3)
    try:
        return jsonify(month_comparison(lat, lon, year, month, base_start, base_end))
    except OpenMeteoError as e:
        return jsonify(error=str(e)), 502


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5057)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    if not args.no_open:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    app.run(port=args.port)
