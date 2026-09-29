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
from datetime import date, timedelta

import requests
from flask import Flask, jsonify, render_template, request

from weather import month_comparison

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
    if not 1 <= month <= 12 or base_start > base_end or base_start < 1941 or year > (date.today() + timedelta(days=16)).year:
        return jsonify(error="out-of-range month/year/baseline"), 400
    try:
        return jsonify(month_comparison(lat, lon, year, month, base_start, base_end))
    except requests.RequestException as e:
        return jsonify(error=f"Open-Meteo request failed: {e}"), 502


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5057)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    if not args.no_open:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    app.run(port=args.port)
