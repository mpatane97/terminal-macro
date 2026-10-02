"""Corrida diaria (20 h): macro de EE.UU. y Argentina, Fed, curva de Treasuries, BCRA, riesgo país,
bandas, calendario y earnings. Escribe docs/data/daily.json."""
import io
import os
import re
from datetime import date, datetime, timedelta

import openpyxl

from common import (DATA, HIST, changes_from_series, http_get, load_config, log, now_iso, num, pct,
                    read_json, run_blocks, today_ar, write_json)

CFG = load_config("instruments.json")
FRED_KEY = os.environ.get("FRED_API_KEY", "")
FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "")
BCRA = "https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias"


# ---------- FRED ----------

def fred(series_id, start=None):
    if not FRED_KEY:
        raise RuntimeError("falta FRED_API_KEY")
    p = {"series_id": series_id, "api_key": FRED_KEY, "file_type": "json"}
    if start:
        p["observation_start"] = start
    js = http_get("https://api.stlouisfed.org/fred/series/observations", params=p)
    return [(o["date"], num(o["value"])) for o in js["observations"] if num(o["value"]) is not None]


def fred_next_release(series_id):
    try:
        rel = http_get("https://api.stlouisfed.org/fred/series/release",
                       params={"series_id": series_id, "api_key": FRED_KEY, "file_type": "json"})
        rid = rel["releases"][0]["id"]
        js = http_get("https://api.stlouisfed.org/fred/release/dates",
                      params={"release_id": rid, "api_key": FRED_KEY, "file_type": "json",
                              "realtime_start": today_ar().isoformat(), "include_release_dates_with_no_data": "true",
                              "sort_order": "asc", "limit": 3})
        fut = [d["date"] for d in js.get("release_dates", []) if d["date"] > today_ar().isoformat()]
        return fut[0] if fut else None
    except Exception as e:  # noqa: BLE001
        log.warning("próximo release %s: %s", series_id, e)
        return None


def _yoy(s, i):
    d = datetime.strptime(s[i][0], "%Y-%m-%d").date()
    target = date(d.year - 1, d.month, 1).isoformat()
    prev = [v for dd, v in s if dd == target]
    return pct(s[i][1], prev[0]) if prev else None


def us_macro():
    start = (today_ar() - timedelta(days=800)).isoformat()
    out = []

    def monthly_index(sid, nombre, tema):
        s = fred(sid, start)
        last, prev = s[-1], s[-2]
        out.append({"id": sid, "tema": tema, "nombre": nombre, "periodo": last[0][:7],
                    "valor": _yoy(s, -1), "anterior": _yoy(s, -2), "unidad": "% i.a.",
                    "mensual": pct(last[1], prev[1]), "proximo": fred_next_release(sid)})

    monthly_index("CPIAUCSL", "CPI", "Inflación")
    monthly_index("PCEPILFE", "Core PCE", "Inflación")

    s = fred("PAYEMS", start)
    out.append({"id": "PAYEMS", "tema": "Empleo", "nombre": "Nóminas no agrícolas", "periodo": s[-1][0][:7],
                "valor": s[-1][1] - s[-2][1], "anterior": s[-2][1] - s[-3][1], "unidad": "miles",
                "proximo": fred_next_release("PAYEMS")})
    s = fred("UNRATE", start)
    out.append({"id": "UNRATE", "tema": "Empleo", "nombre": "Desempleo", "periodo": s[-1][0][:7],
                "valor": s[-1][1], "anterior": s[-2][1], "unidad": "%", "proximo": fred_next_release("UNRATE")})
    s = fred("A191RL1Q225SBEA", start)
    trim = f"{s[-1][0][:4]} T{(int(s[-1][0][5:7]) - 1) // 3 + 1}"
    out.append({"id": "GDP", "tema": "Actividad", "nombre": "PBI (t/t anualizado)", "periodo": trim,
                "valor": s[-1][1], "anterior": s[-2][1], "unidad": "%", "proximo": fred_next_release("A191RL1Q225SBEA")})
    out.append(_ism())
    return out, "FRED (datos BLS, BEA); ISM: comunicado de prensa"


def _ism():
    row = {"id": "ISM", "tema": "Actividad", "nombre": "ISM manufacturero", "unidad": "pts",
           "valor": None, "anterior": None, "periodo": None, "proximo": None}
    try:
        r = http_get("https://www.prnewswire.com/news/institute-for-supply-management/", as_json=False)
        vals = re.findall(r"Manufacturing PMI®?\s*at\s*(\d{2}\.\d)%[;,]?\s*([A-Z][a-z]+)\s*(\d{4})", r.text)
        if vals:
            row["valor"], row["periodo"] = float(vals[0][0]), f"{vals[0][1]} {vals[0][2]}"
            if len(vals) > 1:
                row["anterior"] = float(vals[1][0])
    except Exception as e:  # noqa: BLE001
        log.warning("ISM: %s", e)
    return row


