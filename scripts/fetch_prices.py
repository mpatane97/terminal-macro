"""Corrida cada 15 minutos (lun a vie, 10 a 17 h): precios de mercado, dólares, bonos, acciones,
probabilidades de la Fed y noticias. Escribe docs/data/prices.json."""
import calendar
import re
import unicodedata
from datetime import datetime, timezone

import feedparser
import pandas as pd
import yfinance as yf

import bonds
from common import (AR_TZ, DATA, HIST, Block, changes_from_series, http_get, load_config, log, now_iso,
                    num, pct, read_json, run_blocks, today_ar, write_json)

CFG = load_config("instruments.json")
BONOS = load_config("bonos.json")
D912 = "https://data912.com"


# ---------- Mercados internacionales (Yahoo Finance vía yfinance) ----------

# Respaldo de Yahoo: Stooq (CSV diario gratis). Equivalencias de símbolos que no siguen la regla "acción.us".
STOOQ = {"^GSPC": "^spx", "^NDX": "^ndx", "^DJI": "^dji", "ES=F": "es.f", "NQ=F": "nq.f", "YM=F": "ym.f",
         "^STOXX50E": "^stx", "^GDAXI": "^dax", "^FTSE": "^ukx", "^N225": "^nkx", "000001.SS": "^shc", "^HSI": "^hsi",
         "^BVSP": "^bvp", "DX-Y.NYB": "dx.f", "EURUSD=X": "eurusd", "JPY=X": "usdjpy", "GBPUSD=X": "gbpusd",
         "CNY=X": "usdcny", "BRL=X": "usdbrl", "CL=F": "cl.f", "BZ=F": "cb.f", "GC=F": "gc.f", "SI=F": "si.f",
         "ZS=F": "zs.f", "ZW=F": "zw.f", "ZC=F": "zc.f", "BTC-USD": "btcusd"}


def _stooq(yahoo):
    """Serie diaria de 13 meses desde Stooq, o [] si no hay equivalente o no responde."""
    sym = STOOQ.get(yahoo)
    if not sym:
        if re.fullmatch(r"[A-Z][A-Z.\-]{0,6}", yahoo):  # acción o ETF de EE.UU.
            sym = yahoo.lower().replace(".", "-") + ".us"
        else:
            return []
    hoy = today_ar()
    d1 = (hoy - pd.Timedelta(days=400)).strftime("%Y%m%d")
    try:
        txt = http_get("https://stooq.com/q/d/l/", params={"s": sym, "i": "d", "d1": d1, "d2": hoy.strftime("%Y%m%d")},
                       as_json=False, timeout=20, retries=1).text
    except Exception as e:  # noqa: BLE001
        log.warning("Stooq %s: %s", sym, e)
        return []
    out = []
    for linea in txt.strip().splitlines()[1:]:
        partes = linea.split(",")
        if len(partes) >= 5 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", partes[0]) and num(partes[4]):
            out.append((partes[0], num(partes[4])))
    return out


