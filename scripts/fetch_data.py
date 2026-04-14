#!/usr/bin/env python3
from __future__ import annotations
import html, json, os, sys, urllib.error, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

FRED_KEY = os.environ.get("FRED_API_KEY", "").strip()
if not FRED_KEY:
    print("ERROR: FRED_API_KEY secret not found.", file=sys.stderr)
    sys.exit(1)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
NOW = datetime.now(timezone.utc)
OUT = Path("data/latest.json")
MONTHLY_START = (NOW - timedelta(days=365 * 15)).strftime("%Y-%m-%d")
DAILY_START = (NOW - timedelta(days=365 * 6)).strftime("%Y-%m-%d")
TWO_WEEKS_AGO = (NOW - timedelta(days=14)).strftime("%Y-%m-%d")
YEAR_START = f"{NOW.year}-01-01"
TICKER_ICONS = {"SPX":"📊","VIX":"⚡","BRENT":"🛢️","US 10Y":"📉","GOLD":"🟡","SILBER":"⚪","EUR/USD":"💱"}

def http_get(url:str, timeout:int=25)->bytes:
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 (compatible; MarketRiskMonitor/2.4)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def fred(series_id:str, observation_start:str|None=None, limit:int|None=None)->list[dict]:
    params={"series_id":series_id,"api_key":FRED_KEY,"file_type":"json","sort_order":"asc"}
    if observation_start: params["observation_start"]=observation_start
    if limit is not None: params["limit"]=str(limit)
    url = FRED_BASE + "?" + urllib.parse.urlencode(params)
    try:
        payload = json.loads(http_get(url).decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"ERROR {series_id}: HTTP {e.code}", file=sys.stderr); return []
    except Exception as e:
        print(f"ERROR {series_id}: {e}", file=sys.stderr); return []
    obs = [o for o in payload.get("observations", []) if o.get("value") not in (None, "", ".")]
    print(f"✓ {series_id}: {len(obs)} valid obs")
    return obs

def history_points(obs:list[dict], dec:int=2)->list[dict]:
    out=[]
    for o in obs:
        try: out.append({"date":o["date"],"value":round(float(o["value"]),dec)})
        except Exception: pass
    return out

def build_yoy_history(obs:list[dict], dec:int=2)->list[dict]:
    out=[]
    for i in range(12, len(obs)):
        cur=float(obs[i]["value"]); prev=float(obs[i-12]["value"])
        if prev==0: continue
        out.append({"date":obs[i]["date"],"value":round(((cur/prev)-1)*100,dec)})
    return out

def latest_by_date(points:list[dict])->str:
    return points[-1]["date"] if points else ""

def last_value(obs:list[dict], default:float=0.0)->float:
    if not obs: return default
    try: return float(obs[-1]["value"])
    except Exception: return default

def ticker_item(label:str, obs:list[dict], unit:str="", dec:int=2)->dict|None:
    if not obs: return None
    cur=float(obs[-1]["value"]); prev=float(obs[-2]["value"]) if len(obs)>1 else None
    return {"label":label,"icon":TICKER_ICONS.get(label,"•"),"val":round(cur,dec),"chg":round(cur-prev,dec) if prev is not None else None,"chgPct":round(((cur-prev)/prev)*100,2) if prev not in (None,0) else None,"unit":unit,"dec":dec}

def ytd_stats(sp_history:list[dict])->tuple[float,float,float,str]:
    year_points=[p for p in sp_history if p["date"]>=YEAR_START]
    source=year_points if len(year_points)>=2 else sp_history
    if len(source)<2: return 0.0,0.0,0.0,""
    first, latest = source[0]["value"], source[-1]["value"]
    ytd = round(((latest/first)-1)*100,2) if first else 0.0
    return ytd, first, latest, source[-1]["date"]

def fill_forward_map(points:list[dict])->dict[str,float]:
    return {p["date"]:p["value"] for p in points}

def stress_score(vix:float, brent:float, eurusd:float, us10y:float, sp_ytd:float)->int:
    score=0
    score += 28 if vix>=30 else 22 if vix>=25 else 15 if vix>=20 else 8 if vix>=16 else 0
    score += 26 if brent>=110 else 20 if brent>=100 else 13 if brent>=90 else 7 if brent>=80 else 0
    score += 16 if eurusd<=1.00 else 12 if eurusd<=1.05 else 7 if eurusd<=1.08 else 3 if eurusd<=1.12 else 0
    score += 13 if us10y>=5 else 9 if us10y>=4.5 else 6 if us10y>=4 else 3 if us10y>=3.5 else 0
    score += 17 if sp_ytd<=-20 else 11 if sp_ytd<=-10 else 6 if sp_ytd<=-5 else 0
    return min(100, score)

def stress_label(score:int)->str:
    return "Hoch" if score>=60 else "Erhöht" if score>=35 else "Entspannt"

