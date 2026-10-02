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

def markets():
    groups = CFG["mercados"]
    tickers = sorted({i["yahoo"] for g in groups.values() for i in g})
    df = yf.download(tickers, period="13mo", interval="1d", group_by="ticker", auto_adjust=False,
                     threads=False, progress=False)
    if df is None or df.empty:
        raise RuntimeError("Yahoo devolvió vacío")
    out = {}
    missing = []
    for gname, items in groups.items():
        rows = []
        for it in items:
            try:
                s = df[it["yahoo"]]["Close"].dropna()
            except KeyError:
                s = pd.Series(dtype=float)
            if s.empty:
                missing.append(it["yahoo"])
                rows.append({**_meta(it), "last": None})
                continue
            series = [(d.strftime("%Y-%m-%d"), float(v)) for d, v in s.items()]
            ch = changes_from_series(series)
            ultimos = [v for _, v in series[-252:]]
            ch["dd52"] = (ch["last"] / max(ultimos) - 1) * 100 if ultimos else None
            rows.append({**_meta(it), **ch})
        out[gname] = rows
    if len(missing) > len(tickers) / 2:
        raise RuntimeError(f"Yahoo sin datos para {len(missing)} de {len(tickers)} símbolos")
    if missing:
        log.warning("Yahoo sin datos: %s", missing)
    return out, "Yahoo Finance (yfinance), demora ~15 min"


def _meta(it):
    return {k: it[k] for k in ("id", "nombre", "unidad", "cedear") if k in it}


# ---------- Dólares (dolarapi) ----------

def dolares():
    rows = http_get("https://dolarapi.com/v1/dolares")
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
    return {"cotizaciones": out, "brechas": brechas}, "dolarapi.com (secundaria)"


# ---------- Mercado argentino (data912) ----------

def _d912(path):
    return http_get(f"{D912}{path}", timeout=25)


def _ar_hist():
    return read_json(HIST / "ar_closes.json", {}) or {}


def _chg(hist, ticker, last):
    hoy = today_ar().isoformat()
    serie = {**{d: v for d, v in hist.get(ticker, {}).items() if d < hoy}, hoy: last}
    ch = changes_from_series(sorted(serie.items())) if last else None
    return {k: ch[k] for k in ("w", "m", "y")} if ch else {}


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
        if t in flows_by_ticker and p_usd:
            m = bonds.bond_metrics(flows_by_ticker[t], p_usd, settle)
            if m:
                row.update(m)
        if t in a["soberanos_usd"]:
            row["ley"] = "NY" if t.startswith("GD") else "Local"
        return row

    soberanos = [usd_row(t) for t in a["soberanos_usd"]]
    bopreal = [usd_row(t) for t in a["bopreal"]]

    pesos = []
    payoffs = BONOS.get("pago_final_pesos", {})
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
        pesos.append(row)
    pesos.sort(key=lambda r: r["vto"])

    cer_tamar = _cer_tamar(px, settle, a)
    _breakeven(pesos, cer_tamar)

    stocks = {r["symbol"]: r for r in _d912("/live/arg_stocks")}
    acciones = [{"ticker": t, "precio": num(stocks.get(t, {}).get("c")), "d": num(stocks.get(t, {}).get("pct_change")),
                 **_chg(hist, t, num(stocks.get(t, {}).get("c")))} for t in a["acciones"]]
    panel = [{"ticker": t, "precio": num(stocks.get(t, {}).get("c")), "d": num(stocks.get(t, {}).get("pct_change")),
              **_chg(hist, t, num(stocks.get(t, {}).get("c")))} for t in a.get("panel_lider", [])]

    ced = {r["symbol"]: r for r in _d912("/live/arg_cedears")}
    mep = {r.get("ticker"): r for r in _d912("/live/mep")}
    ccl = {r.get("ticker_ar") or r.get("ticker"): r for r in _d912("/live/ccl")}
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
        cedears.append({"ticker": t, "precio": num(c.get("c")), "d": num(c.get("pct_change")),
                        **_chg(hist, t, num(c.get("c"))),
                        "mep": num((mep.get(t) or {}).get("close") or (mep.get(t) or {}).get("mark")),
                        "ccl": num((ccl.get(t) or {}).get("CCL_close") or (ccl.get(t) or {}).get("CCL_mark"))})

    # guardar cierres del día para calcular variaciones semanales/mensuales/anuales
    today = today_ar().isoformat()
    for r in soberanos + bopreal:
        if r.get("usd"):
            hist.setdefault(_usd_ticker(r["ticker"]), {})[today] = r["usd"]
    for r in acciones + panel + cedears:
        if r.get("precio"):
            hist.setdefault(r["ticker"], {})[today] = r["precio"]
    write_json(HIST / "ar_closes.json", _trim(hist))

    return {"soberanos": soberanos, "bopreal": bopreal, "pesos_fija": pesos, "cer_tamar": cer_tamar,
            "acciones": acciones, "panel_lider": panel, "cedears": cedears, "cedears_mega": mega, "liquidacion": settle.isoformat()}, \
        "data912.com (secundaria); TIR y TEM: cálculo propio"


def _cer_tamar(px, settle, a):
    """Lista curada de bonos CER (con TIR real) y TAMAR (solo precio)."""
    daily = read_json(DATA / "daily.json", {}) or {}
    cer_t10 = (((daily.get("ar_bcra") or {}).get("data") or {}).get("cer_t10") or {}).get("valor")
    out = []
    for t in a.get("cer", []):
        r = px.get(t, {})
        p = num(r.get("c"))
        row = {"ticker": t, "tipo": "CER", "precio": p, "d": num(r.get("pct_change"))}
        fam = BONOS.get("cer", {}).get(t)
        if fam:
            fl = bonds.build_flows(fam)
            row["vto"] = fl[-1][0].isoformat()
            if p and cer_t10:
                coef = cer_t10 / fam["cer_inicial"]
                m = bonds.bond_metrics(fl, p / coef, settle)
                if m:
                    row.update({"tir": m["tir"], "dur_mod": m["dur_mod"], "coef_cer": coef,
                                "dias_vto": m["dias_vto"], "dias_prox": m["dias_prox"]})
        out.append(row)
    for t in a.get("tamar", []):
        r = px.get(t, {})
        out.append({"ticker": t, "tipo": "TAMAR", "precio": num(r.get("c")), "d": num(r.get("pct_change"))})
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
        "news": news,
    })
    log.info("prices.json actualizado %s", now_iso())