def markets():
    from concurrent.futures import ThreadPoolExecutor
    groups = CFG["mercados"]
    tickers = sorted({i["yahoo"] for g in groups.values() for i in g})
    try:
        df = yf.download(tickers, period="13mo", interval="1d", group_by="ticker", auto_adjust=False,
                         threads=8, progress=False)
    except Exception as e:  # noqa: BLE001
        log.warning("Yahoo: %s", e)
        df = None
    series_por = {}
    for t in tickers:
        try:
            s = df[t]["Close"].dropna() if df is not None and not df.empty else pd.Series(dtype=float)
        except KeyError:
            s = pd.Series(dtype=float)
        if not s.empty:
            series_por[t] = [(d.strftime("%Y-%m-%d"), float(v)) for d, v in s.items()]
    faltan = [t for t in tickers if t not in series_por]
    de_stooq = []
    if faltan:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for t, serie in zip(faltan, ex.map(_stooq, faltan)):
                if serie:
                    series_por[t] = serie
                    de_stooq.append(t)
    out = {}
    missing = []
    for gname, items in groups.items():
        rows = []
        for it in items:
            series = series_por.get(it["yahoo"])
            if not series:
                missing.append(it["yahoo"])
                rows.append({**_meta(it), "last": None})
                continue
            ch = changes_from_series(series)
            ultimos = [v for _, v in series[-252:]]
            ch["dd52"] = (ch["last"] / max(ultimos) - 1) * 100 if ultimos else None
            rows.append({**_meta(it), **ch})
        out[gname] = rows
    if len(missing) > len(tickers) / 2:
        raise RuntimeError(f"Yahoo y Stooq sin datos para {len(missing)} de {len(tickers)} símbolos")
    if missing:
        log.warning("sin datos: %s", missing)
    fuente = "Yahoo Finance (yfinance), demora ~15 min"
    if de_stooq:
        fuente += f" · respaldo Stooq para {len(de_stooq)} símbolo(s)"
        log.warning("Stooq usado para: %s", de_stooq)
    return out, fuente


def _meta(it):
    return {k: it[k] for k in ("id", "nombre", "unidad", "cedear", "sector") if k in it}


# ---------- Dólares (dolarapi) ----------

def _dolares_argentinadatos():
    """Respaldo: último dato de cada casa en argentinadatos, con el mismo formato que dolarapi."""
    rows = http_get("https://api.argentinadatos.com/v1/cotizaciones/dolares", timeout=40)
    ult = {}
    for r in rows:
        if r.get("casa") and (r["casa"] not in ult or r["fecha"] > ult[r["casa"]]["fecha"]):
            ult[r["casa"]] = r
    return [{"casa": k, "compra": v.get("compra"), "venta": v.get("venta"), "fechaActualizacion": v.get("fecha")} for k, v in ult.items()]


def dolares():
    fuente = "dolarapi.com (secundaria)"
    try:
        rows = http_get("https://dolarapi.com/v1/dolares")
        if not rows or not any(r.get("casa") == "mayorista" for r in rows):
            raise RuntimeError("dolarapi sin mayorista")
    except Exception as e:  # noqa: BLE001
        log.warning("dolarapi: %s; uso argentinadatos", e)
        rows = _dolares_argentinadatos()
        fuente = "argentinadatos.com (respaldo; dolarapi no respondió)"
    by = {r["casa"]: r for r in rows}
    hist = read_json(HIST / "dolares.json", {}) or {}
    names = [("mayorista", "Mayorista (A3500)"), ("bolsa", "MEP"), ("contadoconliqui", "CCL"),
             ("blue", "Blue"), ("cripto", "Cripto"), ("oficial", "Oficial minorista")]
    out = []
    for casa, nombre in names:
        r = by.get(casa)
        if not r:
            continue
        last = num(r.get("venta"))
        hoy = today_ar().isoformat()
        serie = {**{d: v for d, v in hist.get(casa, {}).items() if d < hoy}, hoy: last}
        ch = changes_from_series(sorted(serie.items())) if last else None
        out.append({"id": casa, "nombre": nombre, "compra": num(r.get("compra")), "venta": last,
                    "hora": r.get("fechaActualizacion"), **({k: ch[k] for k in ("d", "w", "m", "y")} if ch else {})})
    v = {r["id"]: r["venta"] for r in out}
    a3500 = v.get("mayorista")
    brechas = {
        "ccl_a3500": pct(v.get("contadoconliqui"), a3500),
        "mep_a3500": pct(v.get("bolsa"), a3500),
        "ccl_mep": pct(v.get("contadoconliqui"), v.get("bolsa")),
    }
    return {"cotizaciones": out, "brechas": brechas}, fuente


# ---------- Mercado argentino (data912) ----------

