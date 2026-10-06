"""Prueba sin red: reemplaza las fuentes por respuestas falsas con la forma real de cada API y corre
los dos scripts completos. Sirve para verificar el código y generar datos de ejemplo."""
import io
import json
import random
import sys
from datetime import date, datetime, timedelta, timezone
import re
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
    if "argentinadatos.com/v1/feriados" in url:
        return [{"fecha": "2026-10-12", "tipo": "trasladable", "nombre": "Diversidad cultural"}, {"fecha": "2026-11-23", "tipo": "trasladable", "nombre": "Soberanía"}]
    if url.endswith("/economia/finanzas/noticias"):
        class _L: text = '<a href="/noticias/resultado-de-la-licitacion-por-efectivo-de-instrumentos-1">r</a>'
        return _L
    if "/noticias/resultado-de-la-licitacion" in url:
        class _R:
            text = ("<p>27 de agosto de 2026</p><p>Se recibieron ofertas por un total de valor efectivo de $ 13,18 billones. "
                    "Se adjudicó un total de valor efectivo $ 12,16 billones.</p><table><tr><th>Instrumento</th><th>VNO Adjudicado</th>"
                    "<th>VE Adjudicado</th><th>Precio</th><th>TIREA</th></tr><tr><td>LECAP S30N6 (Reapertura)</td><td>$ 5.000.000</td>"
                    "<td>$ 6.085.000</td><td>$ 1.217,00</td><td>29,75%</td></tr></table>")
        return _R
    if "historical-series/history" in url:
        sym = p["symbol"].split()[0]
        base = (61.8 if sym.endswith("D") and sym[:2] in ("AL", "GD", "AE", "AO", "AN") else 91 if sym.startswith("BP")
                else 151000 if re.fullmatch(r"D\d\d[A-Z]\d", sym) else 300 if sym.startswith(("TZX", "TX", "X")) else 115)
        t0 = int(datetime(2025, 10, 6, 3, tzinfo=timezone.utc).timestamp())
        ts = [t0 + 86400 * k for k in range(365) if datetime.fromtimestamp(t0 + 86400 * k, timezone.utc).weekday() < 5]
        cs, v = [], base * 0.9
        for _ in ts:
            v *= 1 + random.uniform(-0.004, 0.0055)
            cs.append(round(v, 3))
        return {"s": "ok", "t": ts, "c": cs, "v": [random.randint(1, 9) * 1e8 for _ in ts]}
    if "stats.bis.org" in url:
        class _B:
            text = ('FREQ,REF_AREA,COMPILATION,TIME_PERIOD,OBS_VALUE\n'
                    'D,JP,"From 24 Sep 2026: call rate, around 1.25",2026-09-23,1\n'
                    'D,JP,"From 24 Sep 2026: call rate, around 1.25",2026-09-29,1.25\n'
                    'D,BR,"SELIC, target",2026-09-28,13.75\n')
        return _B
    if "api.bcb.gov.br" in url:
        raise RuntimeError("403 desde el exterior (prueba del respaldo)")
    if "indec.gob.ar" in url or "fomccalendars" in url:
        raise RuntimeError("sin red en la prueba")
    if "rava.com/perfil/CAUCION" in url:
        d = int(url.split("%20")[1].rstrip("D"))
        class _H: text = f"<title>CAUCION {d}D Caución a {d} día{'s' if d > 1 else ''} $2{d % 5},10 (-1,50%) | Rava</title>"
        return _H
    if "dolarapi" in url:
        v = {"oficial": 1545, "blue": 1560, "bolsa": 1557, "contadoconliqui": 1617.4, "cripto": 1612.3, "tarjeta": 2008.5, "mayorista": 1522}
        return [{"casa": k, "nombre": k, "compra": x - 20, "venta": x, "fechaActualizacion": "2026-10-01T16:40:00.000Z"} for k, x in v.items()]
    if "data912.com/live/arg_bonds" in url:
        base = {"AL29": 66, "GD29": 67, "AL30": 61.8, "GD30": 63.2, "AL35": 74.5, "GD35": 76.8, "AE38": 79.2, "GD38": 81.4,
                "AL41": 64.21, "GD41": 68.43, "GD46": 62.63, "AO27": 101.95, "AO28": 91.02, "AN29": 86.40, "AO29": 84.54, "BPOA7": 104.0, "BPOB7": 104.1, "BPOC7": 104.15, "BPOD7": 104.2,
                "BPOA8": 91.0, "BPOB8": 91.3}
        rows = []
        for t, usd in base.items():
            rows.append({"symbol": t + "D", "c": usd, "pct_change": round(random.uniform(-1, 1), 2)})
            rows.append({"symbol": t, "c": round(usd * 1557, 0), "pct_change": round(random.uniform(-1, 1), 2)})
        for t, pr in {"T15E7": 150.05, "T30J7": 128.6, "TX26": 751.3, "TX28": 1771.0, "TX31": 1444.0, "TZX27": 407.15, "TZX28": 354.65,
                      "TZXD6": 308.9, "TZXD7": 282.5, "TZXM7": 228.95, "TZXO6": 174.93, "TZXS7": 109.95, "TMF27": 124.15, "TML27": 109.35}.items():
            rows.append({"symbol": t, "c": pr, "pct_change": round(random.uniform(-0.5, 0.5), 2)})
        return rows
    if "data912.com/live/arg_notes" in url:
        return [{"symbol": t, "c": pr, "pct_change": round(random.uniform(-0.3, 0.3), 2)}
                for t, pr in {"S16O6": 104.38, "S30O6": 133.15, "S13N6": 106.77, "S30N6": 125.19, "S29E7": 103.15, "T30A7": 135.45, "T31Y7": 127.34}.items()]
    if "data912.com/live/arg_stocks" in url:
        return [{"symbol": t, "c": round(random.uniform(500, 9000), 1), "pct_change": round(random.uniform(-3, 3), 2), "v": random.randint(1000, 900000)} for t in
                ["ALUA", "BBAR", "BMA", "BYMA", "CEPU", "COME", "CRES", "EDN", "GGAL", "IRSA", "LOMA", "METR", "PAMP", "SUPV", "TECO2",
                 "TGNO4", "TGSU2", "TRAN", "TXAR", "VALO", "YPFD", "MORI", "BHIP", "LONG", "AGRO", "YPFDD"]]
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
        vals = {1: 47482, 5: 1523.2, 78: 160, 44: 23.44, 7: 22.06, 12: 21.11, 27: 1.9, 28: 31.8, 29: 22.5, 30: 847.76, 31: 2139.68}
        desc = {30: "CER - Coeficiente de Estabilización de Referencia", 31: "UVA - Unidad de Valor Adquisitivo"}
        return {"results": [{"idVariable": k, "descripcion": desc.get(k, f"Variable {k}"), "ultValorInformado": v, "ultFechaInformada": "2026-09-29"} for k, v in vals.items()]}
    if "bcra.gob.ar/estadisticas" in url:
        idv = int(url.rsplit("/", 1)[1])
        lvl = {1: 47482, 5: 1522, 78: 100, 30: 841.6, 44: 25.0}.get(idv, 10)
        if idv == 30:
            return {"results": [{"idVariable": 30, "detalle": [{"fecha": (TODAY - timedelta(days=k)).isoformat(), "valor": 847.76 - 0.42 * k} for k in range(420)]}]}
        return {"results": [{"idVariable": idv, "detalle": [{"fecha": d, "valor": v} for d, v in series(380, lvl, lvl * 0.004)]}]}
    if "apis.datos.gob.ar" in url:
        return {"data": [["2026-07-01", 0.019, 0.33], ["2026-08-01", 0.0211, 0.318]]}
    if "rem/ultimo" in url:
        out = []
        for i, (m, v) in enumerate([("2026-09", 1.8), ("2026-10", 1.7), ("2026-11", 1.6), ("2026-12", 1.8), ("2027-01", 1.6), ("2027-02", 1.6)]):
            out.append({"informe": "2026-08", "muestra": "todos", "indicador": "Precios minoristas (IPC nivel general-Nacional; INDEC)",
                        "periodoTipo": "mensual", "periodoDesde": m + "-01", "mediana": v})
            out.append({"informe": "2026-08", "muestra": "todos", "indicador": "Tipo de cambio nominal", "periodoTipo": "mensual",
                        "periodoDesde": m + "-01", "mediana": 1530 + 35 * i})
        out.append({"informe": "2026-08", "muestra": "todos", "indicador": "Precios minoristas (IPC nivel general-Nacional; INDEC)",
                    "periodoTipo": "proximos_12_meses", "periodo": "próx. 12 meses", "mediana": 21})
        out.append({"informe": "2026-08", "muestra": "todos", "indicador": "Precios minoristas (IPC nivel general-Nacional; INDEC)",
                    "periodoTipo": "anual", "periodo": "2027", "mediana": 20.5})
        return out
    if "fomccalendars" in url:
        return Resp(text='<a href="/monetarypolicy/fomcprojtabl20260916.htm">Projection</a>')
    if "fomcprojtabl" in url:
        return Resp(text="<table><tr><th>Median</th><th>2026</th><th>2027</th><th>2028</th><th>2029</th><th>Longer run</th></tr>"
                         "<tr><td>Change in real GDP</td><td>2.3</td></tr><tr><td>Federal funds rate</td><td>4.1</td><td>4.1</td><td>3.9</td><td>3.6</td><td>3.2</td></tr></table>")
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
                {"title": "CPI Flash Estimate y/y", "country": "EUR", "date": "2026-10-02T05:00:00-04:00", "impact": "High", "forecast": "2.4%", "previous": "2.3%"},
                {"title": "Caixin Services PMI", "country": "CNY", "date": "2026-10-03T21:45:00-04:00", "impact": "High", "forecast": "51.2", "previous": "50.9"},
                {"title": "ISM Services PMI", "country": "USD", "date": "2026-10-03T10:00:00-04:00", "impact": "Medium", "forecast": "51.8", "previous": "52.0"}]
    if "finnhub" in url:
        return {"earningsCalendar": [{"date": "2026-10-13", "symbol": "JPM", "hour": "bmo", "epsEstimate": 4.85},
                                     {"date": "2026-10-14", "symbol": "JNJ", "hour": "bmo", "epsEstimate": 2.71},
                                     {"date": "2026-10-15", "symbol": "NFLX", "hour": "amc", "epsEstimate": 7.02},
                                     {"date": "2026-10-14", "symbol": "XYZ", "hour": "amc", "epsEstimate": 1.0},
                                     {"date": "2026-10-28", "symbol": "MSFT", "hour": "amc", "epsEstimate": 3.9},
                                     {"date": "2026-10-16", "symbol": "TSM", "hour": "bmo", "epsEstimate": 2.6}]}
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
import lecaps  # noqa: E402
lecaps.HIST = common.HIST
lecaps.ARCHIVO = common.HIST / "lecaps_terms.json"
lecaps.http_get = fake_get
lecaps.today_ar = lambda: TODAY
lecaps.PAUSA = 0
class _Resp:
    def __init__(self, js): self._js = js
    def raise_for_status(self): pass
    def json(self): return self._js
