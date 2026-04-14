#!/usr/bin/env python3
"""Fetch FRED data and write data/latest.json for GitHub Pages."""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

FRED_KEY = os.environ.get("FRED_API_KEY", "").strip()
if not FRED_KEY:
    print("ERROR: FRED_API_KEY secret not found.", file=sys.stderr)
    print("Set it in: Repo → Settings → Secrets and variables → Actions → New repository secret", file=sys.stderr)
    sys.exit(1)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
NOW = datetime.now(timezone.utc)
YEAR_START = f"{NOW.year}-01-01"
TWO_WEEKS_AGO = (NOW - timedelta(days=14)).strftime("%Y-%m-%d")
OUT_PATH = Path("data/latest.json")


def fred(series_id: str, limit: int = 14, observation_start: str | None = None):
    params = {
        "series_id": series_id,
        "api_key": FRED_KEY,
        "file_type": "json",
        "sort_order": "asc",
        "limit": str(limit),
    }
    if observation_start:
        params["observation_start"] = observation_start
    url = FRED_BASE + "?" + urllib.parse.urlencode(params)

    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"ERROR {series_id}: HTTP {e.code} — {body[:400]}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"ERROR {series_id}: {e}", file=sys.stderr)
        return []

    observations = payload.get("observations", [])
    valid = [o for o in observations if o.get("value") not in (None, "", ".")]
    print(f"✓ {series_id}: {len(valid)} valid obs")
    return valid


def last_valid(observations):
    return observations[-1] if observations else None


def last_two(observations):
    return observations[-2:] if len(observations) >= 2 else observations[:]


def to_float(obs, default=0.0):
    if not obs:
        return default
    try:
        return float(obs["value"])
    except Exception:
        return default


def ticker_item(label, observations, unit="", dec=2):
    pair = last_two(observations)
    if not pair:
        print(f"WARNING {label}: no valid observations", file=sys.stderr)
        return None
    current = float(pair[-1]["value"])
    prev = float(pair[-2]["value"]) if len(pair) > 1 else None
    return {
        "label": label,
        "val": round(current, dec),
        "chg": round(current - prev, dec) if prev is not None else None,
        "chgPct": round(((current - prev) / prev) * 100, 2) if prev not in (None, 0) else None,
        "unit": unit,
        "dec": dec,
    }


print("Fetching main indicators…")
cpi_data = fred("CPIAUCSL", limit=15)
fed_data = fred("FEDFUNDS", limit=3)
rec_data = fred("RECPROUSM156N", limit=3)
sp_data = fred("SP500", limit=400, observation_start=YEAR_START)
sent_data = fred("UMCSENT", limit=3)

if len(cpi_data) < 13:
    print("ERROR: Not enough CPI data to calculate YoY inflation.", file=sys.stderr)
    sys.exit(1)
if len(sp_data) < 2:
    print("ERROR: Not enough SP500 data to calculate YTD.", file=sys.stderr)
    sys.exit(1)

cpi_last = float(cpi_data[-1]["value"])
cpi_12ago = float(cpi_data[-13]["value"])
inflation = round(((cpi_last / cpi_12ago) - 1) * 100, 2)
print(f"→ Inflation YoY: {inflation}%")

fed_obs = last_valid(fed_data)
rec_obs = last_valid(rec_data)
sent_obs = last_valid(sent_data)

sp_first = float(sp_data[0]["value"])
sp_latest = float(sp_data[-1]["value"])
sp_ytd = round(((sp_latest / sp_first) - 1) * 100, 2)
print(f"→ S&P 500 YTD: {sp_ytd}%")

print("Fetching ticker series…")
vix_data = fred("VIXCLS", limit=10, observation_start=TWO_WEEKS_AGO)
brent_data = fred("DCOILBRENTEU", limit=10, observation_start=TWO_WEEKS_AGO)
us10y_data = fred("DGS10", limit=10, observation_start=TWO_WEEKS_AGO)
gold_data = fred("GOLDAMGBD228NLBM", limit=10, observation_start=TWO_WEEKS_AGO)
silver_data = fred("SLVPRUSD", limit=10, observation_start=TWO_WEEKS_AGO)
eur_data = fred("DEXUSEU", limit=10, observation_start=TWO_WEEKS_AGO)

ticker = [
    ticker_item("SPX", sp_data, "", 2),
    ticker_item("VIX", vix_data, "", 2),
    ticker_item("BRENT", brent_data, "USD", 2),
    ticker_item("US 10Y", us10y_data, "%", 2),
    ticker_item("GOLD", gold_data, "USD", 0),
    ticker_item("SILBER", silver_data, "USD", 2),
    ticker_item("EUR/USD", eur_data, "", 4),
]
ticker = [t for t in ticker if t is not None]

output = {
    "fetchedAt": NOW.isoformat(),
    "indicators": {
        "inflation": {"value": inflation, "date": cpi_data[-1]["date"]},
        "fedRate": {"value": to_float(fed_obs), "date": fed_obs["date"] if fed_obs else ""},
        "recProb": {"value": to_float(rec_obs), "date": rec_obs["date"] if rec_obs else ""},
        "sp500": {
            "ytd": sp_ytd,
            "first": sp_first,
            "latest": sp_latest,
            "date": sp_data[-1]["date"],
        },
        "sentiment": {"value": to_float(sent_obs), "date": sent_obs["date"] if sent_obs else ""},
    },
    "ticker": ticker,
}

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
print(f"✓ Wrote {OUT_PATH} at {NOW.strftime('%Y-%m-%d %H:%M:%S UTC')}")
