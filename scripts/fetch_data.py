#!/usr/bin/env python3
"""Fetch FRED data and write a stable data/latest.json schema for GitHub Pages."""

from __future__ import annotations

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
OUT_PATH = Path("data/latest.json")

MONTHLY_START = (NOW - timedelta(days=365 * 15)).strftime("%Y-%m-%d")
DAILY_START = (NOW - timedelta(days=365 * 6)).strftime("%Y-%m-%d")
YEAR_START = f"{NOW.year}-01-01"
TWO_WEEKS_AGO = (NOW - timedelta(days=14)).strftime("%Y-%m-%d")

TICKER_ICONS = {
    "SPX": "📊",
    "VIX": "⚡",
    "BRENT": "🛢️",
    "US 10Y": "📉",
    "GOLD": "🟡",
    "SILBER": "⚪",
    "EUR/USD": "💱",
}


def fred(series_id: str, observation_start: str | None = None, limit: int | None = None) -> list[dict]:
    params = {
        "series_id": series_id,
        "api_key": FRED_KEY,
        "file_type": "json",
        "sort_order": "asc",
    }
    if observation_start:
        params["observation_start"] = observation_start
    if limit is not None:
        params["limit"] = str(limit)

    url = FRED_BASE + "?" + urllib.parse.urlencode(params)

    try:
        with urllib.request.urlopen(url, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"ERROR {series_id}: HTTP {exc.code} — {body[:400]}", file=sys.stderr)
        return []
    except Exception as exc:
        print(f"ERROR {series_id}: {exc}", file=sys.stderr)
        return []

    observations = payload.get("observations", [])
    valid = [o for o in observations if o.get("value") not in (None, "", ".")]
    print(f"✓ {series_id}: {len(valid)} valid obs")
    return valid


def history_points(observations: list[dict], dec: int = 2) -> list[dict]:
    points: list[dict] = []
    for obs in observations:
        try:
            points.append({"date": obs["date"], "value": round(float(obs["value"]), dec)})
        except Exception:
            continue
    return points


def last_value(observations: list[dict], default: float = 0.0) -> float:
    if not observations:
        return default
    try:
        return float(observations[-1]["value"])
    except Exception:
        return default


def ticker_item(label: str, observations: list[dict], unit: str = "", dec: int = 2) -> dict | None:
    if not observations:
        return None
    current = float(observations[-1]["value"])
    prev = float(observations[-2]["value"]) if len(observations) > 1 else None
    return {
        "label": label,
        "icon": TICKER_ICONS.get(label, "•"),
        "val": round(current, dec),
        "chg": round(current - prev, dec) if prev is not None else None,
        "chgPct": round(((current - prev) / prev) * 100, 2) if prev not in (None, 0) else None,
        "unit": unit,
        "dec": dec,
    }


def build_yoy_history(observations: list[dict], dec: int = 2) -> list[dict]:
    points: list[dict] = []
    for idx in range(12, len(observations)):
        current = float(observations[idx]["value"])
        prev = float(observations[idx - 12]["value"])
        if prev == 0:
            continue
        yoy = ((current / prev) - 1) * 100
        points.append({"date": observations[idx]["date"], "value": round(yoy, dec)})
    return points


def latest_by_date(points: list[dict]) -> str:
    return points[-1]["date"] if points else ""


def ytd_stats(sp_history: list[dict]) -> tuple[float, float, float, str]:
    year_points = [p for p in sp_history if p["date"] >= YEAR_START]
    source = year_points if len(year_points) >= 2 else sp_history
    if len(source) < 2:
        return 0.0, 0.0, 0.0, ""
    first = source[0]["value"]
    latest = source[-1]["value"]
    ytd = round(((latest / first) - 1) * 100, 2) if first else 0.0
    return ytd, first, latest, source[-1]["date"]


def fill_forward_map(points: list[dict]) -> dict[str, float]:
    return {p["date"]: p["value"] for p in points}