def fake_post(url, json=None, **kw):
    sym = (json or {}).get("symbol", "")
    vtos = {"TMF27": "2027-02-26", "TML27": "2027-07-30", "TMG27": "2027-08-31", "TMF28": "2028-02-25", "TMG28": "2028-08-31"}
    if sym in vtos:
        return _Resp({"data": [{"denominacion": "BONO DEL TESORO NACIONAL EN PESOS A TASA TAMAR", "moneda": "Pesos",
                                "fechaEmision": "2026-02-13", "fechaVencimiento": vtos[sym]}]})
    # ficha simulada: TEM 2,30% emitida el 15/12/2025 (alcanza para probar el flujo)
    return _Resp({"data": [{"denominacion": "LETRA DEL TESORO NACIONAL CAPITALIZABLE EN PESOS", "moneda": "Pesos",
                            "interes": "Tasa efectiva mensual: 2,30 %", "fechaEmision": "2025-12-15", "fechaVencimiento": None}]})
lecaps.requests.post = fake_post
import indec, feriados  # noqa: E402,E401
indec.http_get = fake_get
indec.today_ar = lambda: TODAY
feriados.http_get = fake_get
feriados.HIST = common.HIST
feriados.ARCHIVO = common.HIST / "feriados.json"
feriados.today_ar = lambda: TODAY
lecaps.ARCHIVO_CER = common.HIST / "cer_terms.json"
fetch_prices.yf.download = fake_download
class _FI:
    market_cap = 1.5e12
    currency = "USD"