BYMA_FREE = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free"
# panel de BYMA equivalente a cada lista de data912 (mep/ccl implícitos no tienen equivalente)
BYMA_PANELES = {"/live/arg_bonds": ["public-bonds"], "/live/arg_notes": ["lebacs"],
                "/live/arg_stocks": ["leading-equity", "general-equity"], "/live/arg_cedears": ["cedears"]}
RESPALDOS = set()  # qué listas vinieron de BYMA en esta corrida


def _byma_panel(panel):
    import requests
    from common import UA
    verify = True
    for intento in range(2):
        try:
            r = requests.post(f"{BYMA_FREE}/{panel}", json={"page_size": 5000, "Content-Type": "application/json"},
                              headers={**UA, "Content-Type": "application/json"}, timeout=25, verify=verify)
            r.raise_for_status()
            js = r.json()
            return js if isinstance(js, list) else (js.get("data") or [])
        except requests.exceptions.SSLError:
            verify = False
        except Exception as e:  # noqa: BLE001
            if intento:
                raise
            log.warning("BYMA %s: %s", panel, e)


def _desde_byma(path):
    """Lista con el formato de data912 (symbol, c, pct_change, v) armada con los paneles públicos de BYMA.
    Se prefiere la liquidación a 24 h; si un papel sólo opera en contado, se toma esa."""
    filas = {}
    for panel in BYMA_PANELES.get(path, []):
        for it in _byma_panel(panel) or []:
            sym, liq = it.get("symbol"), str(it.get("settlementType"))
            if not sym or liq not in ("1", "2"):
                continue
            if sym in filas and not (filas[sym]["_liq"] == "1" and liq == "2"):
                continue
            ult = it.get("trade") or it.get("closingPrice") or it.get("previousClosingPrice")
            prev = it.get("previousClosingPrice")
            filas[sym] = {"symbol": sym, "c": ult, "v": it.get("volumeAmount") or it.get("volume") or 0, "_liq": liq,
                          "pct_change": (ult / prev - 1) * 100 if ult and prev else None}
    if not filas:
        raise RuntimeError(f"BYMA sin datos para {path}")
    return list(filas.values())


def _d912(path):
    try:
        rows = http_get(f"{D912}{path}", timeout=25)
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("respuesta vacía")
        return rows
    except Exception as e:  # noqa: BLE001
        if path not in BYMA_PANELES:
            raise
        log.warning("data912 %s: %s; uso BYMA", path, e)
        RESPALDOS.add(path)
        return _desde_byma(path)


def _ajustar_splits(serie):
    """Corrige splits y cambios de ratio: si entre dos cierres seguidos el precio se divide o multiplica
    por más de 2 (algo que no pasa con un movimiento real de un día), reescala la historia anterior."""
    fechas = sorted(serie)
    vals = [serie[f] for f in fechas]
    for i in range(len(vals) - 1, 0, -1):
        a, b = vals[i - 1], vals[i]
        if a and b and (b / a < 0.5 or b / a > 2):
            r = b / a
            for j in range(i):
                vals[j] = vals[j] * r if vals[j] else vals[j]
    return dict(zip(fechas, vals))


def _ar_hist():
    hist = read_json(HIST / "ar_closes.json", {}) or {}
    return {t: _ajustar_splits(s) for t, s in hist.items()}


def _chg(hist, ticker, last):
    hoy = today_ar().isoformat()
    serie = _ajustar_splits({**{d: v for d, v in hist.get(ticker, {}).items() if d < hoy}, hoy: last})
    ch = changes_from_series(sorted(serie.items())) if last else None
    return {k: ch[k] for k in ("w", "m", "y")} if ch else {}


def _vol(r):
    return num((r or {}).get("v"))


