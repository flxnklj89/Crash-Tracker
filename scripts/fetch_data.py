#!/usr/bin/env python3
"""Fetches economic data from FRED and writes data/latest.json."""

import json, os, urllib.request
from datetime import datetime, timezone, timedelta

FRED_KEY  = os.environ["FRED_API_KEY"]
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
NOW       = datetime.now(timezone.utc)
YEAR_START   = f"{NOW.year}-01-01"
TWO_WEEKS_AGO = (NOW - timedelta(days=14)).strftime("%Y-%m-%d")


def fred(series, limit=14, start=None):
    url = (
        f"{FRED_BASE}?series_id={series}&api_key={FRED_KEY}"
        f"&file_type=json&sort_order=desc&limit={limit}"
    )
    if start:
        url += f"&observation_start={start}"
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read())


def latest(data):
    for obs in reversed(data["observations"]):
        if obs["value"] not in (".", ""):
            return obs
    return None


def prev2(data):
    result = []
    for obs in reversed(data["observations"]):
        if obs["value"] not in (".", ""):
            result.append(obs)
            if len(result) == 2:
                break
    return result


# ── Main indicators ──────────────────────────────────────────────
print("Fetching indicators…")
cpi_data  = fred("CPIAUCSL",        14)
fed_data  = fred("FEDFUNDS",         2)
rec_data  = fred("RECPROUSM156N",    2)
sp_data   = fred("SP500",           90, YEAR_START)
sent_data = fred("UMCSENT",          2)

# CPI year-over-year
cpi_obs   = [o for o in cpi_data["observations"] if o["value"] not in (".", "")]
cpi_last  = float(cpi_obs[-1]["value"])
cpi_12ago = float(cpi_obs[max(0, len(cpi_obs) - 13)]["value"])
inflation = round(((cpi_last / cpi_12ago) - 1) * 100, 2)

fed_obs = latest(fed_data)
rec_obs = latest(rec_data)
sent_obs = latest(sent_data)

sp_obs    = sorted([o for o in sp_data["observations"] if o["value"] not in (".", "")], key=lambda x: x["date"])
sp_first  = float(sp_obs[0]["value"])
sp_latest = float(sp_obs[-1]["value"])
sp_ytd    = round(((sp_latest / sp_first) - 1) * 100, 2)


# ── Ticker series ────────────────────────────────────────────────
print("Fetching ticker…")
vix_data   = fred("VIXCLS",           4, TWO_WEEKS_AGO)
brent_data = fred("DCOILBRENTEU",     4, TWO_WEEKS_AGO)
us10y_data = fred("DGS10",            4, TWO_WEEKS_AGO)
gold_data  = fred("GOLDAMGBD228NLBM", 4, TWO_WEEKS_AGO)
silver_data= fred("SLVPRUSD",         4, TWO_WEEKS_AGO)
eur_data   = fred("DEXUSEU",          4, TWO_WEEKS_AGO)


def ticker_item(label, data, unit="", dec=2):
    pair = prev2(data)
    if not pair:
        return None
    v = float(pair[0]["value"])
    p = float(pair[1]["value"]) if len(pair) > 1 else None
    return {
        "label":   label,
        "val":     round(v, dec),
        "chg":     round(v - p, dec) if p else None,
        "chgPct":  round(((v - p) / p) * 100, 2) if p else None,
        "unit":    unit,
        "dec":     dec,
    }


ticker = [
    ticker_item("SPX",     sp_data,    "",    2),
    ticker_item("VIX",     vix_data,   "",    2),
    ticker_item("BRENT",   brent_data, "USD", 2),
    ticker_item("US 10Y",  us10y_data, "%",   2),
    ticker_item("GOLD",    gold_data,  "USD", 0),
    ticker_item("SILBER",  silver_data,"USD", 2),
    ticker_item("EUR/USD", eur_data,   "",    4),
]
ticker = [t for t in ticker if t]


# ── Assemble output ──────────────────────────────────────────────
output = {
    "fetchedAt": NOW.isoformat(),
    "indicators": {
        "inflation": {"value": inflation,              "date": cpi_obs[-1]["date"]},
        "fedRate":   {"value": float(fed_obs["value"]), "date": fed_obs["date"]},
        "recProb":   {"value": float(rec_obs["value"]), "date": rec_obs["date"]},
        "sp500":     {"ytd": sp_ytd, "first": sp_first, "latest": sp_latest, "date": sp_obs[-1]["date"]},
        "sentiment": {"value": float(sent_obs["value"]), "date": sent_obs["date"]},
    },
    "ticker": ticker,
}

os.makedirs("data", exist_ok=True)
with open("data/latest.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"✓ data/latest.json written at {NOW.isoformat()}")