def fed():
    lo, hi = fred("DFEDTARL")[-1], fred("DFEDTARU")[-1]
    effr = None
    try:
        js = http_get("https://markets.newyorkfed.org/api/rates/unsecured/effr/last/1.json")
        r = js["refRates"][0]
        effr = {"valor": num(r["percentRate"]), "fecha": r["effectiveDate"]}
    except Exception as e:  # noqa: BLE001
        log.warning("EFFR: %s", e)
    today = today_ar().isoformat()
    proximas = [d for d in CFG["fomc_2026_2027"] if d >= today]
    return {"rango": [lo[1], hi[1]], "fecha_rango": hi[0], "effr": effr, "proximo_fomc": proximas[:1],
            "fomc": proximas[:4]}, "FRED / NY Fed / federalreserve.gov"


def treasuries():
    plazos = [("3m", "DGS3MO"), ("2y", "DGS2"), ("5y", "DGS5"), ("10y", "DGS10"), ("30y", "DGS30")]
    start = (today_ar() - timedelta(days=400)).isoformat()
    rows, mes = [], []
    for lab, sid in plazos:
        s = fred(sid, start)
        last = s[-1]
        d_last = datetime.strptime(last[0], "%Y-%m-%d").date()

        def at(days):
            t = (d_last - timedelta(days=days)).isoformat()
            c = [v for d, v in s if d <= t]
            return c[-1] if c else None
        m1 = at(30)
        rows.append({"plazo": lab, "tasa": last[1], "fecha": last[0],
                     "d_pb": (last[1] - s[-2][1]) * 100, "m_pb": (last[1] - m1) * 100 if m1 else None,
                     "y_pb": (last[1] - at(365)) * 100 if at(365) else None, "hace_1m": m1})
    t = {r["plazo"]: r["tasa"] for r in rows}
    spread = (t["10y"] - t["2y"]) * 100 if t.get("10y") and t.get("2y") else None
    return {"curva": rows, "spread_10_2_pb": spread}, "FRED (dato del Tesoro de EE.UU.), cierre diario"


# ---------- BCRA ----------

def _bcra_list():
    out, offset = [], 0
    while True:
        js = http_get(BCRA, params={"limit": 1000, "offset": offset}, timeout=30)
        res = js.get("results", [])
        out += res
        if len(res) < 1000:
            break
        offset += 1000
    return out


def _bcra_series(idv, days=400):
    d = today_ar()
    js = http_get(f"{BCRA}/{idv}", params={"desde": (d - timedelta(days=days)).isoformat(), "hasta": d.isoformat(),
                                             "limit": 3000}, timeout=30)
    det = js["results"][0]["detalle"] if js.get("results") else []
    return sorted((x["fecha"], num(x["valor"])) for x in det)


def ar_bcra():
    lst = _bcra_list()
    by_id = {v["idVariable"]: v for v in lst}

    def find(pattern):
        for v in lst:
            if re.search(pattern, v.get("descripcion", ""), re.I):
                return v["idVariable"]
        return None

    ids = {"a3500": 5, "reservas": 1, "compras": 78, "tamar": 44, "badlar": 7, "plazo_fijo": 12,
           "inflacion_m": 27, "inflacion_ia": 28, "rem_12m": 29,
           "cer": find(r"^\s*CER\b|Coeficiente de Estabilizaci"), "uva": find(r"\bUVA\b|Unidad de Valor Adquisitivo")}
    out = {}
    for k, idv in ids.items():
        v = by_id.get(idv) if idv else None
        if not v:
            out[k] = None
            continue
        out[k] = {"id": idv, "descripcion": v.get("descripcion"), "valor": num(v.get("ultValorInformado")),
                  "fecha": v.get("ultFechaInformada")}
    for k in ("a3500", "reservas"):
        if out.get(k):
            try:
                ch = changes_from_series(_bcra_series(out[k]["id"]))
                out[k].update({x: ch[x] for x in ("d", "w", "m", "y")})
            except Exception as e:  # noqa: BLE001
                log.warning("serie BCRA %s: %s", k, e)
    if out.get("compras"):
        try:
            s = _bcra_series(78, days=60)
            mes = out["compras"]["fecha"][:7]
            out["compras"]["mes_acum"] = sum(v for d, v in s if d.startswith(mes) and v is not None)
        except Exception as e:  # noqa: BLE001
            log.warning("compras BCRA: %s", e)
    return out, "API BCRA v4 (oficial)"


def ipc():
    start = (today_ar() - timedelta(days=800)).isoformat()
    base = "148.3_INIVELNAL_DICI_M_26"
    js = http_get("https://apis.datos.gob.ar/series/api/series/",
                  params={"ids": f"{base}:percent_change,{base}:percent_change_a_year_ago", "start_date": start,
                          "format": "json", "limit": 1000})
    rows = [r for r in js["data"] if r[1] is not None]
    last, prev = rows[-1], rows[-2]
    return {"periodo": last[0][:7], "mensual": last[1] * 100, "interanual": (last[2] or 0) * 100 if last[2] is not None else None,
            "mensual_anterior": prev[1] * 100}, "INDEC vía datos.gob.ar (oficial)"