def stress_score(vix: float, brent: float, eurusd: float, us10y: float, sp_ytd: float) -> int:
    score = 0

    if vix >= 30:
        score += 28
    elif vix >= 25:
        score += 22
    elif vix >= 20:
        score += 15
    elif vix >= 16:
        score += 8

    if brent >= 110:
        score += 26
    elif brent >= 100:
        score += 20
    elif brent >= 90:
        score += 13
    elif brent >= 80:
        score += 7

    # DEXUSEU = USD per EUR. Lower values imply a stronger USD / tighter conditions.
    if eurusd <= 1.00:
        score += 16
    elif eurusd <= 1.05:
        score += 12
    elif eurusd <= 1.08:
        score += 7
    elif eurusd <= 1.12:
        score += 3

    if us10y >= 5.00:
        score += 13
    elif us10y >= 4.50:
        score += 9
    elif us10y >= 4.00:
        score += 6
    elif us10y >= 3.50:
        score += 3

    if sp_ytd <= -20:
        score += 17
    elif sp_ytd <= -10:
        score += 11
    elif sp_ytd <= -5:
        score += 6

    return min(100, score)


def stress_label(score: int) -> str:
    if score >= 60:
        return "Hoch"
    if score >= 35:
        return "Erhöht"
    return "Entspannt"


def build_stress_history(vix: list[dict], brent: list[dict], eurusd: list[dict], us10y: list[dict], sp500: list[dict]) -> list[dict]:
    vix_map = fill_forward_map(vix)
    brent_map = fill_forward_map(brent)
    eur_map = fill_forward_map(eurusd)
    y10_map = fill_forward_map(us10y)
    sp_map = fill_forward_map(sp500)

    dates = sorted(set(vix_map) | set(brent_map) | set(eur_map) | set(y10_map) | set(sp_map))
    last_vix = last_brent = last_eur = last_y10 = last_sp = None
    base_sp = None
    history: list[dict] = []

    for date in dates:
        if date in vix_map:
            last_vix = vix_map[date]
        if date in brent_map:
            last_brent = brent_map[date]
        if date in eur_map:
            last_eur = eur_map[date]
        if date in y10_map:
            last_y10 = y10_map[date]
        if date in sp_map:
            last_sp = sp_map[date]
            if base_sp is None:
                base_sp = last_sp

        if None in (last_vix, last_brent, last_eur, last_y10, last_sp, base_sp) or base_sp == 0:
            continue

        sp_ytd_like = ((last_sp / base_sp) - 1) * 100
        history.append(
            {
                "date": date,
                "value": stress_score(float(last_vix), float(last_brent), float(last_eur), float(last_y10), float(sp_ytd_like)),
            }
        )

    return history


print("Fetching core series…")
cpi_raw = fred("CPIAUCSL", observation_start=MONTHLY_START)
fed_raw = fred("FEDFUNDS", observation_start=MONTHLY_START)
rec_raw = fred("RECPROUSM156N", observation_start=MONTHLY_START)
sent_raw = fred("UMCSENT", observation_start=MONTHLY_START)
sp_raw = fred("SP500", observation_start=DAILY_START)

print("Fetching market series…")
vix_recent = fred("VIXCLS", observation_start=TWO_WEEKS_AGO)
brent_recent = fred("DCOILBRENTEU", observation_start=TWO_WEEKS_AGO)
us10y_recent = fred("DGS10", observation_start=TWO_WEEKS_AGO)
gold_recent = fred("GOLDAMGBD228NLBM", observation_start=TWO_WEEKS_AGO)
silver_recent = fred("SLVPRUSD", observation_start=TWO_WEEKS_AGO)
eurusd_recent = fred("DEXUSEU", observation_start=TWO_WEEKS_AGO)

print("Fetching long histories…")
vix_hist_raw = fred("VIXCLS", observation_start=DAILY_START)
brent_hist_raw = fred("DCOILBRENTEU", observation_start=DAILY_START)
us10y_hist_raw = fred("DGS10", observation_start=DAILY_START)
eurusd_hist_raw = fred("DEXUSEU", observation_start=DAILY_START)

if len(cpi_raw) < 13:
    print("ERROR: Not enough CPI history to calculate YoY inflation.", file=sys.stderr)
    sys.exit(1)
if len(sp_raw) < 2:
    print("ERROR: Not enough SP500 history.", file=sys.stderr)
    sys.exit(1)

