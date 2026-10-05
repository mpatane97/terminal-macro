"""Historia de un año de cada bono y letra argentina, para la ficha (gráfico y variaciones).

Fuente: serie histórica diaria de BYMA (la misma del gráfico de su sitio, liquidación T+1).
Respaldo para bonos en dólares: los cierres guardados en history/ar_closes.json (data912).
Con cada precio se calcula la métrica del día: TIR (dólares y BOPREAL), TEM (LECAP/BONCAP),
TIR real (CER, con el CER t-10 hábiles de esa fecha) y TIR en dólares (dólar linked, con el A3500 de esa fecha).
Escribe un archivo por papel en <datos>/fichas/<TICKER>.json; la página lo pide solo al abrir la ficha.
"""
import bisect
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import bonds
import feriados
from common import http_get, log, now_iso, num

BYMA_HIST = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/chart/historical-series/history"
AR = timezone(timedelta(hours=-3))


def historia_byma(simbolo, dias=380):
    """[(fecha, cierre, volumen)] de la especie en BYMA, plazo 24hs."""
    hasta = datetime.now(AR)
    js = http_get(BYMA_HIST, params={"symbol": f"{simbolo} 24HS", "resolution": "D",
                                     "from": int((hasta - timedelta(days=dias)).timestamp()), "to": int(hasta.timestamp())},
                  headers={"Accept": "application/json"}, timeout=25)
    if not isinstance(js, dict) or js.get("s") != "ok":
        return []
    out = []
    for t, c, v in zip(js.get("t", []), js.get("c", []), js.get("v", []) or [None] * len(js.get("t", []))):
        if c:
            out.append((datetime.fromtimestamp(t, AR).date().isoformat(), float(c), float(v) if v else None))
    return out


def _valor_al(serie, iso):
    """Último valor de una serie [(fecha, valor)] ordenada con fecha <= iso."""
    i = bisect.bisect_right([d for d, _ in serie], iso)
    return serie[i - 1][1] if i else None


def _r(x, d):
    return None if x is None else round(x, d)


def metrica(papel, iso, precio, cer=None, a3500=None):
    """Métrica del día para un precio histórico. papel: dict con 'clase' y lo que necesita cada cálculo."""
    if not precio:
        return None
    settle = bonds.settle_date(date.fromisoformat(iso))
    try:
        if papel["clase"] == "usd":
            m = bonds.bond_metrics(papel["flujos"], precio, settle)
            v = m and m["tir"]
            return v if v is not None and -50 < v < 100 else None
        if papel["clase"] == "fija":
            mat = date.fromisoformat(papel["vto"])
            t = bonds.tem(precio, papel["pago_final"], settle, mat)
            return t and t["tem"]
        if papel["clase"] == "cer" and cer:
            c = _valor_al(cer, feriados.sumar_habiles(settle, -10).isoformat())
            m = c and bonds.bond_metrics(papel["flujos"], precio / (c / papel["cer_inicial"]), settle)
            v = m and m["tir"]
            return v if v is not None and -50 < v < 100 else None
        if papel["clase"] == "dl" and a3500:
            a = _valor_al(a3500, iso)
            mat = date.fromisoformat(papel["vto"])
            dias = (mat - settle).days
            if not a or dias <= 0:
                return None
            usd = precio / a
            for escala in (1, 100, 0.1):
                if 40 <= usd * escala <= 130:
                    return ((100 / (usd * escala)) ** (365 / dias) - 1) * 100
    except Exception:  # noqa: BLE001  un día con un precio raro no corta la serie
        return None
    return None


def armar(papeles, cer, a3500, cierres_respaldo, carpeta):
    """papeles: {ticker: {...}}; escribe un JSON por papel. Devuelve resumen."""
    carpeta.mkdir(parents=True, exist_ok=True)
    errores, ok = {}, 0

    def uno(t):
        p = papeles[t]
        fuente = "BYMA (serie histórica 24hs)"
        try:
            filas = historia_byma(p["simbolo"])
        except Exception as e:  # noqa: BLE001
            filas, fuente = [], None
            errores[t] = str(e)[:120]
        if not filas and cierres_respaldo.get(p["simbolo"]):
            filas = [(d, v, None) for d, v in sorted(cierres_respaldo[p["simbolo"]].items())]
            fuente = "data912 (cierres guardados)"
        if not filas:
            errores.setdefault(t, "sin historia")
            return False
        doc = {"ticker": t, "simbolo": p["simbolo"], "metrica": p.get("metrica"), "fuente": fuente, "updated": now_iso(),
               "f": [d for d, _, _ in filas], "p": [_r(c, 4) for _, c, _ in filas],
               "v": [_r(v, 0) for _, _, v in filas],
               "m": [_r(metrica(p, d, c, cer, a3500), 3) for d, c, _ in filas] if p.get("metrica") else None}
        (carpeta / f"{t}.json").write_text(__import__("json").dumps(doc, separators=(",", ":")), encoding="utf-8")
        return True

    with ThreadPoolExecutor(6) as ex:
        ok = sum(1 for r in ex.map(uno, sorted(papeles)) if r)
    if not ok:
        raise RuntimeError(f"ninguna historia disponible ({len(errores)} errores)")
    return {"papeles": ok, "sin_historia": sorted(errores), "errores": dict(list(errores.items())[:10])}


def papeles_de(ar_market, bonos_cfg, hoy):
    """Arma la lista de papeles a partir del último prices.json (para tomar los mismos tickers que la página)."""
    flujos = {}
    for fam in bonos_cfg["familias"].values():
        fl = bonds.build_flows(fam)
        for t in fam["tickers"]:
            flujos[t] = fl
    out = {}
    import re
    for r in (ar_market.get("soberanos") or []) + (ar_market.get("bopreal") or []):
        t = r["ticker"]
        m = re.fullmatch(r"BPO([A-D]\d)", t)
        out[t] = {"clase": "usd", "simbolo": f"BP{m.group(1)}D" if m else t + "D", "flujos": flujos.get(t), "metrica": "TIR" if t in flujos else None}
    for r in ar_market.get("pesos_fija") or []:
        out[r["ticker"]] = {"clase": "fija", "simbolo": r["ticker"], "vto": r["vto"], "pago_final": r.get("pago_final"),
                            "metrica": "TEM" if r.get("pago_final") else None}
    for r in ar_market.get("cer_tamar") or []:
        t = r["ticker"]
        fam = (bonos_cfg.get("cer") or {}).get(t)
        if r["tipo"] == "CER" and r.get("coef_cer") and not fam and r.get("cond"):
            c = r["cond"]
            fam = {"cer_inicial": c["cer_inicial"], "pago_mes_dia": [c["vto"][5:]],
                   "amortizacion": {"primera": c["vto"], "cuotas_pct": 100.0, "n": 1}, "cupones": [[c["emision"], 0.0]]}
        if r["tipo"] == "CER" and fam:
            out[t] = {"clase": "cer", "simbolo": t, "flujos": bonds.build_flows(fam), "cer_inicial": fam["cer_inicial"], "metrica": "TIR real"}
        else:
            out[t] = {"clase": "precio", "simbolo": t, "metrica": None}
    for r in ar_market.get("dolar_linked") or []:
        out[r["ticker"]] = {"clase": "dl", "simbolo": r["ticker"], "vto": r["vto"], "metrica": "TIR en US$"}
    return out