def build_stress_history(vix, brent, eurusd, us10y, sp500):
    maps=[fill_forward_map(x) for x in (vix, brent, eurusd, us10y, sp500)]
    vix_map, brent_map, eur_map, y10_map, sp_map = maps
    dates=sorted(set(vix_map)|set(brent_map)|set(eur_map)|set(y10_map)|set(sp_map))
    lv=lb=le=ly=ls=base=None
    out=[]
    for d in dates:
        if d in vix_map: lv=vix_map[d]
        if d in brent_map: lb=brent_map[d]
        if d in eur_map: le=eur_map[d]
        if d in y10_map: ly=y10_map[d]
        if d in sp_map:
            ls=sp_map[d]
            if base is None: base=ls
        if None in (lv,lb,le,ly,ls,base) or base==0: continue
        sp_ytd=((ls/base)-1)*100
        out.append({"date":d,"value":stress_score(float(lv),float(lb),float(le),float(ly),float(sp_ytd))})
    return out

def clean_title(title:str)->str:
    title=html.unescape(title).strip()
    for sep in (" - ", " | ", " — "):
        if sep in title: return title.split(sep)[0].strip()
    return title

def infer_why_and_assets(title:str)->tuple[str,list[str],str]:
    t=title.lower()
    if any(k in t for k in ["oil","brent","opec","hormuz","energy","gas"]):
        return ("Energiepreise wirken direkt auf Inflation, Transportkosten und Risikoappetit. Das kann Aktien, Anleihen und Zentralbank-Erwartungen gleichzeitig bewegen.",["Öl","Inflation","Aktien","Staatsanleihen"],"Energie / Inflation")
    if any(k in t for k in ["fed","rate","rates","inflation","cpi","pce","yield","bond"]):
        return ("Zins- und Inflationsnachrichten verändern die Abzinsung künftiger Gewinne und beeinflussen Renditen, US-Dollar und Bewertungsniveaus.",["Aktien","US-Dollar","Staatsanleihen","Gold"],"Zinsen / Inflation")
    if any(k in t for k in ["earnings","guidance","profit","results","forecast"]):
        return ("Gewinnmeldungen und Ausblicke zeigen, ob Unternehmen höhere Kosten und schwächeres Wachstum abfedern können.",["Aktien","Sektoren","Volatilität"],"Unternehmensgewinne")
    if any(k in t for k in ["china","euro","europe","japan","boj","ecb","brics"]):
        return ("Internationale Wachstums- und Politiksignale sind wichtig, weil globale Nachfrage, Wechselkurse und Lieferketten eng verbunden sind.",["Weltaktien","Währungen","Rohstoffe"],"Globales Wachstum")
    if any(k in t for k in ["tariff","trade","sanction","shipping","supply chain"]):
        return ("Handels- und Lieferkettenmeldungen beeinflussen Margen, Preise und die Verfügbarkeit wichtiger Vorprodukte.",["Aktien","Rohstoffe","Inflation"],"Handel / Lieferketten")
    return ("Die Meldung liefert zusätzlichen Kontext dafür, wie Risikoappetit, Wachstumserwartungen oder Inflation kurzfristig verschoben werden können.",["Aktien","Makro"],"Marktkontext")

def fetch_news(max_items:int=5)->list[dict]:
    query=urllib.parse.quote("stock market OR inflation OR Federal Reserve OR oil OR recession OR earnings OR tariffs when:3d")
    url=f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    try:
        root=ET.fromstring(http_get(url, timeout=20))
    except Exception as e:
        print(f"WARNING news fetch failed: {e}", file=sys.stderr)
        return []
    items=[]; seen=set()
    for item in root.findall("./channel/item"):
        raw=item.findtext("title", default="").strip(); title=clean_title(raw)
        if not title or title.lower() in seen: continue
        seen.add(title.lower())
        link=item.findtext("link", default="").strip()
        pub=item.findtext("pubDate", default="").strip()
        source_el=item.find("source")
        source=source_el.text.strip() if source_el is not None and source_el.text else "Google News"
        try: pub_iso=parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat()
        except Exception: pub_iso=NOW.isoformat()
        why, assets, bucket = infer_why_and_assets(title)
        items.append({"title":title,"source":source,"publishedAt":pub_iso,"link":link,"whyItMatters":why,"assets":assets,"bucket":bucket})
        if len(items)>=max_items: break
    return items

