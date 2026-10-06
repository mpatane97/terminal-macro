"""Ficha de cada acción argentina del panel líder.

- Historia de un año en pesos (BYMA, serie diaria 24hs; respaldo: cierres de data912) y en dólares CCL.
- Referencias en dólares CCL: Merval (Yahoo) y el promedio simple de las otras acciones del mismo sector.
- Si tiene ADR: historia del ADR (para el CCL implícito de cada día) y datos de la empresa desde Yahoo.
  Como reportan en pesos y el ADR cotiza en dólares, P/E, precio/valor libro y ventas se calculan acá:
  resultado y patrimonio en pesos pasados a dólares al CCL de hoy (aproximado).
Escribe un archivo por acción en <datos>/fichas/acc/<TICKER>.json.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import empresas
import fichas
from common import log, now_iso


def _valor_al(serie, iso):
    """Último valor de una serie ordenada [(fecha, valor)] con fecha <= iso."""
    v = None
    for d, x in serie:
        if d > iso:
            break
        v = x
    return v


def _alinear(fechas, serie):
    serie = sorted(serie)
    out, j, ult = [], 0, None
    for f in fechas:
        while j < len(serie) and serie[j][0] <= f:
            ult = serie[j][1]
            j += 1
        out.append(ult)
    return out


def _fila(df, nombres):
    """Primera fila del estado contable que exista (los nombres varían entre empresas y bancos)."""
    if df is None or getattr(df, "empty", True):
        return None
    for n in nombres:
        if n in df.index:
            return df.loc[n]
    return None


def fundamentos(adr, ccl, moneda="ARS"):
    """P/E, precio/valor libro, ROE, ventas y margen con los estados contables pasados a dólares CCL.
    Algunas (YPF, Pampa) reportan en dólares: en ese caso no se convierte."""
    if (moneda or "ARS").upper() == "USD":
        ccl = 1.0
    import yfinance as yf
    t = yf.Ticker(adr)
    out = {}
    try:
        inc = t.quarterly_income_stmt
        bal = t.quarterly_balance_sheet
        ni = _fila(inc, ["Net Income Common Stockholders", "Net Income", "Net Income Including Noncontrolling Interests"])
        rev = _fila(inc, ["Total Revenue", "Operating Revenue"])
        eq = _fila(bal, ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"])
        if ni is not None:
            v = [float(x) for x in ni.dropna().values[:4]]
            if len(v) == 4:
                out["utilidad_12m"] = sum(v) / ccl
        if rev is not None:
            v = [float(x) for x in rev.dropna().values[:4]]
            if len(v) == 4:
                out["ventas_12m"] = sum(v) / ccl
        if eq is not None and len(eq.dropna()):
            out["patrimonio"] = float(eq.dropna().values[0]) / ccl
            out["patrimonio_fecha"] = str(eq.dropna().index[0])[:10]
    except Exception as e:  # noqa: BLE001
        log.warning("estados contables %s: %s", adr, e)
    return out


def _verificar_moneda(fund, cap, ccl):
    """Yahoo a veces marca como pesos estados que en realidad están en dólares (pasa con YPF). Si al pasarlos
    de pesos a dólares el precio/valor libro da absurdo (más de 50 veces) y sin convertir da razonable, se
    toman como dólares."""
    if not cap or not fund.get("patrimonio") or fund.get("moneda") == "USD":
        return fund
    pbv_ars, pbv_usd = cap / fund["patrimonio"], cap / (fund["patrimonio"] * ccl)
    if pbv_ars > 50 and 0.05 <= pbv_usd <= 20:
        for k in ("utilidad_12m", "ventas_12m", "patrimonio"):
            if fund.get(k) is not None:
                fund[k] *= ccl
        fund["moneda"] = "USD"
        fund["moneda_corregida"] = True
    return fund


def armar(cfg_ar, carpeta, dolares_hist, cierres, hilos=6, extra=(), nombres=None):
    """extra: acciones del panel general elegidas por monto operado (sin sector ni ADR)."""
    carpeta.mkdir(parents=True, exist_ok=True)
    tickers = list(dict.fromkeys(cfg_ar.get("panel_lider", []) + cfg_ar.get("acciones", []) + list(extra)))
    emp = dict(cfg_ar.get("empresas", {}))
    for t, n in (nombres or {}).items():
        if t not in emp and n:
            emp[t] = {"nombre": n, "buscar": [n.split()[0]] if len(n.split()[0]) > 3 else [n]}
    sector_de = {t: s for s, ts in cfg_ar.get("sectores", {}).items() for t in ts}
    ccl = sorted((dolares_hist or {}).get("contadoconliqui", {}).items())
    if not ccl:
        raise RuntimeError("sin historia del CCL")
    ccl_hoy = ccl[-1][1]

    # precios locales (BYMA) con respaldo en los cierres guardados
    def local(t):
        try:
            filas = fichas.historia_byma(t)
        except Exception as e:  # noqa: BLE001
            log.warning("BYMA %s: %s", t, e)
            filas = []
        if not filas and cierres.get(t):
            filas = [(d, v, None) for d, v in sorted(cierres[t].items())]
        return t, filas
    with ThreadPoolExecutor(hilos) as ex:
        loc = dict(ex.map(local, tickers))

    # Merval y ADRs (Yahoo; respaldo Stooq para los ADRs)
    adrs = {t: emp[t]["adr"] for t in tickers if emp.get(t, {}).get("adr")}
    yh = empresas.historias(set(adrs.values()) | {"^MERV"})
    merval = [(d, c) for d, c, _ in yh.get("^MERV", [])]

    # cada acción en dólares CCL, para armar los promedios de sector
    usd = {}
    for t, filas in loc.items():
        usd[t] = {d: c / _valor_al(ccl, d) for d, c, _ in filas if _valor_al(ccl, d)}

    def info_adr(t):
        if t not in adrs:
            return t, {}
        d = empresas.datos_yahoo(adrs[t])
        d["fund"] = fundamentos(adrs[t], ccl_hoy, ((d.get("info") or {}).get("moneda_balance")))
        d["fund"]["moneda"] = ((d.get("info") or {}).get("moneda_balance")) or "ARS"
        d["fund"] = _verificar_moneda(d["fund"], (d.get("info") or {}).get("cap"), ccl_hoy)
        return t, d
    with ThreadPoolExecutor(hilos) as ex:
        datos = dict(ex.map(info_adr, tickers))

    hechas, sin = 0, []
    corte = (datetime.now() - timedelta(days=380)).strftime("%Y-%m-%d")
    for t in tickers:
        filas = [x for x in loc.get(t) or [] if x[0] >= corte]
        if not filas:
            sin.append(t)
            continue
        fechas = [x[0] for x in filas]
        ccl_al = _alinear(fechas, ccl)
        sec = sector_de.get(t)
        pares = [o for o in cfg_ar.get("sectores", {}).get(sec, []) if o != t] if sec and sec != "Otros" else []
        # índice de sector: promedio simple de los rendimientos diarios en dólares de las otras acciones del sector
        sec_idx = None
        if pares:
            sec_idx, nivel = [], 100.0
            for i, f in enumerate(fechas):
                if i:
                    r = [usd[o][f] / usd[o][fechas[i - 1]] - 1 for o in pares if f in usd.get(o, {}) and fechas[i - 1] in usd.get(o, {})]
                    if r:
                        nivel *= 1 + sum(r) / len(r)
                sec_idx.append(round(nivel, 4))
        e = emp.get(t, {})
        d = datos.get(t) or {}
        doc = {"ticker": t, "nombre": e.get("nombre", t), "sector": sec, "pares": pares, "buscar": e.get("buscar", []),
               "updated": now_iso(), "fuente": "BYMA (serie 24hs); CCL: argentinadatos; Merval y ADR: Yahoo Finance",
               "f": fechas, "p": [round(x[1], 3) for x in filas], "v": [round(x[2]) if x[2] else None for x in filas],
               "ccl": [round(x, 2) if x else None for x in ccl_al],
               "merval": [round(x, 2) if x else None for x in _alinear(fechas, merval)] if merval else None,
               "sector_idx": sec_idx}
        if t in adrs:
            doc["adr"] = {"simbolo": adrs[t], "ratio": e.get("ratio"),
                          "p": [round(x, 4) if x else None for x in _alinear(fechas, [(dd, c) for dd, c, _ in yh.get(adrs[t], [])])]}
            doc.update({k: d[k] for k in ("info", "balances", "recomendaciones", "noticias", "fund") if d.get(k)})
        (carpeta / f"{t}.json").write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        hechas += 1
    if not hechas:
        raise RuntimeError("ninguna acción con historia")
    # controles: ratio del ADR (CCL implícito lejos del CCL) y valuaciones imposibles
    avisos = []
    for t in adrs:
        try:
            d = json.loads((carpeta / f"{t}.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        k = next((i for i in range(len(d["f"]) - 1, -1, -1) if d["p"][i] and d["adr"]["p"][i] and d["ccl"][i]), None)
        if k is not None and d["adr"].get("ratio"):
            imp = d["p"][k] * d["adr"]["ratio"] / d["adr"]["p"][k]
            if abs(imp / d["ccl"][k] - 1) > 0.15:
                avisos.append((f"{t}: con el ratio {d['adr']['ratio']} su ADR da un CCL de {imp:,.0f} contra {d['ccl'][k]:,.0f}; "
                               "revisar el ratio en config/instruments.json").replace(",", "."))
        fu, cap = d.get("fund") or {}, (d.get("info") or {}).get("cap")
        if cap and fu.get("patrimonio") and not 0.05 <= cap / fu["patrimonio"] <= 20:
            avisos.append(f"{t}: precio/valor libro de {cap / fu['patrimonio']:,.1f} veces, fuera de rango (¿estados en otra moneda?)")
    return {"acciones": hechas, "avisos": avisos, "sin_historia": sin, "con_adr": sorted(adrs), "ccl_hoy": ccl_hoy}