def _marcar_operados(rows, campo="vol"):
    """Marca `opero` en cada fila (si hubo volumen en la rueda). Si casi nadie operó todavía (antes de la
    apertura o un feriado), no marca nada: sería avisar que no operó algo que todavía no podía operar."""
    con_precio = [r for r in rows if r.get("precio", r.get("usd")) is not None]
    n = sum(1 for r in con_precio if (r.get(campo) or 0) > 0)
    hay_rueda = con_precio and n >= 0.3 * len(con_precio)
    for r in rows:
        r["opero"] = ((r.get(campo) or 0) > 0) if hay_rueda else None
    return rows


def _usd_ticker(t):
    """Especie en dólares MEP. Los BOPREAL usan otra raíz: BPOA7 -> BPA7D."""
    m = re.fullmatch(r"BPO([A-D]\d)", t)
    return f"BP{m.group(1)}D" if m else t + "D"


def ar_market():
    a = CFG["argentina"]
    bonds_rows = _d912("/live/arg_bonds")
    notes_rows = _d912("/live/arg_notes")
    px = {r["symbol"]: r for r in bonds_rows + notes_rows}
    hist = _ar_hist()
    settle = bonds.settle_date(today_ar())
    flows_by_ticker = {}
    for fam in BONOS["familias"].values():
        fl = bonds.build_flows(fam)
        for t in fam["tickers"]:
            flows_by_ticker[t] = fl

    def usd_row(t):
        ars, usd = px.get(t), px.get(_usd_ticker(t))
        p_usd = num(usd.get("c")) if usd else None
        vol = num(usd.get("v")) if usd else None
        row = {"ticker": t, "ars": num(ars.get("c")) if ars else None, "usd": p_usd,
               "d": num(usd.get("pct_change")) if usd else None, "vol": vol / 1e6 if vol else None,
               **_chg(hist, _usd_ticker(t), p_usd)}
        if t in flows_by_ticker:
            row["flujos"] = bonds.tabla_flujos(flows_by_ticker[t], settle)
            m = bonds.bond_metrics(flows_by_ticker[t], p_usd, settle) if p_usd else None
            if m:
                row.update(m)
        if t in a["soberanos_usd"]:
            row["ley"] = "NY" if t.startswith("GD") else "Local"
        return row

    soberanos = [usd_row(t) for t in a["soberanos_usd"]]
    bopreal = [usd_row(t) for t in a["bopreal"]]

    pesos = []
    # pagos finales: los calculados solos (scripts/lecaps.py) y, encima, los cargados a mano
    auto = {t: e["pago_final"] for t, e in (read_json(HIST / "lecaps_terms.json", {}) or {}).items() if e.get("pago_final")}
    payoffs = {**auto, **BONOS.get("pago_final_pesos", {})}
    for sym, r in px.items():
        mat = bonds.maturity_from_ticker(sym)
        if not mat or mat <= settle:
            continue
        p = num(r.get("c"))
        vol = num(r.get("v"))
        row = {"ticker": sym, "tipo": "LECAP" if sym.startswith("S") else "BONCAP", "precio": p,
               "vto": mat.isoformat(), "dias": (mat - settle).days, "d": num(r.get("pct_change")),
               "pago_final": num(payoffs.get(sym)), "vol": vol / 1e6 if vol else None}
        t = bonds.tem(p, payoffs.get(sym), settle, mat)
        if t:
            row.update(t)
        if payoffs.get(sym):  # un único pago al vencimiento: capital 100 + interés capitalizado
            pf = num(payoffs[sym])
            row["flujos"] = [[mat.isoformat(), 100.0, round(pf - 100, 4), 100.0, round(pf, 4)]]
        pesos.append(row)
    pesos.sort(key=lambda r: r["vto"])

    # dólar linked: pagan en pesos el valor nominal en dólares al tipo de cambio A3500 del vencimiento
    a35 = ((((read_json(DATA / "daily.json", {}) or {}).get("ar_bcra") or {}).get("data") or {}).get("a3500") or {}).get("valor")
    dl = []
    for sym, r in px.items():
        m_dl = re.fullmatch(r"D(\d{2})([EFMAYJLGSOND])(\d)", sym)
        if not m_dl:
            continue
        mat = bonds.maturity_from_ticker("S" + sym[1:])
        p = num(r.get("c"))
        if not mat or mat <= settle or not p:
            continue
        row = {"ticker": sym, "tipo": "Dólar linked", "precio": p, "vto": mat.isoformat(), "dias": (mat - settle).days,
               "d": num(r.get("pct_change")), "vol": _vol(r)}
        if a35:
            usd = p / a35
            for escala in (1, 100, 0.1):  # precio por 100 VN; si la fuente lo da por 1 o por 1.000 VN, se corrige
                if 40 <= usd * escala <= 130:
                    usd *= escala
                    break
            else:
                usd = None
            if usd:
                tir = (100 / usd) ** (365 / row["dias"]) - 1
                row.update({"precio_usd": usd, "tir": tir * 100, "tna": ((100 / usd) - 1) * 365 / row["dias"] * 100,
                            "flujos": [[mat.isoformat(), 100.0, round(100 - 100, 4), 100.0, 100.0]]})
        dl.append(row)
    dl.sort(key=lambda r: r["vto"])
    _marcar_operados(dl)

    cer_tamar = _cer_tamar(px, settle, a)
    for grupo in (soberanos, bopreal, pesos, [r for r in cer_tamar if r["tipo"] == "CER"], [r for r in cer_tamar if r["tipo"] == "TAMAR"]):
        _marcar_operados(grupo)
    _breakeven(pesos, cer_tamar)

    stocks = {r["symbol"]: r for r in _d912("/live/arg_stocks")}
    acciones = _marcar_operados([{"ticker": t, "precio": num(stocks.get(t, {}).get("c")), "d": num(stocks.get(t, {}).get("pct_change")),
                 "vol": _vol(stocks.get(t)), **_chg(hist, t, num(stocks.get(t, {}).get("c")))} for t in a["acciones"]])
    panel = _marcar_operados([{"ticker": t, "precio": num(stocks.get(t, {}).get("c")), "d": num(stocks.get(t, {}).get("pct_change")),
              "vol": _vol(stocks.get(t)), **_chg(hist, t, num(stocks.get(t, {}).get("c")))} for t in a.get("panel_lider", [])])

    ced = {r["symbol"]: r for r in _d912("/live/arg_cedears")}
    def opcional(path):  # MEP/CCL implícitos: sin equivalente en BYMA; si data912 no responde, quedan vacíos
        try:
            return _d912(path)
        except Exception as e:  # noqa: BLE001
            log.warning("data912 %s: %s", path, e)
            return []
    mep = {r.get("ticker"): r for r in opcional("/live/mep")}
    ccl = {r.get("ticker_ar") or r.get("ticker"): r for r in opcional("/live/ccl")}
    mega = {}
    for g in ("megacaps_eeuu", "megacaps_global", "empresas_seleccion"):
        for it in CFG["mercados"].get(g, []):
            t = it.get("cedear")
            if t and t in ced:
                mega[t] = {"precio": num(ced[t].get("c")), "d": num(ced[t].get("pct_change")),
                           "ccl": num((ccl.get(t) or {}).get("CCL_close") or (ccl.get(t) or {}).get("CCL_mark"))}
    cedears = []
    for t in a["cedears"]:
        c = ced.get(t, {})
        cedears.append({"ticker": t, "precio": num(c.get("c")), "d": num(c.get("pct_change")), "vol": _vol(c),
                        **_chg(hist, t, num(c.get("c"))),
                        "mep": num((mep.get(t) or {}).get("close") or (mep.get(t) or {}).get("mark")),
                        "ccl": num((ccl.get(t) or {}).get("CCL_close") or (ccl.get(t) or {}).get("CCL_mark"))})

    _marcar_operados(cedears)
    # guardar cierres del día para calcular variaciones semanales/mensuales/anuales (sólo días hábiles)
    import feriados
    today = today_ar().isoformat()
    if not feriados.es_habil(today_ar()):
        today = None
    for r in (soberanos + bopreal) if today else []:
        if r.get("usd"):
            hist.setdefault(_usd_ticker(r["ticker"]), {})[today] = r["usd"]
    for r in (acciones + panel + cedears) if today else []:
        if r.get("precio"):
            hist.setdefault(r["ticker"], {})[today] = r["precio"]
    write_json(HIST / "ar_closes.json", _trim(hist))

    return {"soberanos": soberanos, "bopreal": bopreal, "pesos_fija": pesos, "cer_tamar": cer_tamar, "dolar_linked": dl, "a3500_ref": a35,
            "acciones": acciones, "panel_lider": panel, "cedears": cedears, "cedears_mega": mega, "sectores": a.get("sectores", {}), "liquidacion": settle.isoformat()}, \
        ("data912.com (secundaria)" if not RESPALDOS else "BYMA open data (respaldo; data912 no respondió)") + "; TIR y TEM: cálculo propio"


