"""Ficha de cada empresa (pestaña Empresas): historia de precio, datos del negocio, balances, analistas y noticias.

Fuente principal: Yahoo Finance (yfinance), una vez por día. Si Yahoo no devuelve los datos de una empresa,
se piden a Finnhub (con clave, límite 60 pedidos por minuto). Precios: si Yahoo falla, Stooq.
Escribe un archivo por empresa en <datos>/fichas/emp/<ID>.json; la página lo pide solo al abrir la ficha.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from common import http_get, log, now_iso

INDICE = "^GSPC"


def _f(x):
    try:
        v = float(x)
        return None if v != v else v  # NaN
    except (TypeError, ValueError):
        return None


def _pct(x):
    """Yahoo da márgenes y crecimientos como fracción (0,25 = 25%)."""
    v = _f(x)
    return None if v is None else v * 100


def _rend_div(info):
    """Rendimiento por dividendo en %. Yahoo cambió el formato de dividendYield (antes fracción, ahora %):
    se usa el dividendo anual sobre el precio, que no es ambiguo."""
    tasa, precio = _f(info.get("dividendRate")), _f(info.get("currentPrice") or info.get("regularMarketPrice"))
    if tasa is not None and precio:
        return tasa / precio * 100
    v = _f(info.get("trailingAnnualDividendYield"))
    return v * 100 if v is not None else None


def datos_yahoo(sym):
    """Datos del negocio, balances, analistas y noticias desde Yahoo. Cada parte falla por separado."""
    import yfinance as yf
    t = yf.Ticker(sym)
    out = {}
    try:
        i = t.info or {}
        if i.get("quoteType") or i.get("longName") or i.get("shortName"):
            deuda, caja = _f(i.get("totalDebt")), _f(i.get("totalCash"))
            out["info"] = {
                "nombre": i.get("longName") or i.get("shortName"), "sector": i.get("sector"), "industria": i.get("industry"),
                "pais": i.get("country"), "empleados": i.get("fullTimeEmployees"), "web": i.get("website"),
                "moneda": i.get("currency"), "moneda_balance": i.get("financialCurrency"),
                "cap": _f(i.get("marketCap")), "beta": _f(i.get("beta")),
                "pe": _f(i.get("trailingPE")), "pe_fwd": _f(i.get("forwardPE")), "ev_ebitda": _f(i.get("enterpriseToEbitda")),
                "p_ventas": _f(i.get("priceToSalesTrailing12Months")), "p_libro": _f(i.get("priceToBook")),
                "div": _rend_div(i), "payout": _pct(i.get("payoutRatio")),
                "crec_ventas": _pct(i.get("revenueGrowth")), "crec_ganancias": _pct(i.get("earningsGrowth")),
                "margen_bruto": _pct(i.get("grossMargins")), "margen_operativo": _pct(i.get("operatingMargins")),
                "margen_neto": _pct(i.get("profitMargins")), "roe": _pct(i.get("returnOnEquity")),
                "ventas": _f(i.get("totalRevenue")), "ebitda": _f(i.get("ebitda")), "fcf": _f(i.get("freeCashflow")),
                "deuda_neta": (deuda - caja) if deuda is not None and caja is not None else None,
                "max52": _f(i.get("fiftyTwoWeekHigh")), "min52": _f(i.get("fiftyTwoWeekLow")),
                "recom": i.get("recommendationKey"), "recom_media": _f(i.get("recommendationMean")),
                "analistas": i.get("numberOfAnalystOpinions"),
                "objetivo": _f(i.get("targetMeanPrice")), "objetivo_max": _f(i.get("targetHighPrice")), "objetivo_min": _f(i.get("targetLowPrice")),
            }
    except Exception as e:  # noqa: BLE001
        log.warning("Yahoo info %s: %s", sym, e)
    try:
        eh = t.earnings_history
        if eh is not None and not eh.empty:
            filas = []
            for idx, r in eh.iterrows():
                filas.append({"trimestre": str(getattr(idx, "date", lambda: idx)())[:10], "estimado": _f(r.get("epsEstimate")),
                              "real": _f(r.get("epsActual")), "sorpresa": _f(r.get("surprisePercent"))})
            for f in filas:  # Yahoo da la sorpresa como fracción
                if f["sorpresa"] is not None:
                    f["sorpresa"] *= 100
            out["balances"] = sorted(filas, key=lambda x: x["trimestre"])[-4:]
    except Exception as e:  # noqa: BLE001
        log.warning("Yahoo balances %s: %s", sym, e)
    try:
        rc = t.recommendations
        if rc is not None and not rc.empty:
            r = rc.iloc[0]
            out["recomendaciones"] = {k: int(r.get(k) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}
    except Exception as e:  # noqa: BLE001
        log.warning("Yahoo analistas %s: %s", sym, e)
    try:
        notas = []
        crudas = []
        try:
            crudas = t.get_news(count=8) if hasattr(t, "get_news") else []
        except Exception:  # noqa: BLE001
            crudas = []
        for n in (crudas or t.news or [])[:8]:
            c = n.get("content") or n  # formato nuevo (content) y viejo
            url = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or c.get("link"))
            fecha = c.get("pubDate") or (datetime.fromtimestamp(c["providerPublishTime"], timezone.utc).isoformat() if c.get("providerPublishTime") else None)
            if c.get("title") and url:
                notas.append({"titulo": c["title"], "url": url, "fecha": fecha,
                              "fuente": (c.get("provider") or {}).get("displayName") or c.get("publisher")})
        if not notas:
            notas = _noticias_rss(sym)
        out["noticias"] = notas[:6]
    except Exception as e:  # noqa: BLE001
        log.warning("Yahoo noticias %s: %s", sym, e)
    # múltiplos que mezclan monedas: si la empresa reporta en otra moneda que la del precio (TSMC en TWD),
    # Yahoo divide valores en monedas distintas y el resultado no sirve
    i = out.get("info")
    if i and i.get("moneda_balance") and i.get("moneda") and i["moneda_balance"] != i["moneda"]:
        for k in ("ev_ebitda", "p_ventas", "p_libro"):
            i[k] = None
        i["multiplos_omitidos"] = True
    return out


def _noticias_rss(sym):
    """Titulares de Yahoo Finance por RSS (respaldo cuando la API de noticias no devuelve nada)."""
    import feedparser
    try:
        txt = http_get("https://feeds.finance.yahoo.com/rss/2.0/headline", params={"s": sym, "region": "US", "lang": "en-US"},
                       as_json=False, timeout=15, retries=1).text
        out = []
        for e in feedparser.parse(txt).entries[:6]:
            fecha = None
            if getattr(e, "published_parsed", None):
                fecha = datetime(*e.published_parsed[:6], tzinfo=timezone.utc).isoformat()
            out.append({"titulo": e.get("title"), "url": e.get("link"), "fecha": fecha, "fuente": "Yahoo Finance"})
        return [x for x in out if x["titulo"] and x["url"]]
    except Exception as e:  # noqa: BLE001
        log.warning("RSS noticias %s: %s", sym, e)
        return []


def noticias_finnhub(sym, key):
    """Último respaldo de noticias (solo acciones de EE.UU.)."""
    hoy = datetime.now(timezone.utc).date()
    try:
        rows = http_get("https://finnhub.io/api/v1/company-news",
                        params={"symbol": sym, "from": (hoy - timedelta(days=14)).isoformat(), "to": hoy.isoformat(), "token": key}) or []
        return [{"titulo": r.get("headline"), "url": r.get("url"), "fuente": r.get("source"),
                 "fecha": datetime.fromtimestamp(r["datetime"], timezone.utc).isoformat() if r.get("datetime") else None}
                for r in rows[:6] if r.get("headline") and r.get("url")]
    except Exception as e:  # noqa: BLE001
        log.warning("Finnhub noticias %s: %s", sym, e)
        return []


def datos_finnhub(sym, key):
    """Respaldo: métricas, balances y analistas desde Finnhub (si Yahoo no devolvió esa parte)."""
    out = {}
    base = "https://finnhub.io/api/v1"
    try:
        m = (http_get(f"{base}/stock/metric", params={"symbol": sym, "metric": "all", "token": key}) or {}).get("metric") or {}
        if m:
            out["info"] = {"cap": _f(m.get("marketCapitalization")) and _f(m.get("marketCapitalization")) * 1e6, "beta": _f(m.get("beta")),
                           "pe": _f(m.get("peTTM") or m.get("peBasicExclExtraTTM")), "p_ventas": _f(m.get("psTTM")), "p_libro": _f(m.get("pbQuarterly")),
                           "div": _f(m.get("currentDividendYieldTTM")), "crec_ventas": _f(m.get("revenueGrowthQuarterlyYoy")),
                           "crec_ganancias": _f(m.get("epsGrowthQuarterlyYoy")), "margen_bruto": _f(m.get("grossMarginTTM")),
                           "margen_operativo": _f(m.get("operatingMarginTTM")), "margen_neto": _f(m.get("netProfitMarginTTM")),
                           "roe": _f(m.get("roeTTM")), "max52": _f(m.get("52WeekHigh")), "min52": _f(m.get("52WeekLow"))}
        time.sleep(1.1)
        e = http_get(f"{base}/stock/earnings", params={"symbol": sym, "token": key}) or []
        if isinstance(e, list) and e:
            out["balances"] = sorted([{"trimestre": x.get("period"), "estimado": _f(x.get("estimate")), "real": _f(x.get("actual")),
                                       "sorpresa": _f(x.get("surprisePercent"))} for x in e], key=lambda x: x["trimestre"] or "")[-4:]
        time.sleep(1.1)
        r = http_get(f"{base}/stock/recommendation", params={"symbol": sym, "token": key}) or []
        if isinstance(r, list) and r:
            out["recomendaciones"] = {k: int(r[0].get(k) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}
        time.sleep(1.1)
    except Exception as e:  # noqa: BLE001
        log.warning("Finnhub %s: %s", sym, e)
    return out


def historias(simbolos):
    """{símbolo: [(fecha, cierre, volumen)]} de 13 meses, ajustado por dividendos y splits. Yahoo; si falta, Stooq."""
    import yfinance as yf
    out = {}
    try:
        df = yf.download(sorted(simbolos), period="13mo", interval="1d", group_by="ticker", auto_adjust=True, threads=8, progress=False)
    except Exception as e:  # noqa: BLE001
        log.warning("Yahoo historia: %s", e)
        df = None
    for s in simbolos:
        try:
            sub = df[s].dropna(subset=["Close"])
            vol = sub["Volume"] if "Volume" in sub else None
            out[s] = [(d.strftime("%Y-%m-%d"), float(c), float(vol[d]) if vol is not None and vol[d] == vol[d] else None)
                      for d, c in sub["Close"].items()]
        except Exception:  # noqa: BLE001
            pass
    faltan = [s for s in simbolos if not out.get(s)]
    if faltan:
        from fetch_prices import _stooq
        with ThreadPoolExecutor(6) as ex:
            for s, serie in zip(faltan, ex.map(_stooq, faltan)):
                if serie:
                    out[s] = [(d, v, None) for d, v in serie]
    return out


def armar(items, carpeta, finnhub_key=None, hilos=6):
    """items: empresas de config (id, nombre, yahoo, cedear, sector). Devuelve resumen."""
    carpeta.mkdir(parents=True, exist_ok=True)
    simbolos = {it["yahoo"] for it in items} | {INDICE} | {it["sector"] for it in items if it.get("sector")}
    hist = historias(simbolos)
    base = {s: hist.get(s) or [] for s in simbolos}

    with ThreadPoolExecutor(hilos) as ex:
        yahoo = dict(zip([it["id"] for it in items], ex.map(lambda it: datos_yahoo(it["yahoo"]), items)))
    sin, respaldo = [], []
    for it in items:
        d = yahoo[it["id"]]
        faltan = [k for k in ("info", "balances", "recomendaciones") if not d.get(k)]
        if faltan and finnhub_key and "." not in it["yahoo"]:  # Finnhub gratis: solo acciones de EE.UU.
            fh = datos_finnhub(it["yahoo"], finnhub_key)
            for k in faltan:
                if fh.get(k):
                    d[k] = fh[k]
                    respaldo.append(f"{it['id']}:{k}")
        if not d.get("noticias") and finnhub_key and "." not in it["yahoo"]:
            d["noticias"] = noticias_finnhub(it["yahoo"], finnhub_key)
            if d["noticias"]:
                respaldo.append(f"{it['id']}:noticias")
            time.sleep(1.1)
        filas = base.get(it["yahoo"]) or []
        if not filas and not d.get("info"):
            sin.append(it["id"])
            continue
        corta = lambda s: [x for x in s if x[0] >= (datetime.now() - timedelta(days=380)).strftime("%Y-%m-%d")]  # noqa: E731
        filas = corta(filas)
        fechas = [x[0] for x in filas]
        def alinear(sym):  # referencia (S&P 500 o ETF del sector) en las mismas fechas que la empresa
            ref = sorted(base.get(sym) or [])
            out_, j, ult = [], 0, None
            for f in fechas:  # último cierre disponible a esa fecha (las bolsas no abren los mismos días)
                while j < len(ref) and ref[j][0] <= f:
                    ult = ref[j][1]
                    j += 1
                out_.append(round(ult, 4) if ult is not None else None)
            return out_
        doc = {"id": it["id"], "nombre": it["nombre"], "yahoo": it["yahoo"], "cedear": it.get("cedear"), "sector_etf": it.get("sector"),
               "updated": now_iso(), "fuente": "Yahoo Finance" + (" (respaldo Finnhub)" if any(r.startswith(it["id"] + ":") for r in respaldo) else ""),
               "f": fechas, "p": [round(x[1], 4) for x in filas], "v": [round(x[2]) if x[2] else None for x in filas],
               "spx": alinear(INDICE), "sec": alinear(it["sector"]) if it.get("sector") else None, **d}
        (carpeta / f"{it['id']}.json").write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    # capitalización en miles de millones de US$ (reemplaza al bloque megacaps_info: un pedido menos por empresa)
    a_usd = {"USD": 1.0, "SAR": 1 / 3.75}
    caps = {}
    for it in items:
        i = yahoo[it["id"]].get("info") or {}
        if i.get("cap") and (i.get("moneda") or "USD") in a_usd:
            caps[it["id"]] = i["cap"] * a_usd[i.get("moneda") or "USD"] / 1e9
    hechas = len(items) - len(sin)
    if not hechas:
        raise RuntimeError("ninguna empresa con datos")
    avisos = [f"Ficha de {x}: Yahoo no devolvió datos" for x in sin]
    for it in items:
        i = yahoo[it["id"]].get("info") or {}
        for k, lo, hi, nom in (("pe", 0, 500, "P/E"), ("pe_fwd", 0, 300, "P/E proyectado"), ("p_libro", 0, 200, "precio/valor libro")):
            if i.get(k) is not None and not lo < i[k] < hi:
                avisos.append(f"{it['id']}: {nom} de {i[k]:,.1f}, fuera de rango")
    return {"empresas": hechas, "caps": caps, "avisos": avisos, "sin_datos": sin, "respaldo_finnhub": respaldo,
            "sin_info": [it["id"] for it in items if it["id"] not in sin and not yahoo[it["id"]].get("info")]}