inflation_history = build_yoy_history(cpi_raw)
fed_history = history_points(fed_raw, dec=2)
rec_history = history_points(rec_raw, dec=1)
sent_history = history_points(sent_raw, dec=1)
sp_history = history_points(sp_raw, dec=2)
vix_hist = history_points(vix_hist_raw, dec=2)
brent_hist = history_points(brent_hist_raw, dec=2)
eurusd_hist = history_points(eurusd_hist_raw, dec=4)
us10y_hist = history_points(us10y_hist_raw, dec=2)

stress_history = build_stress_history(vix_hist, brent_hist, eurusd_hist, us10y_hist, sp_history)

inflation_value = inflation_history[-1]["value"]
fed_value = fed_history[-1]["value"] if fed_history else 0.0
rec_value = rec_history[-1]["value"] if rec_history else 0.0
sent_value = sent_history[-1]["value"] if sent_history else 0.0
sp_ytd, sp_first, sp_latest, sp_date = ytd_stats(sp_history)
stress_value = stress_history[-1]["value"] if stress_history else 0

print(f"→ Inflation YoY: {inflation_value}%")
print(f"→ S&P 500 YTD: {sp_ytd}%")
print(f"→ Trade Stress: {stress_value}/100 ({stress_label(stress_value)})")

latest_vix = last_value(vix_hist_raw)
latest_brent = last_value(brent_hist_raw)
latest_eurusd = last_value(eurusd_hist_raw)
latest_us10y = last_value(us10y_hist_raw)

output = {
    "fetchedAt": NOW.isoformat(),
    "meta": {
        "schemaVersion": "2.2",
        "source": "FRED",
        "notes": {
            "reload": "Das Dashboard lädt nur data/latest.json neu. Frische Makrodaten kommen, wenn GitHub Actions diese Datei überschreibt.",
            "cadence": "Monatliche Reihen wirken auf 1W/1M oft flach, weil die Quelle selbst nur monatlich aktualisiert wird.",
        },
    },
    "indicators": {
        "inflation": {
            "value": inflation_value,
            "date": latest_by_date(inflation_history),
            "cadence": "monthly",
        },
        "fedRate": {
            "value": fed_value,
            "date": latest_by_date(fed_history),
            "cadence": "monthly",
        },
        "recProb": {
            "value": rec_value,
            "date": latest_by_date(rec_history),
            "cadence": "monthly",
            "series": "RECPROUSM156N",
        },
        "sp500": {
            "ytd": sp_ytd,
            "first": sp_first,
            "latest": sp_latest,
            "date": sp_date,
            "cadence": "daily",
        },
        "sentiment": {
            "value": sent_value,
            "date": latest_by_date(sent_history),
            "cadence": "monthly",
        },
        "tradeStress": {
            "value": stress_value,
            "label": stress_label(stress_value),
            "date": latest_by_date(stress_history),
            "cadence": "daily",
            "method": "proxy",
            "components": {
                "vix": round(latest_vix, 2),
                "brent": round(latest_brent, 2),
                "eurusd": round(latest_eurusd, 4),
                "us10y": round(latest_us10y, 2),
            },
        },
    },
    "ticker": [
        ticker_item("SPX", sp_raw[-10:] if len(sp_raw) >= 2 else sp_raw, "", 2),
        ticker_item("VIX", vix_recent, "", 2),
        ticker_item("BRENT", brent_recent, "USD", 2),
        ticker_item("US 10Y", us10y_recent, "%", 2),
        ticker_item("GOLD", gold_recent, "USD", 0),
        ticker_item("SILBER", silver_recent, "USD", 2),
        ticker_item("EUR/USD", eurusd_recent, "", 4),
    ],
    "history": {
        "inflation": inflation_history,
        "fedRate": fed_history,
        "recProb": rec_history,
        "sp500": sp_history,
        "sentiment": sent_history,
        "tradeStress": stress_history,
    },
}
output["ticker"] = [item for item in output["ticker"] if item is not None]

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"✓ Wrote {OUT_PATH} at {NOW.strftime('%Y-%m-%d %H:%M:%S UTC')}")