def _cer_tamar(px, settle, a):
    """Lista curada de bonos CER (con TIR real) y TAMAR (solo precio)."""
    daily = read_json(DATA / "daily.json", {}) or {}
    cer_t10 = (((daily.get("ar_bcra") or {}).get("data") or {}).get("cer_t10") or {}).get("valor")
    out = []
    # bonos CER: los de la lista curada más los que se dieron de alta solos (scripts/lecaps.py)
    auto = {t: e for t, e in (read_json(HIST / "cer_terms.json", {}) or {}).items()
            if e.get("cer_inicial") and e.get("vto", "") > settle.isoformat()}
    lista = list(dict.fromkeys(a.get("cer", []) + sorted(auto, key=lambda t: auto[t]["vto"])))
    for t in lista:
        r = px.get(t, {})
        p = num(r.get("c"))
        if t not in a.get("cer", []) and not p:
            continue
        row = {"ticker": t, "tipo": "CER", "precio": p, "d": num(r.get("pct_change")), "vol": _vol(r)}
        fam = BONOS.get("cer", {}).get(t)
        if not fam and t in auto:
            e = auto[t]
            fam = {"cer_inicial": e["cer_inicial"], "pago_mes_dia": [e["vto"][5:]],
                   "amortizacion": {"primera": e["vto"], "cuotas_pct": 100.0, "n": 1}, "cupones": [[e["emision"], 0.0]]}
            row["auto"] = True
        if fam:
            fl = bonds.build_flows(fam)
            row["vto"] = fl[-1][0].isoformat()
            if cer_t10:
                row["flujos"] = bonds.tabla_flujos(fl, settle, cer_t10 / fam["cer_inicial"])
                row["coef_cer"] = cer_t10 / fam["cer_inicial"]
            if p and cer_t10:
                coef = cer_t10 / fam["cer_inicial"]
                m = bonds.bond_metrics(fl, p / coef, settle)
                if m and -50 < (m.get("tir") or 0) < 100:  # una TIR absurda indica un precio de otra especie
                    row.update({"tir": m["tir"], "dur_mod": m["dur_mod"], "coef_cer": coef,
                                "dias_vto": m["dias_vto"], "dias_prox": m["dias_prox"]})
        out.append(row)
    for t in a.get("tamar", []):
        r = px.get(t, {})
        out.append({"ticker": t, "tipo": "TAMAR", "precio": num(r.get("c")), "d": num(r.get("pct_change")), "vol": _vol(r)})
    return out