def riesgo_pais():
    s = http_get("https://api.argentinadatos.com/v1/finanzas/indices/riesgo-pais")
    serie = [(r["fecha"][:10], num(r["valor"])) for r in s]
    ch = changes_from_series(serie)
    ch["d_pb"] = None
    pts = sorted(serie)
    if len(pts) > 1:
        ch["d_pb"] = pts[-1][1] - pts[-2][1]
    return ch, "argentinadatos.com (secundaria; EMBI de JP Morgan)"


def bandas():
    url = "https://www.bcra.gob.ar/archivos/Pdfs/PublicacionesEstadisticas/serie-completa-bandas-cambiarias.xlsx"
    r = http_get(url, as_json=False, timeout=40)
    wb = openpyxl.load_workbook(io.BytesIO(r.content), data_only=True, read_only=True)
    today = today_ar()
    best = None
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            dts = [c for c in row if isinstance(c, (datetime, date))]
            nums = [c for c in row if isinstance(c, (int, float)) and 100 < c < 100000]
            if dts and len(nums) >= 2:
                d = dts[0].date() if isinstance(dts[0], datetime) else dts[0]
                if d <= today and (best is None or d > best[0]):
                    best = (d, min(nums[:2]), max(nums[:2]))
    if not best:
        raise RuntimeError("no se encontró la fila de hoy en el Excel de bandas")
    return {"fecha": best[0].isoformat(), "piso": best[1], "techo": best[2]}, "BCRA (Excel de bandas, oficial)"


def dolares_hist():
    rows = http_get("https://api.argentinadatos.com/v1/cotizaciones/dolares", timeout=60)
    cutoff = (today_ar() - timedelta(days=400)).isoformat()
    h = {}
    for r in rows:
        if r.get("fecha", "") >= cutoff and num(r.get("venta")):
            h.setdefault(r["casa"], {})[r["fecha"][:10]] = num(r["venta"])
    write_json(HIST / "dolares.json", h)
    return {"casas": sorted(h)}, "argentinadatos.com"


def ar_backfill():
    """Completa historia de precios de bonos, acciones y CEDEARs desde data912 si todavía es corta."""
    hist = read_json(HIST / "ar_closes.json", {}) or {}
    a = CFG["argentina"]
    pedidos = [("bonds", t + "D") for t in a["soberanos_usd"] + a["bopreal"]] + \
              [("stocks", t) for t in a["acciones"]] + [("cedears", t) for t in a["cedears"]]
    hechos = 0
    cutoff = (today_ar() - timedelta(days=400)).isoformat()
    for kind, t in pedidos:
        if len(hist.get(t, {})) >= 200:
            continue
        try:
            rows = http_get(f"https://data912.com/historical/{kind}/{t}", timeout=30)
            for r in rows:
                d = str(r.get("date", ""))[:10]
                if d >= cutoff and num(r.get("c")):
                    hist.setdefault(t, {}).setdefault(d, num(r["c"]))
            hechos += 1
        except Exception as e:  # noqa: BLE001
            log.warning("historia %s: %s", t, e)
    write_json(HIST / "ar_closes.json", hist)
    return {"completados": hechos}, "data912.com (histórico)"


# ---------- Calendario y earnings ----------

def calendar_us():
    rows = http_get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
    out = [{"fecha": r.get("date"), "evento": r.get("title"), "impacto": r.get("impact"),
            "esperado": r.get("forecast") or None, "previo": r.get("previous") or None}
           for r in rows if r.get("country") == "USD" and r.get("impact") in ("High", "Medium")]
    return out, "Forex Factory (secundaria)"


def calendar_ar():
    c = load_config("calendario_ar.json")
    today = today_ar().isoformat()
    return [e for e in c["eventos"] if e["fecha"] >= today], "INDEC (carga manual)"


def earnings():
    if not FINNHUB_KEY:
        raise RuntimeError("falta FINNHUB_API_KEY")
    d = today_ar()
    js = http_get("https://finnhub.io/api/v1/calendar/earnings",
                  params={"from": d.isoformat(), "to": (d + timedelta(days=14)).isoformat(), "token": FINNHUB_KEY})
    universe = set(CFG["earnings_top20"]) | set(CFG.get("watchlist", []))
    out = [{"fecha": r["date"], "ticker": r["symbol"], "hora": {"bmo": "antes de apertura", "amc": "después del cierre"}.get(r.get("hour"), r.get("hour")),
            "eps_estimado": r.get("epsEstimate")}
           for r in js.get("earningsCalendar", []) if r.get("symbol") in universe]
    out.sort(key=lambda r: r["fecha"])
    return out, "Finnhub (secundaria)"


if __name__ == "__main__":
    run_blocks(DATA / "daily.json", {
        "us_macro": us_macro,
        "fed": fed,
        "treasuries": treasuries,
        "ar_bcra": ar_bcra,
        "ipc": ipc,
        "riesgo_pais": riesgo_pais,
        "bandas": bandas,
        "dolares_hist": dolares_hist,
        "ar_backfill": ar_backfill,
        "calendar_us": calendar_us,
        "calendar_ar": calendar_ar,
        "earnings": earnings,
    })
    log.info("daily.json actualizado %s", now_iso())
