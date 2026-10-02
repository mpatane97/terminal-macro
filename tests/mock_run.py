"""Prueba sin red: reemplaza las fuentes por respuestas falsas con la forma real de cada API y corre
los dos scripts completos. Sirve para verificar el código y generar datos de ejemplo."""
import io
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests" / "out"

import common  # noqa: E402
common.DATA = OUT
common.HIST = OUT / "history"
random.seed(7)
np.random.seed(7)
TODAY = date(2026, 10, 1)

LEVELS = {"^GSPC": 6650, "^NDX": 24600, "^DJI": 46300, "^RUT": 2440, "ES=F": 6690, "NQ=F": 24800, "YM=F": 46600,
          "^VIX": 16.4, "^STOXX50E": 5520, "^GDAXI": 23800, "^FTSE": 9350, "^N225": 44900, "000001.SS": 3850,
          "^HSI": 26800, "^BVSP": 146000, "EEM": 53.1, "DX-Y.NYB": 97.6, "EURUSD=X": 1.172, "JPY=X": 148.2,
          "GBPUSD=X": 1.344, "CNY=X": 7.12, "BRL=X": 5.33, "CL=F": 62.4, "BZ=F": 66.1, "GC=F": 3860, "SI=F": 46.7,
          "ZS=F": 1015, "ZW=F": 515, "ZC=F": 418, "BTC-USD": 114200, "^MERV": 1850000}


class Resp:
    def __init__(self, content=b"", text=""):
        self.content, self.text = content, text


def fake_download(tickers, **kw):
    idx = pd.bdate_range(end=pd.Timestamp(TODAY), periods=280)
    frames = {}
    for t in tickers:
        lvl = LEVELS.get(t, 100)
        walk = np.cumprod(1 + np.random.normal(0.0003, 0.011, len(idx)))
        s = lvl * walk / walk[-1]
        frames[t] = pd.DataFrame({"Close": s}, index=idx)
    return pd.concat(frames, axis=1)


def bandas_xlsx():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Fecha", "Piso", "Techo"])
    for i in range(40):
        d = TODAY - timedelta(days=20) + timedelta(days=i)
        ws.append([d, 740 - i * 0.2, 1905 + i * 1.05])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def series(n, lvl, step, fmt=lambda d: d.isoformat()):
    out = []
    v = lvl
    for i in range(n):
        d = TODAY - timedelta(days=n - i)
        v += random.uniform(-step, step)
        out.append((fmt(d), round(v, 4)))
    return out