def _breakeven(pesos, cer):
    """Inflación implícita: compara la TEM de cada letra a tasa fija con la tasa real CER del mismo plazo
    (interpolada linealmente en días sobre la curva CER)."""
    pts = sorted((r["dias_vto"], r["tir"]) for r in cer if r.get("tir") is not None and r.get("dias_vto"))
    if len(pts) < 2:
        return
    for r in pesos:
        if r.get("tem") is None:
            continue
        d = r["dias"]
        if d <= pts[0][0]:
            real = pts[0][1]
        elif d >= pts[-1][0]:
            real = pts[-1][1]
        else:
            for (d0, y0), (d1, y1) in zip(pts, pts[1:]):
                if d0 <= d <= d1:
                    real = y0 + (y1 - y0) * (d - d0) / (d1 - d0)
                    break
        real_tem = (1 + real / 100) ** (30 / 365) - 1
        r["tem_real_cer"] = real_tem * 100
        r["inflacion_implicita"] = ((1 + r["tem"] / 100) / (1 + real_tem) - 1) * 100


def _trim(hist, keep=400):
    cutoff = (today_ar().toordinal() - keep)
    for t, s in hist.items():
        hist[t] = {d: v for d, v in s.items() if datetime.strptime(d, "%Y-%m-%d").toordinal() >= cutoff}
    return hist