print("Fetching core series…")
cpi_raw=fred("CPIAUCSL", observation_start=MONTHLY_START)
effr_raw=fred("EFFR", observation_start=DAILY_START)
rec_raw=fred("RECPROUSM156N", observation_start=MONTHLY_START)
sahm_raw=fred("SAHMCURRENT", observation_start=MONTHLY_START)
sent_raw=fred("UMCSENT", observation_start=MONTHLY_START)
sp_raw=fred("SP500", observation_start=DAILY_START)
print("Fetching market series…")
vix_recent=fred("VIXCLS", observation_start=TWO_WEEKS_AGO)
brent_recent=fred("DCOILBRENTEU", observation_start=TWO_WEEKS_AGO)
us10y_recent=fred("DGS10", observation_start=TWO_WEEKS_AGO)
gold_recent=fred("GOLDAMGBD228NLBM", observation_start=TWO_WEEKS_AGO)
silver_recent=fred("SLVPRUSD", observation_start=TWO_WEEKS_AGO)
eurusd_recent=fred("DEXUSEU", observation_start=TWO_WEEKS_AGO)
print("Fetching long histories…")
vix_hist_raw=fred("VIXCLS", observation_start=DAILY_START)
brent_hist_raw=fred("DCOILBRENTEU", observation_start=DAILY_START)
us10y_hist_raw=fred("DGS10", observation_start=DAILY_START)
eurusd_hist_raw=fred("DEXUSEU", observation_start=DAILY_START)
if len(cpi_raw)<13 or len(sp_raw)<2:
    print("ERROR: not enough core history", file=sys.stderr); sys.exit(1)
inflation_history=build_yoy_history(cpi_raw)
effr_history=history_points(effr_raw,2)
rec_history=history_points(rec_raw,1)
sahm_history=history_points(sahm_raw,2)
sent_history=history_points(sent_raw,1)
sp_history=history_points(sp_raw,2)
vix_hist=history_points(vix_hist_raw,2)
brent_hist=history_points(brent_hist_raw,2)
eurusd_hist=history_points(eurusd_hist_raw,4)
us10y_hist=history_points(us10y_hist_raw,2)
stress_history=build_stress_history(vix_hist, brent_hist, eurusd_hist, us10y_hist, sp_history)
inflation_value = inflation_history[-1]["value"] if inflation_history else 0.0
effr_value = effr_history[-1]["value"] if effr_history else 0.0
rec_value = rec_history[-1]["value"] if rec_history else 0.0
sahm_value = sahm_history[-1]["value"] if sahm_history else 0.0
sent_value = sent_history[-1]["value"] if sent_history else 0.0
sp_ytd, sp_first, sp_latest, sp_date = ytd_stats(sp_history)
stress_value = stress_history[-1]["value"] if stress_history else 0
news_items = fetch_news(5)
output={
 "fetchedAt":NOW.isoformat(),
 "meta":{"schemaVersion":"2.4","source":"FRED + Google News RSS","notes":{"reload":"Das Dashboard lädt nur data/latest.json neu. Frische Daten kommen, wenn GitHub Actions diese Datei überschreibt.","cadence":"Monatliche Reihen wirken auf 1W/1M oft flach, weil die Quelle selbst nur monatlich aktualisiert wird.","news":"Die Nachrichten sind ein kompakter Marktkontext und keine Anlageempfehlung."}},
 "indicators":{
   "inflation":{"value":inflation_value,"date":latest_by_date(inflation_history),"cadence":"monthly","series":"CPIAUCSL"},
   "fedRate":{"value":effr_value,"date":latest_by_date(effr_history),"cadence":"daily","series":"EFFR","displayName":"Effective Federal Funds Rate"},
   "recProb":{"value":rec_value,"date":latest_by_date(rec_history),"cadence":"monthly","series":"RECPROUSM156N","fastProxy":{"label":"Sahm Rule","value":sahm_value,"date":latest_by_date(sahm_history),"series":"SAHMCURRENT"}},
   "sp500":{"ytd":sp_ytd,"first":sp_first,"latest":sp_latest,"date":sp_date,"cadence":"daily","series":"SP500"},
   "sentiment":{"value":sent_value,"date":latest_by_date(sent_history),"cadence":"monthly","series":"UMCSENT"},
   "tradeStress":{"value":stress_value,"label":stress_label(stress_value),"date":latest_by_date(stress_history),"cadence":"daily","method":"proxy","components":{"vix":round(last_value(vix_hist_raw),2),"brent":round(last_value(brent_hist_raw),2),"eurusd":round(last_value(eurusd_hist_raw),4),"us10y":round(last_value(us10y_hist_raw),2)}}},
 "ticker":[
   ticker_item("SPX", sp_raw[-10:] if len(sp_raw)>=2 else sp_raw, "", 2),
   ticker_item("VIX", vix_recent, "", 2),
   ticker_item("BRENT", brent_recent, "USD", 2),
   ticker_item("US 10Y", us10y_recent, "%", 2),
   ticker_item("GOLD", gold_recent, "USD", 0),
   ticker_item("SILBER", silver_recent, "USD", 2),
   ticker_item("EUR/USD", eurusd_recent, "", 4)
 ],
 "history":{"inflation":inflation_history,"fedRate":effr_history,"recProb":rec_history,"sp500":sp_history,"sentiment":sent_history,"tradeStress":stress_history},
 "news":news_items
}
output["ticker"]=[x for x in output["ticker"] if x is not None]
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"✓ Wrote {OUT}")