def fake_get(url, params=None, headers=None, timeout=20, retries=2, as_json=True, verify=True):
    p = params or {}
    if "dolarapi" in url:
        v = {"oficial": 1545, "blue": 1560, "bolsa": 1557, "contadoconliqui": 1617.4, "cripto": 1612.3, "tarjeta": 2008.5, "mayorista": 1522}
        return [{"casa": k, "nombre": k, "compra": x - 20, "venta": x, "fechaActualizacion": "2026-10-01T16:40:00.000Z"} for k, x in v.items()]
    if "data912.com/live/arg_bonds" in url:
        base = {"AL29": 66, "GD29": 67, "AL30": 61.8, "GD30": 63.2, "AL35": 74.5, "GD35": 76.8, "AE38": 79.2, "GD38": 81.4,
                "AL41": 70.1, "GD41": 72.3, "GD46": 74.9, "BPOA7": 104.0, "BPOB7": 104.1, "BPOC7": 104.15, "BPOD7": 104.2,
                "BPOA8": 91.0, "BPOB8": 91.3}
        rows = []
        for t, usd in base.items():
            rows.append({"symbol": t + "D", "c": usd, "pct_change": round(random.uniform(-1, 1), 2)})
            rows.append({"symbol": t, "c": round(usd * 1557, 0), "pct_change": round(random.uniform(-1, 1), 2)})
        for t, pr in {"T15E7": 108.2, "T30J7": 112.5, "TX26": 640.0, "TZX27": 248.0, "TMF27": 101.2, "TTD26": 99.1}.items():
            rows.append({"symbol": t, "c": pr, "pct_change": round(random.uniform(-0.5, 0.5), 2)})
        return rows
    if "data912.com/live/arg_notes" in url:
        return [{"symbol": t, "c": pr, "pct_change": round(random.uniform(-0.3, 0.3), 2)}
                for t, pr in {"S16O6": 101.3, "S30N6": 103.6, "S30D6": 102.1, "S29E7": 105.8, "S31M7": 101.0}.items()]
    if "data912.com/live/arg_stocks" in url:
        return [{"symbol": t, "c": p, "pct_change": round(random.uniform(-3, 3), 2)} for t, p in {"GGAL": 6250, "YPFD": 41200, "PAMP": 3580}.items()]
    if "data912.com/live/arg_cedears" in url:
        return [{"symbol": t, "c": p, "pct_change": round(random.uniform(-2, 2), 2)} for t, p in {"SPY": 46800, "GOOGL": 9200, "NU": 16100, "NVDA": 10900, "MELI": 24500, "KO": 18900}.items()]
    if "data912.com/live/mep" in url:
        return [{"ticker": t, "close": 1557 + random.uniform(-6, 6)} for t in ["SPY", "GOOGL", "NU", "NVDA", "MELI", "KO"]]
    if "data912.com/live/ccl" in url:
        return [{"ticker": t, "CCL_close": 1617 + random.uniform(-8, 8)} for t in ["SPY", "GOOGL", "NU", "NVDA", "MELI", "KO"]]
    if "data912.com/historical" in url:
        t = url.rsplit("/", 1)[1]
        lvl = {"GGAL": 6000, "YPFD": 40000, "PAMP": 3600, "SPY": 46000, "GOOGL": 9000, "NU": 16000, "NVDA": 10500,
               "MELI": 25000, "KO": 18500}.get(t, 100 if t.startswith("BP") else 70)
        return [{"date": d, "c": v} for d, v in series(300, lvl, lvl * 0.01)]
    if "kalshi" in url:
        mk = lambda s, p: {"floor_strike": s, "strike_type": "greater", "last_price_dollars": str(p)}  # noqa: E731
        return {"events": [{"event_ticker": "KXFED-26OCT", "title": "Fed funds rate after Oct 2026 meeting", "strike_date": "2026-10-28T18:00:00Z",
                            "markets": [mk(3.25, 0.99), mk(3.5, 0.97), mk(3.75, 0.31), mk(4.0, 0.02)]}]}
    if "stlouisfed.org/fred/series/observations" in url:
        sid = p["series_id"]
        lv = {"CPIAUCSL": (322, 0.6), "PCEPILFE": (127, 0.25), "PAYEMS": (159500, 120), "UNRATE": (4.2, 0.05),
              "A191RL1Q225SBEA": (2.1, 0.8), "DFEDTARL": (3.75, 0), "DFEDTARU": (4.0, 0), "DGS3MO": (3.95, 0.02),
              "DGS2": (3.58, 0.03), "DGS5": (3.69, 0.03), "DGS10": (4.12, 0.03), "DGS30": (4.71, 0.03)}[sid]
        monthly = sid in ("CPIAUCSL", "PCEPILFE", "PAYEMS", "UNRATE")
        if monthly:
            obs, v = [], lv[0] * 0.97
            for m in pd.date_range(end=pd.Timestamp(2026, 8, 1), periods=26, freq="MS"):
                v += random.uniform(0, lv[1] * 2) if sid in ("CPIAUCSL", "PCEPILFE", "PAYEMS") else random.uniform(-lv[1], lv[1])
                obs.append({"date": m.strftime("%Y-%m-%d"), "value": str(round(v, 3))})
            obs.sort(key=lambda o: o["date"])
            return {"observations": obs}
        return {"observations": [{"date": d, "value": str(v)} for d, v in series(380, lv[0], lv[1])]}
    if "fred/series/release" in url:
        return {"releases": [{"id": 10}]}
    if "fred/release/dates" in url:
        return {"release_dates": [{"date": "2026-10-15"}]}
    if "newyorkfed" in url:
        return {"refRates": [{"effectiveDate": "2026-09-30", "percentRate": 3.88}]}
    if "prnewswire" in url:
        return Resp(text="Manufacturing PMI® at 49.6%; September 2026 ... Manufacturing PMI® at 48.7%; August 2026")
    if url.endswith("/Monetarias") and "bcra" in url:
        vals = {1: 41850, 5: 1522.0, 78: 160, 44: 23.44, 7: 22.06, 12: 21.11, 27: 1.9, 28: 31.8, 29: 22.5, 30: 640.12, 31: 1595.4}
        desc = {30: "CER - Coeficiente de Estabilización de Referencia", 31: "UVA - Unidad de Valor Adquisitivo"}
        return {"results": [{"idVariable": k, "descripcion": desc.get(k, f"Variable {k}"), "ultValorInformado": v, "ultFechaInformada": "2026-09-29"} for k, v in vals.items()]}
    if "bcra.gob.ar/estadisticas" in url:
        idv = int(url.rsplit("/", 1)[1])
        lvl = {1: 41850, 5: 1522, 78: 100}.get(idv, 10)
        return {"results": [{"idVariable": idv, "detalle": [{"fecha": d, "valor": v} for d, v in series(380, lvl, lvl * 0.004)]}]}
    if "apis.datos.gob.ar" in url:
        return {"data": [["2026-07-01", 0.019, 0.33], ["2026-08-01", 0.0211, 0.318]]}
    if "riesgo-pais" in url:
        return [{"fecha": d, "valor": round(v)} for d, v in series(400, 620, 8)]
    if "bandas-cambiarias" in url:
        return Resp(content=bandas_xlsx())
    if "argentinadatos.com/v1/cotizaciones/dolares" in url:
        out = []
        for casa, lvl in {"mayorista": 1460, "bolsa": 1500, "contadoconliqui": 1555, "blue": 1500, "cripto": 1550, "oficial": 1480}.items():
            out += [{"casa": casa, "fecha": d, "venta": v} for d, v in series(380, lvl * 0.985, lvl * 0.003)]
        return out
    if "faireconomy" in url:
        return [{"title": "ISM Manufacturing PMI", "country": "USD", "date": "2026-10-01T10:00:00-04:00", "impact": "High", "forecast": "49.2", "previous": "48.7"},
                {"title": "Non-Farm Employment Change", "country": "USD", "date": "2026-10-02T08:30:00-04:00", "impact": "High", "forecast": "90K", "previous": "22K"},
                {"title": "Unemployment Rate", "country": "USD", "date": "2026-10-02T08:30:00-04:00", "impact": "High", "forecast": "4.2%", "previous": "4.2%"},
                {"title": "ISM Services PMI", "country": "USD", "date": "2026-10-03T10:00:00-04:00", "impact": "Medium", "forecast": "51.8", "previous": "52.0"}]
    if "finnhub" in url:
        return {"earningsCalendar": [{"date": "2026-10-13", "symbol": "JPM", "hour": "bmo", "epsEstimate": 4.85},
                                     {"date": "2026-10-14", "symbol": "JNJ", "hour": "bmo", "epsEstimate": 2.71},
                                     {"date": "2026-10-15", "symbol": "NFLX", "hour": "amc", "epsEstimate": 7.02},
                                     {"date": "2026-10-14", "symbol": "XYZ", "hour": "amc", "epsEstimate": 1.0}]}
    raise RuntimeError(f"sin mock para {url}")