# ---------- Probabilidades FOMC (Kalshi) ----------

def _kalshi_price(m):
    """Probabilidad implícita: punto medio entre compra y venta; si no hay puntas, último precio."""
    bid, ask = num(m.get("yes_bid_dollars")), num(m.get("yes_ask_dollars"))
    if bid is None and m.get("yes_bid") is not None:
        bid, ask = num(m.get("yes_bid")) / 100, num(m.get("yes_ask")) / 100 if m.get("yes_ask") is not None else None
    if bid is not None and ask is not None and ask > 0:
        return (bid + ask) / 2
    last = num(m.get("last_price_dollars"))
    if last is None and m.get("last_price") is not None:
        last = num(m["last_price"]) / 100
    return last


# ---------- Cauciones en pesos (1, 7 y 14 días) ----------

PLAZOS_CAUCION = (1, 7, 14)


def _caucion_rava(dias):
    """La página pública de Rava publica la TNA de cada plazo en el título:
    'CAUCION 7D Caución a 7 días $19,10 (-3,50%)'. Es la fuente principal: se lee sólo ese dato."""
    html = http_get(f"https://www.rava.com/perfil/CAUCION%20{dias}D", as_json=False, timeout=20).text
    m = re.search(r"<title>[^<]*?Cauci[oó]n a\s+(\d+)\s+d[ií]as?\s*\$?\s*([\d.,]+)\s*\((-?[\d.,]+)%\)", html, re.I)
    if not m or int(m.group(1)) != dias:
        raise RuntimeError(f"no se encontró la tasa de {dias} días en Rava")
    tna = float(m.group(2).replace(".", "").replace(",", "."))
    var = float(m.group(3).replace(".", "").replace(",", "."))
    return tna, var


def _cauciones_byma():
    """Respaldo: panel de cauciones de BYMA open data (tasa en pesos por plazo en días)."""
    for panel in ("cauciones", "repos", "caucion"):
        try:
            filas = _byma_panel(panel) or []
        except Exception as e:  # noqa: BLE001
            log.warning("BYMA %s: %s", panel, e)
            continue
        out = {}
        for it in filas:
            if (it.get("denominationCcy") or "ARS") != "ARS":
                continue
            dias = it.get("daysToMaturity") or it.get("term") or it.get("plazo")
            tasa = it.get("trade") or it.get("closingPrice") or it.get("vwap")
            if dias and tasa and int(dias) in PLAZOS_CAUCION:
                out[int(dias)] = (float(tasa), None)
        if out:
            return out
    return {}