class _T:
    def __init__(self, t):
        self.fast_info = _FI()
        self.info = {"quoteType": "EQUITY", "longName": f"{t} Inc.", "sector": "Technology", "industry": "Semiconductors", "country": "United States",
                     "currency": "USD", "financialCurrency": "USD", "marketCap": 1.5e12, "beta": 1.2, "trailingPE": 31.5, "forwardPE": 26.1,
                     "enterpriseToEbitda": 22.3, "priceToSalesTrailing12Months": 8.1, "priceToBook": 12.0, "dividendRate": 1.04, "currentPrice": 250.0,
                     "payoutRatio": 0.25, "revenueGrowth": 0.12, "earningsGrowth": 0.18, "grossMargins": 0.46, "operatingMargins": 0.31,
                     "profitMargins": 0.24, "returnOnEquity": 0.35, "totalRevenue": 4e11, "ebitda": 1.3e11, "freeCashflow": 1e11,
                     "totalDebt": 1e11, "totalCash": 6e10, "fiftyTwoWeekHigh": 260.0, "fiftyTwoWeekLow": 170.0, "recommendationKey": "buy",
                     "recommendationMean": 1.9, "numberOfAnalystOpinions": 41, "targetMeanPrice": 280.0, "targetHighPrice": 330.0, "targetLowPrice": 200.0}
        self.earnings_history = pd.DataFrame({"epsEstimate": [1.5, 1.6, 1.62, 1.7], "epsActual": [1.6, 1.58, 1.7, 1.81],
                                              "surprisePercent": [0.0667, -0.0125, 0.0494, 0.0647]},
                                             index=pd.to_datetime(["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]))
        cols = pd.to_datetime(["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"])
        self.quarterly_income_stmt = pd.DataFrame([[4.0e11, 3.5e11, 3.8e11, 3.2e11], [2.0e12, 1.9e12, 1.8e12, 1.7e12]],
                                                  index=["Net Income Common Stockholders", "Total Revenue"], columns=cols)
        self.quarterly_balance_sheet = pd.DataFrame([[1.2e13, 1.1e13, 1.0e13, 9.5e12]], index=["Stockholders Equity"], columns=cols)
        self.recommendations = pd.DataFrame({"period": ["0m"], "strongBuy": [12], "buy": [20], "hold": [8], "sell": [1], "strongSell": [0]})
        self.news = [{"content": {"title": f"{t} sube tras su balance", "pubDate": "2026-10-02T14:00:00Z", "provider": {"displayName": "Reuters"},
                                  "canonicalUrl": {"url": "https://example.com/nota"}}}]
import yfinance
yfinance.Ticker = _T
fetch_prices.feedparser.parse = fake_parse
common.today_ar = lambda: TODAY

OUT.mkdir(parents=True, exist_ok=True)
d = common.run_blocks(OUT / "daily.json", {k: getattr(fetch_daily, k) for k in
    ["us_macro", "fed", "treasuries", "ar_bcra", "ipc", "riesgo_pais", "emae", "rem", "bandas", "dolares_hist", "ar_backfill", "calendar_us", "calendar_ar", "calendar_intl", "us_senales", "megacaps_info", "earnings", "lecaps_auto", "cer_auto", "feriados_block", "avisos", "licitaciones_resultado", "tasas_bancos_centrales", "tamar_terms", "panel_general"]})
p = common.run_blocks(OUT / "prices.json", {k: getattr(fetch_prices, k) for k in ["markets", "dolares", "ar_market", "fed_probs", "cauciones", "news"]})
import fichas  # noqa: E402
fichas.http_get = fake_get
d["fichas_acciones"] = common.run_blocks(OUT / "fichas_run3.json", {"fichas_acciones": fetch_daily.fichas_acciones})["fichas_acciones"]
d["fichas_empresas"] = common.run_blocks(OUT / "fichas_run2.json", {"fichas_empresas": fetch_daily.fichas_empresas})["fichas_empresas"]
d["fichas_bonos"] = common.run_blocks(OUT / "fichas_run.json", {"fichas_bonos": fetch_daily.fichas_bonos})["fichas_bonos"]
bad = {k: v["error"] for src in (d, p) for k, v in src.items() if isinstance(v, dict) and v.get("error")}
print("errores:", json.dumps(bad, ensure_ascii=False, indent=1) if bad else "ninguno")