class FakeFeed:
    def __init__(self, entries):
        self.entries = entries


def fake_parse(url, agent=None):
    import time
    titles = {"federalreserve": ["Federal Reserve issues FOMC statement", "Minutes of the Federal Open Market Committee"],
              "dowjones": ["Stocks edge higher as Treasury yields slip", "Oil steadies ahead of OPEC+ meeting"],
              "ambito": ["El BCRA compró US$160 millones", "Riesgo país: cómo cerró la jornada"],
              "lanacion": ["Bonos en dólares: qué espera el mercado para octubre"],
              "bloomberglinea": ["Las reservas del BCRA y el techo de la banda"]}
    for k, ts in titles.items():
        if k in url:
            return FakeFeed([{"title": t, "link": "https://example.com", "published_parsed": time.gmtime(time.time() - 1800 * (i + 1))} for i, t in enumerate(ts)])
    return FakeFeed([])


import fetch_daily  # noqa: E402
import fetch_prices  # noqa: E402

for mod in (fetch_daily, fetch_prices):
    mod.http_get = fake_get
    mod.DATA, mod.HIST = common.DATA, common.HIST
    mod.today_ar = lambda: TODAY
fetch_daily.FRED_KEY = fetch_daily.FINNHUB_KEY = "x"
fetch_prices.yf.download = fake_download
fetch_prices.feedparser.parse = fake_parse
common.today_ar = lambda: TODAY

OUT.mkdir(parents=True, exist_ok=True)
d = common.run_blocks(OUT / "daily.json", {k: getattr(fetch_daily, k) for k in
    ["us_macro", "fed", "treasuries", "ar_bcra", "ipc", "riesgo_pais", "bandas", "dolares_hist", "ar_backfill", "calendar_us", "calendar_ar", "earnings"]})
p = common.run_blocks(OUT / "prices.json", {k: getattr(fetch_prices, k) for k in ["markets", "dolares", "ar_market", "fed_probs", "news"]})
bad = {k: v["error"] for src in (d, p) for k, v in src.items() if isinstance(v, dict) and v.get("error")}
print("errores:", json.dumps(bad, ensure_ascii=False, indent=1) if bad else "ninguno")