def cauciones():
    out = []
    byma = None
    for d in PLAZOS_CAUCION:
        try:
            tna, var = _caucion_rava(d)
        except Exception as e:  # noqa: BLE001
            log.warning("caución %sd: %s", d, e)
            if byma is None:
                byma = _cauciones_byma()
            if d not in byma:
                continue
            tna, var = byma[d][0], 0.0
        prev = tna / (1 + var / 100) if var is not None and var > -100 else None
        out.append({"plazo": d, "tna": tna, "d_pb": (tna - prev) * 100 if prev else None,
                    "tem": ((1 + tna / 100 * d / 365) ** (30 / d) - 1) * 100,
                    "tea": ((1 + tna / 100 * d / 365) ** (365 / d) - 1) * 100})
    if not out:
        raise RuntimeError("sin datos de cauciones")
    return out, "Rava Bursátil (tasas de BYMA, secundaria)" + (" · BYMA open data como respaldo" if byma else "")


def fed_probs():
    url = "https://api.elections.kalshi.com/trade-api/v2/events"
    js = http_get(url, params={"series_ticker": "KXFED", "status": "open", "with_nested_markets": "true", "limit": 10})
    events = js.get("events", [])
    out = []
    for ev in events:
        pts = []
        for m in ev.get("markets", []):
            strike = num(m.get("floor_strike"))
            p = _kalshi_price(m)
            if strike is not None and p is not None and m.get("strike_type", "greater") in ("greater", "greater_or_equal"):
                pts.append((strike, p))
        pts.sort()
        if not pts or (ev.get("strike_date") or "") < now_iso()[:10]:
            continue
        # P(techo > s) no puede subir con s: se fuerza una curva no creciente
        mono, run = [], 1.0
        for s_, p in pts:
            run = min(run, p)
            mono.append((s_, run))
        pts = mono
        # P(tasa > s) para cada umbral -> distribución por tramos
        dist = []
        for i, (s, p) in enumerate(pts):
            nxt = pts[i + 1][1] if i + 1 < len(pts) else 0.0
            dist.append({"desde": s, "prob": max(p - nxt, 0.0) * 100})
        below = max(1 - pts[0][1], 0.0) * 100
        out.append({"evento": ev.get("event_ticker"), "titulo": ev.get("title"),
                    "fecha": ev.get("strike_date") or ev.get("close_time"),
                    "debajo_de": pts[0][0], "prob_debajo": below, "tramos": dist})
    out.sort(key=lambda e: e.get("fecha") or "")
    if not out:
        raise RuntimeError("Kalshi sin mercados KXFED abiertos")
    return out[:3], "Kalshi (mercado de predicción, secundaria)"


# ---------- Noticias (RSS) ----------

def _norm(t):
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def _news(feeds, claves, n=15):
    claves = [_norm(k) for k in claves]
    items, seen = [], set()
    for f in feeds:
        try:
            d = feedparser.parse(f["url"], agent="Mozilla/5.0")
            for e in d.entries[:30]:
                titulo = (e.get("title") or "").strip()
                if not titulo or titulo in seen:
                    continue
                if f.get("filtrar", True) and not any(k in _norm(titulo) for k in claves):
                    continue
                seen.add(titulo)
                t = e.get("published_parsed") or e.get("updated_parsed")
                ts = datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc).astimezone(AR_TZ).isoformat() if t else None
                items.append({"titulo": titulo, "url": e.get("link"), "fuente": f["fuente"], "hora": ts})
        except Exception as ex:  # noqa: BLE001
            log.warning("RSS %s: %s", f["fuente"], ex)
    items.sort(key=lambda i: i["hora"] or "", reverse=True)
    return items[:n]


def news():
    n = CFG["noticias"]
    us, ar = _news(n["eeuu"], n.get("claves_eeuu", [])), _news(n["argentina"], n.get("claves_argentina", []))
    if not us and not ar:
        raise RuntimeError("ningún RSS respondió")
    return {"eeuu": us, "argentina": ar}, "RSS de cada medio"


if __name__ == "__main__":
    run_blocks(DATA / "prices.json", {
        "markets": markets,
        "dolares": dolares,
        "ar_market": ar_market,
        "fed_probs": fed_probs,
        "cauciones": cauciones,
        "news": news,
    })
    log.info("prices.json actualizado %s", now_iso())
