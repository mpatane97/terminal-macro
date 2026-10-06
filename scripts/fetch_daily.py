"""Corrida diaria (20 h): macro de EE.UU. y Argentina, Fed, curva de Treasuries, BCRA, riesgo país,
bandas, calendario y earnings. Escribe docs/data/daily.json."""
import csv
import io
import os
import re
import time
from datetime import date, datetime, timedelta

import openpyxl

from common import (DATA, HIST, changes_from_series, http_get, load_config, log, now_iso, num, pct,
                    read_json, run_blocks, today_ar, write_json)

CFG = load_config("instruments.json")
BONOS = load_config("bonos.json")
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


MESES_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
            "November", "December"]


def _mes_es(mes, anio):
    return f"{anio}-{MESES_EN.index(mes) + 1:02d}" if mes in MESES_EN else f"{mes} {anio}"


def _ism():
    row = {"id": "ISM", "tema": "Actividad", "nombre": "ISM manufacturero", "unidad": "pts",
           "valor": None, "anterior": None, "periodo": None, "proximo": None}
    try:
        r = http_get("https://www.prnewswire.com/news/institute-for-supply-management/", as_json=False)
        vals = re.findall(r"Manufacturing PMI®?\s*at\s*(\d{2}(?:\.\d)?)%[;,]?\s*([A-Z][a-z]+)\s*(\d{4})", r.text)
        unicos = []
        for v in vals:  # el mismo titular aparece varias veces en la página
            if v not in unicos:
                unicos.append(v)
        if unicos:
            row["valor"], row["periodo"] = float(unicos[0][0]), _mes_es(unicos[0][1], unicos[0][2])
            if len(unicos) > 1:
                row["anterior"] = float(unicos[1][0])
    except Exception as e:  # noqa: BLE001
        log.warning("ISM: %s", e)
    return row


_MESES_EN = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                         "september", "october", "november", "december"], 1)}


def _fomc_web():
    """Fechas de decisión del FOMC (último día de cada reunión) desde el calendario oficial de la Fed."""
    html = http_get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", as_json=False, timeout=30).text
    out = []
    partes = re.split(r"(\d{4}) FOMC Meetings", html)
    for i in range(1, len(partes) - 1, 2):
        anio, bloque = int(partes[i]), partes[i + 1]
        meses = re.findall(r'fomc-meeting__month[^>]*>\s*(?:<[^>]+>\s*)*([A-Za-z/]+)', bloque)
        dias = re.findall(r'fomc-meeting__date[^>]*>\s*(?:<[^>]+>\s*)*([\d\-–]+)', bloque)
        for mes, dd in zip(meses, dias):
            partes_d = [x for x in re.split(r"[-–]", dd) if x]
            ultimo_dia = partes_d[-1]
            # "Apr/May 30-1": si el último día es menor que el primero, la decisión cae en el segundo mes
            cruza = len(partes_d) > 1 and partes_d[-1].isdigit() and partes_d[0].isdigit() and int(partes_d[-1]) < int(partes_d[0])
            ultimo_mes = mes.split("/")[-1 if cruza else 0].lower()
            mm = next((v for k, v in _MESES_EN.items() if k.startswith(ultimo_mes[:3])), None)
            if mm and ultimo_dia.isdigit():
                out.append(date(anio, mm, int(ultimo_dia)).isoformat())
    out = sorted(set(out))
    if len(out) < 8:
        raise RuntimeError(f"calendario FOMC: sólo {len(out)} fechas leídas")
    return out


def fed():
    lo, hi = fred("DFEDTARL", (today_ar() - timedelta(days=400)).isoformat())[-1], fred("DFEDTARU", (today_ar() - timedelta(days=400)).isoformat())[-1]
    effr = None
    try:
        js = http_get("https://markets.newyorkfed.org/api/rates/unsecured/effr/last/1.json")
        r = js["refRates"][0]
        effr = {"valor": num(r["percentRate"]), "fecha": r["effectiveDate"]}
    except Exception as e:  # noqa: BLE001
        log.warning("EFFR: %s", e)
    today = today_ar().isoformat()
    try:
        fechas = _fomc_web()
    except Exception as e:  # noqa: BLE001
        log.warning("calendario FOMC: %s (uso config)", e)
        fechas = []
    proximas = sorted({d for d in fechas + CFG.get("fomc_2026_2027", []) if d >= today}) if not fechas else [d for d in fechas if d >= today]
    return {"rango": [lo[1], hi[1]], "fecha_rango": hi[0], "effr": effr, "proximo_fomc": proximas[:1],
            "fomc": proximas[:4], "dot_plot": _dot_plot()}, "FRED / NY Fed / federalreserve.gov"


def _dot_plot():
    """Mediana de la tasa de fed funds del último Resumen de Proyecciones (SEP)."""
    try:
        cal = http_get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", as_json=False).text
        fechas = sorted(set(re.findall(r"fomcprojtabl(\d{8})\.htm", cal)))
        if not fechas:
            return None
        f = fechas[-1]
        html = http_get(f"https://www.federalreserve.gov/monetarypolicy/fomcprojtabl{f}.htm", as_json=False).text
        texto = re.sub(r"<[^>]+>", " ", html)
        texto = re.sub(r"\s+", " ", texto)
        i = texto.find("Federal funds rate")
        if i < 0:
            return None
        cab = texto[:i]
        anios = []
        for y in re.findall(r"\b(20\d\d)\b", cab[cab.rfind("Median"):] if "Median" in cab else cab[-600:]):
            if y not in anios:
                anios.append(y)
        vals = re.findall(r"-?\d+\.\d", texto[i:i + 300])
        cols = anios[:len(vals) - 1] + ["Largo plazo"] if len(vals) > len(anios) else anios
        n = min(len(cols), len(vals), 5)
        return {"fecha": f"{f[:4]}-{f[4:6]}-{f[6:]}", "mediana": [{"periodo": cols[k], "tasa": float(vals[k])} for k in range(n)]}
    except Exception as e:  # noqa: BLE001
        log.warning("dot plot: %s", e)
        return None


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


def _habiles_atras(d, n):
    """Retrocede n días hábiles de Argentina (descuenta fines de semana y feriados)."""
    import feriados
    return feriados.sumar_habiles(d, -n)


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
    if out.get("cer"):
        try:
            s_cer = _bcra_series(out["cer"]["id"], days=40)
            ref = _habiles_atras(today_ar() + timedelta(days=1), 10).isoformat()
            cand = [(d, v) for d, v in s_cer if d <= ref and v is not None]
            if cand:
                out["cer_t10"] = {"fecha": cand[-1][0], "valor": cand[-1][1]}
        except Exception as e:  # noqa: BLE001
            log.warning("CER t-10: %s", e)
    if out.get("compras"):
        try:
            s = _bcra_series(78, days=60)
            mes = out["compras"]["fecha"][:7]
            out["compras"]["mes_acum"] = sum(v for d, v in s if d.startswith(mes) and v is not None)
            s_anio = _bcra_series(78, days=(today_ar() - date(today_ar().year, 1, 1)).days + 1)
            out["compras"]["anio_acum"] = sum(v for d, v in s_anio if d.startswith(str(today_ar().year)) and v is not None)
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
    def usd(t):
        m = re.fullmatch(r"BPO([A-D]\d)", t)
        return f"BP{m.group(1)}D" if m else t + "D"
    pg = (read_json(HIST / "panel_general.json", {}) or {}).get("tickers", [])
    acciones = list(dict.fromkeys(a["acciones"] + a.get("panel_lider", []) + pg))
    pedidos = [("bonds", usd(t)) for t in a["soberanos_usd"] + a["bopreal"]] + \
              [("stocks", t) for t in acciones] + [("cedears", t) for t in a["cedears"]]
    hechos, errores = 0, {}
    cutoff = (today_ar() - timedelta(days=400)).isoformat()
    for kind, t in pedidos:
        if len(hist.get(t, {})) >= 200:
            continue
        try:
            rows = http_get(f"https://data912.com/historical/{kind}/{t}", timeout=30)
            if not isinstance(rows, list):
                raise RuntimeError(f"respuesta inesperada: {str(rows)[:100]}")
            for r in rows:
                d = str(r.get("date", ""))[:10]
                if d >= cutoff and num(r.get("c")):
                    hist.setdefault(t, {}).setdefault(d, num(r["c"]))
            hechos += 1
        except Exception as e:  # noqa: BLE001
            log.warning("historia %s: %s", t, e)
            errores[t] = str(e)[:120]
    write_json(HIST / "ar_closes.json", hist)
    return {"completados": hechos, "errores": errores}, "data912.com (histórico)"


def emae():
    ids = "143.3_NO_PR_2004_A_31,143.3_NO_PR_2004_A_21"
    js = http_get("https://apis.datos.gob.ar/series/api/series/",
                  params={"ids": f"143.3_NO_PR_2004_A_31:percent_change,143.3_NO_PR_2004_A_21:percent_change_a_year_ago",
                          "start_date": (today_ar() - timedelta(days=500)).isoformat(), "format": "json", "limit": 1000})
    rows = [r for r in js["data"] if r[1] is not None]
    last, prev = rows[-1], rows[-2]
    return {"periodo": last[0][:7], "mensual_desest": last[1] * 100, "interanual": last[2] * 100 if last[2] is not None else None,
            "mensual_anterior": prev[1] * 100}, "INDEC vía datos.gob.ar (oficial)"


def rem():
    rows = http_get("https://api.argentinadatos.com/v1/finanzas/rem/ultimo")
    rows = [r for r in rows if r.get("muestra", "todos") == "todos"]
    ipc = [r for r in rows if str(r.get("indicador", "")).startswith("Precios minoristas (IPC nivel general")]
    mens = sorted((r for r in ipc if r.get("periodoTipo") == "mensual"), key=lambda r: r.get("periodoDesde") or "")
    hoy = today_ar().isoformat()[:7]
    mens = [r for r in mens if (r.get("periodoDesde") or "")[:7] >= hoy][:6] or mens[-6:]
    p12 = next((r for r in ipc if r.get("periodoTipo") == "proximos_12_meses"), None)
    anual = [r for r in ipc if r.get("periodoTipo") == "anual"]

    def serie(nombre):
        rs = [r for r in rows if r.get("indicador") == nombre and r.get("periodoTipo") == "mensual"]
        rs.sort(key=lambda r: r.get("periodoDesde") or "")
        return [{"mes": (r.get("periodoDesde") or "")[:7], "mediana": num(r.get("mediana"))} for r in rs
                if (r.get("periodoDesde") or "")[:7] >= hoy][:4]
    return {"informe": rows[0].get("informe") if rows else None,
            "ipc_mensual": [{"mes": (r.get("periodoDesde") or "")[:7], "mediana": num(r.get("mediana"))} for r in mens],
            "ipc_12m": num(p12.get("mediana")) if p12 else None,
            "ipc_anual": [{"anio": r.get("periodo"), "mediana": num(r.get("mediana"))} for r in anual],
            "tipo_cambio": serie("Tipo de cambio nominal"), "tamar": serie("Tasa de interés (TAMAR)")}, \
        "REM del BCRA vía argentinadatos.com"


def us_senales():
    """Regla de Sahm: promedio móvil de 3 meses del desempleo menos su mínimo de los 12 meses previos."""
    s_ = fred("UNRATE", (today_ar() - timedelta(days=800)).isoformat())
    v = [x for _, x in s_]
    m3 = [sum(v[i - 2:i + 1]) / 3 for i in range(2, len(v))]
    sahm = m3[-1] - min(m3[-13:-1]) if len(m3) >= 13 else None
    return {"sahm": sahm, "desempleo_min12": min(v[-13:-1]) if len(v) >= 13 else None}, "FRED (BLS); cálculo propio"


def megacaps_info():
    """Capitalización de mercado (USD) de las empresas grandes, una vez por día."""
    import yfinance as yf
    tasas = {"SAR": 1 / 3.75}
    out = {}
    from concurrent.futures import ThreadPoolExecutor

    def una(it):
        try:
            fi = yf.Ticker(it["yahoo"]).fast_info
            cap = getattr(fi, "market_cap", None)
            cur = (getattr(fi, "currency", None) or "USD").upper()
            if cap:
                return it["id"], (cap * tasas.get(cur, 1.0) / 1e9 if cur in tasas or cur == "USD" else None)
        except Exception as e:  # noqa: BLE001
            log.warning("market cap %s: %s", it["id"], e)
        return it["id"], None

    items = [it for g in ("megacaps_eeuu", "megacaps_global", "empresas_seleccion") for it in CFG["mercados"].get(g, [])]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for k, v in ex.map(una, items):
            if v is not None:
                out[k] = v
    if not out:
        raise RuntimeError("sin capitalizaciones")
    return out, "Yahoo Finance (yfinance), miles de millones de USD"


def calendar_intl():
    rows = http_get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
    nombres = {"EUR": "Eurozona", "GBP": "Reino Unido", "JPY": "Japón", "CNY": "China"}
    datos = [{"fecha": r.get("date"), "pais": nombres[r["country"]], "evento": r.get("title"),
              "esperado": r.get("forecast") or None, "previo": r.get("previous") or None}
             for r in rows if r.get("country") in nombres and r.get("impact") == "High"
             and not re.search(r"speaks|speech|testifies|remarks", r.get("title", ""), re.I)]
    hoy = today_ar().isoformat()
    bancos = [{"fecha": f, "hora": v.get("hora"), "banco": k}
              for k, v in CFG.get("bancos_centrales", {}).items() if not k.startswith("_") for f in v["fechas"] if f >= hoy]
    bancos.sort(key=lambda r: r["fecha"])
    return {"datos_semana": datos, "bancos": bancos}, "Forex Factory (datos) y bancos centrales (fechas oficiales)"


# ---------- Calendario y earnings ----------

def calendar_us():
    rows = http_get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
    out = [{"fecha": r.get("date"), "evento": r.get("title"), "impacto": r.get("impact"),
            "esperado": r.get("forecast") or None, "previo": r.get("previous") or None}
           for r in rows if r.get("country") == "USD" and r.get("impact") in ("High", "Medium")
           and not re.search(r"speaks|speech|testifies|remarks", r.get("title", ""), re.I)]
    return out, "Forex Factory (secundaria)"


def _vto_futuro(simbolo):
    """DLR102026 vence el último día hábil de octubre de 2026."""
    import feriados
    m = re.fullmatch(r"DLR(\d{2})(\d{4})", simbolo)
    if not m:
        return None
    mes, anio = int(m.group(1)), int(m.group(2))
    d = (date(anio + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1))
    while not feriados.es_habil(d):
        d -= timedelta(days=1)
    return d


def futuros_dolar():
    """Dólar futuro de A3 (ex Matba-Rofex): precios de cierre oficiales y tasas implícitas contra el mayorista."""
    hoy = today_ar()
    filas = []
    try:
        js = http_get("https://apicem.matbarofex.com.ar/api/v2/closing-prices",
                      params={"product": "DLR", "segment": "Monedas", "type": "FUT", "excludeEmptyVol": "false",
                              "from": (hoy - timedelta(days=10)).isoformat(), "to": hoy.isoformat(),
                              "page": 1, "pageSize": 500, "sortDir": "ASC"}, timeout=30)
        ultimo = {}
        for r in js.get("data", []):
            sym = r.get("symbol", "")
            if re.fullmatch(r"DLR\d{6}", sym) and (r.get("settlement") or r.get("close")):
                if sym not in ultimo or r["dateTime"] > ultimo[sym]["dateTime"]:
                    ultimo[sym] = r
        filas = [{"especie": k, "precio": num(v.get("settlement") or v.get("close")), "fecha": v["dateTime"][:10],
                  "vol": v.get("volume"), "interes_abierto": num(v.get("openInterest")), "var": num(v.get("changePercent"))}
                 for k, v in ultimo.items()]
        fuente = "A3 Mercados (cierres oficiales)"
    except Exception as e:  # noqa: BLE001
        log.warning("futuros A3: %s", e)
    if not filas:
        raise RuntimeError("A3 no devolvió contratos de dólar futuro")
    # dólar base: mayorista A3500 (último dato del BCRA)
    try:
        spot = _bcra_series(5, days=10)[-1][1]
    except Exception:  # noqa: BLE001
        spot = None
    out = []
    for f in filas:
        vto = _vto_futuro(f["especie"])
        if not vto or vto < hoy:
            continue
        dias = (vto - hoy).days
        f.update({"vto": vto.isoformat(), "dias": dias})
        if spot and f["precio"] and dias > 0:
            r = f["precio"] / spot
            f.update({"tasa_efectiva": (r - 1) * 100, "tna": (r - 1) * 365 / dias * 100, "tea": (r ** (365 / dias) - 1) * 100,
                      "tem": (r ** (30 / dias) - 1) * 100})
        out.append(f)
    out.sort(key=lambda x: x["vto"])
    return {"spot": spot, "contratos": out[:14]}, fuente


_MESES_ES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}


def _fechas_texto(txt, anio):
    """Todas las fechas de un texto, en orden: 28/10/2026, 28/10/26, 28/10, 28-oct, 28 de octubre (de 2026)."""
    out = []
    patron = r"(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?|(\d{1,2})[-\s](?:de\s+)?([a-záéíóú]{3,10})\.?(?:[-\s](?:de\s+)?(\d{4}))?"
    for m in re.finditer(patron, txt, re.I):
        try:
            if m.group(1):
                y = int(m.group(3)) if m.group(3) else anio
                out.append(date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1))))
            else:
                mm = _MESES_ES.get(m.group(5)[:3].lower())
                if mm:
                    out.append(date(int(m.group(6)) if m.group(6) else anio, mm, int(m.group(4))))
        except ValueError:
            pass
    return out


_MESES_NOM = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _color(c):
    if c is None:
        return None
    if isinstance(c, (int, float)):
        c = (c, c, c)
    c = tuple(round(float(x), 2) for x in c)
    if len(c) == 4:  # CMYK -> RGB aproximado
        k = c[3]
        c = tuple(round((1 - x) * (1 - k), 2) for x in c[:3])
    return c


def _lic_desde_pdf(contenido, anio):
    """El cronograma es un calendario anual: cada día de llamado, licitación y liquidación está pintado de un
    color, explicado en la leyenda de arriba ("Llamado", "Licitación", "Liquidación"). Se lee el color de fondo
    detrás de cada número de día."""
    import io
    import pdfplumber
    eventos = {"llamado": [], "licitacion": [], "liquidacion": []}
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        leyenda = {}
        for page in pdf.pages:
            words = page.extract_words(extra_attrs=["non_stroking_color"])
            rects = [r for r in page.rects if r.get("fill")] + [c for c in getattr(page, "curves", []) if c.get("fill")]
            def fondo(w):
                cx, cy = (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2
                cands = [r for r in rects if r["x0"] - 1 <= cx <= r["x1"] + 1 and r["top"] - 1 <= cy <= r["bottom"] + 1
                         and (r["x1"] - r["x0"]) < 60 and (r["bottom"] - r["top"]) < 40]
                cands.sort(key=lambda r: (r["x1"] - r["x0"]) * (r["bottom"] - r["top"]))
                return _color(cands[0].get("non_stroking_color")) if cands else None
            # leyenda: el cuadradito de color a la izquierda de cada palabra
            for w in words:
                clave = {"llamado": "llamado", "licitación": "licitacion", "licitacion": "licitacion", "liquidación": "liquidacion", "liquidacion": "liquidacion"}.get(w["text"].lower())
                if clave and clave not in leyenda:
                    cy = (w["top"] + w["bottom"]) / 2
                    cerca = [r for r in rects if r["x1"] <= w["x0"] + 2 and w["x0"] - r["x1"] < 40 and r["top"] - 3 <= cy <= r["bottom"] + 3]
                    if cerca:
                        leyenda[clave] = _color(max(cerca, key=lambda r: r["x1"]).get("non_stroking_color"))
                    else:
                        leyenda[clave] = _color(w.get("non_stroking_color"))
            # meses: encabezados con su posición; cada número de día pertenece al encabezado más cercano por arriba en su columna
            meses = [(w, _MESES_NOM.index(w["text"].lower()) + 1) for w in words if w["text"].lower() in _MESES_NOM]
            for w in words:
                if not re.fullmatch(r"\d{1,2}", w["text"]):
                    continue
                arriba = [(m, n) for m, n in meses if m["top"] < w["top"] and abs((m["x0"] + m["x1"]) / 2 - (w["x0"] + w["x1"]) / 2) < page.width / 4]
                if not arriba:
                    continue
                mes = max(arriba, key=lambda x: x[0]["top"])[1]
                col = fondo(w) or _color(w.get("non_stroking_color"))
                for clave, c in leyenda.items():
                    if c and col and all(abs(a - b) < 0.06 for a, b in zip(c, col)):
                        try:
                            eventos[clave].append(date(anio, mes, int(w["text"])))
                        except ValueError:
                            pass
    return eventos, leyenda


def _licitaciones():
    """Fechas de licitación del Tesoro, del cronograma anual (PDF) de la Secretaría de Finanzas."""
    from urllib.parse import urljoin
    hoy = today_ar()
    ev = []
    for anio in (hoy.year, hoy.year + 1):
        url = f"https://www.argentina.gob.ar/economia/finanzas/licitaciones-de-letras-y-bonos-del-tesoro/cronograma-{anio}"
        try:
            html = http_get(url, as_json=False, timeout=30).text
        except Exception as e:  # noqa: BLE001
            log.warning("cronograma licitaciones %s: %s", anio, e)
            continue
        for pdf in dict.fromkeys(re.findall(r'href="([^"]+\.pdf)"', html, re.I)):
            try:
                contenido = http_get(urljoin(url, pdf), as_json=False, timeout=30).content
                (HIST / f"licitaciones_{anio}.pdf").write_bytes(contenido)  # copia para revisar el formato
                fechas, leyenda = _lic_desde_pdf(contenido, anio)
                log.info("cronograma %s: leyenda %s, %s", anio, leyenda, {k: len(v) for k, v in fechas.items()})
            except Exception as e:  # noqa: BLE001
                log.warning("cronograma PDF %s: %s", pdf, e)
                continue
            liqs = sorted(set(fechas["liquidacion"]))
            for lic in sorted(set(fechas["licitacion"])):
                liq = next((d for d in liqs if 0 <= (d - lic).days <= 7), None)
                if lic >= hoy:
                    ev.append({"fecha": lic.isoformat(), "hora": "15:00", "tipo": "licitacion",
                               "evento": "Licitación del Tesoro" + (f" (liquida {liq.strftime('%d/%m')})" if liq else "")})
            if fechas["licitacion"]:
                break
    vistos = set()
    return [e for e in sorted(ev, key=lambda x: x["fecha"]) if not (e["fecha"] in vistos or vistos.add(e["fecha"]))]


def _pagos_deuda():
    """Pagos de bonos soberanos y BOPREAL (de los flujos cargados) y vencimientos de letras y bonos en pesos."""
    import bonds
    hoy = today_ar()
    lim = hoy + timedelta(days=200)
    ev = {}
    import feriados
    for nombre, fam in BONOS.get("familias", {}).items():
        for d, c, a in bonds.build_flows(fam):
            # sólo los pagos grandes: los cupones mensuales chicos (AO27, AO28…) sin amortización no se muestran
            if hoy <= d <= lim and (a > 0 or not fam.get("fin_de_mes")):
                while not feriados.es_habil(d):
                    d += timedelta(days=1)
                k = ev.setdefault(d.isoformat(), {"tks": set(), "amort": False})
                k["tks"].update(fam["tickers"]); k["amort"] |= a > 0
    out = []
    for f, k in sorted(ev.items()):
        out.append({"fecha": f, "hora": None, "tipo": "pago",
                    "evento": f"Pago de bonos en dólares ({'cupón y amortización' if k['amort'] else 'cupón'}): {', '.join(sorted(k['tks']))}"})
    prices = read_json(DATA / "prices.json", {}) or {}
    arm = ((prices.get("ar_market") or {}).get("data")) or {}
    venc = {}
    for r in (arm.get("pesos_fija") or []) + (arm.get("dolar_linked") or []) + [x for x in (arm.get("cer_tamar") or []) if x.get("vto")]:
        v = r.get("vto")
        if v and hoy.isoformat() <= v <= lim.isoformat():
            venc.setdefault(v, []).append(r["ticker"])
    for v, tks in sorted(venc.items()):
        out.append({"fecha": v, "hora": None, "evento": f"Vencimiento en pesos: {', '.join(tks)}", "tipo": "pago"})
    return sorted(out, key=lambda e: e["fecha"])


def calendar_ar():
    """Calendario del INDEC leído de sus PDF semestrales. Lo cargado a mano en config/calendario_ar.json
    (licitaciones u otros eventos) se suma; si el PDF no responde, queda sólo eso."""
    import indec
    hoy = today_ar().isoformat()
    auto, leidos = indec.calendario()
    manual = [e for e in load_config("calendario_ar.json").get("eventos", []) if e["fecha"] >= hoy]
    tipo = lambda e: e["evento"].split(" ")[0].upper()  # noqa: E731
    claves = {(e["fecha"], tipo(e)) for e in auto}
    eventos = sorted(auto + [e for e in manual if (e["fecha"], tipo(e)) not in claves], key=lambda e: e["fecha"])
    if not eventos:
        raise RuntimeError("sin eventos futuros del INDEC")
    for e in eventos:
        e.setdefault("tipo", "indec")
    try:
        lic = _licitaciones()
    except Exception as e:  # noqa: BLE001
        log.warning("licitaciones: %s", e)
        lic = []
    try:
        pagos = _pagos_deuda()
    except Exception as e:  # noqa: BLE001
        log.warning("pagos de deuda: %s", e)
        pagos = []
    eventos = sorted(eventos + lic + pagos, key=lambda e: e["fecha"])
    fuente = "INDEC, calendario de difusión (PDF)" if auto else "INDEC (carga manual; el PDF no respondió)"
    fuente += f" · Finanzas, cronograma de licitaciones ({len(lic)})" + " · pagos: flujos propios"
    return eventos, fuente + (f" · {'; '.join(leidos)}" if leidos else "")


def earnings():
    if not FINNHUB_KEY:
        raise RuntimeError("falta FINNHUB_API_KEY")
    d = today_ar()
    mega = [it["id"] for g in ("megacaps_eeuu", "megacaps_global", "empresas_seleccion") for it in CFG["mercados"].get(g, [])]
    universe = set(CFG["earnings_top20"]) | set(CFG.get("watchlist", [])) | set(mega)
    # Finnhub recorta los pedidos por rango: se consulta empresa por empresa. Límite: 60 por minuto y 30 por
    # segundo; con menos de 50 empresas se piden en paralelo sin esperar (antes, 1 por segundo: ~45 s).
    from concurrent.futures import ThreadPoolExecutor
    pausa = 0 if len(universe) <= 50 else 1.1

    def una(sym):
        for intento in range(2):
            try:
                r = http_get("https://finnhub.io/api/v1/calendar/earnings",
                             params={"symbol": sym, "from": d.isoformat(), "to": (d + timedelta(days=90)).isoformat(),
                                     "token": FINNHUB_KEY}, retries=0).get("earningsCalendar", [])
                time.sleep(pausa)
                return r
            except Exception as e:  # noqa: BLE001
                if intento:
                    log.warning("earnings %s: %s", sym, e)
                time.sleep(3)  # probablemente el límite por segundo: se espera y se reintenta una vez
        return []
    filas = []
    with ThreadPoolExecutor(max_workers=4 if not pausa else 1) as ex:
        for r in ex.map(una, sorted(universe)):
            filas += r
    js = {"earningsCalendar": filas}
    out = [{"fecha": r["date"], "ticker": r["symbol"], "hora": {"bmo": "antes de apertura", "amc": "después del cierre"}.get(r.get("hour"), r.get("hour")),
            "eps_estimado": r.get("epsEstimate")}
           for r in js.get("earningsCalendar", []) if r.get("symbol") in universe]
    out.sort(key=lambda r: r["fecha"])
    return out, "Finnhub (secundaria)"


def feriados_block():
    import feriados
    f = feriados.actualizar()
    hoy = today_ar().isoformat()
    return {k: [r for r in v if r["fecha"] >= hoy][:40] for k, v in f.items()}, "argentinadatos (Argentina); librería holidays (bolsas del exterior)"


def cer_auto():
    """Altas automáticas de bonos y letras CER cero cupón (TZX…, X…)."""
    import lecaps
    tickers = _tickers_d912()
    if not tickers:
        raise RuntimeError("data912 no devolvió tickers")
    lst = _bcra_list()
    idv = next((v["idVariable"] for v in lst if re.search(r"^\s*CER\b|Coeficiente de Estabilizaci", v.get("descripcion", ""), re.I)), None)
    if not idv:
        raise RuntimeError("no se encontró la serie CER en el BCRA")

    def cer_en(fecha):
        d = date.fromisoformat(fecha)
        js = http_get(f"{BCRA}/{idv}", params={"desde": (d - timedelta(days=10)).isoformat(), "hasta": d.isoformat(), "limit": 100}, timeout=30)
        det = sorted((x["fecha"], num(x["valor"])) for x in (js["results"][0]["detalle"] if js.get("results") else []))
        cand = [v for f, v in det if f <= fecha and v]
        return cand[-1] if cand else None

    manuales = {t: f["cer_inicial"] for t, f in BONOS.get("cer", {}).items()}
    vtos = {t: (f.get("amortizacion") or {}).get("primera") for t, f in BONOS.get("cer", {}).items() if (f.get("amortizacion") or {}).get("primera")}
    terms, resumen = lecaps.actualizar_cer(tickers, manuales, cer_en, vtos)
    resumen["automaticos"] = sorted(t for t, e in terms.items() if e.get("cer_inicial") and t not in manuales)
    return resumen, "BYMA ficha técnica + CER del BCRA"


def avisos():
    """Datos que dependen de calendarios y están por quedarse sin fechas futuras."""
    hoy = today_ar()
    lim = (hoy + timedelta(days=45)).isoformat()
    out = []
    for k, v in CFG.get("bancos_centrales", {}).items():
        if k.startswith("_"):
            continue
        if not any(f >= hoy.isoformat() for f in v.get("fechas", [])):
            out.append(f"Calendario de {v.get('nombre', k)}: no quedan fechas cargadas")
    cal = read_json(DATA / "daily.json", {}) or {}
    ar = ((cal.get("calendar_ar") or {}).get("data")) or []
    if not any("IPC" in e.get("evento", "") and e["fecha"] <= lim for e in ar):
        out.append("Calendario INDEC: no hay fecha de IPC en los próximos 45 días")
    return out, "controles propios"


import threading
_lock912 = threading.Lock()
_cache912 = {}


def _tickers_d912():
    """Lista de tickers de bonos y letras de data912, pedida una sola vez por corrida (varios bloques la usan
    en paralelo y data912 corta si recibe muchos pedidos juntos)."""
    with _lock912:
        if "t" not in _cache912:
            t = []
            for path in ("/live/arg_notes", "/live/arg_bonds"):
                for intento in range(3):
                    try:
                        t += [r.get("symbol") for r in http_get(f"https://data912.com{path}", timeout=30) if r.get("symbol")]
                        break
                    except Exception as e:  # noqa: BLE001
                        log.warning("data912 %s (intento %s): %s", path, intento + 1, e)
                        time.sleep(5 * (intento + 1))
            _cache912["t"] = t
        return list(_cache912["t"])


def licitaciones_resultado():
    """Últimos resultados de licitación del Tesoro (Secretaría de Finanzas)."""
    import licitaciones
    r = licitaciones.resultados(4)
    if not r or not any(x["instrumentos"] or x["adjudicado"] for x in r):
        raise RuntimeError("no se pudieron leer resultados de licitación")
    return r, "Secretaría de Finanzas (resultados de licitación)"


def tasas_bancos_centrales():
    """Tasa de política vigente de los bancos centrales que sigue la terminal."""
    out = []
    # Fed: rango objetivo (FRED)
    try:
        lo, hi = fred("DFEDTARL", (today_ar() - timedelta(days=400)).isoformat())[-1], fred("DFEDTARU", (today_ar() - timedelta(days=400)).isoformat())[-1]
        out.append({"banco": "Fed", "tasa": hi[1], "detalle": f"rango {lo[1]:.2f}–{hi[1]:.2f}%", "fecha": hi[0]})
    except Exception as e:  # noqa: BLE001
        log.warning("tasa Fed: %s", e)
    # BCE: tasa de la facilidad de depósito (la que guía el mercado)
    try:
        f, v = fred("ECBDFR", (today_ar() - timedelta(days=400)).isoformat())[-1]
        out.append({"banco": "BCE", "tasa": v, "detalle": "facilidad de depósito", "fecha": f})
    except Exception as e:  # noqa: BLE001
        log.warning("tasa BCE: %s", e)
    # Banco de Inglaterra: Bank Rate (base de datos del BoE)
    try:
        hoy = today_ar()
        txt = http_get("https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp",
                       params={"csv.x": "yes", "Datefrom": (hoy - timedelta(days=120)).strftime("%d/%b/%Y"), "Dateto": "now",
                               "SeriesCodes": "IUDBEDR", "CSVF": "TN", "UsingCodes": "Y", "VPD": "Y", "VFD": "N"},
                       headers={"User-Agent": "Mozilla/5.0"}, as_json=False, timeout=30).text
        filas = [l.split(",") for l in txt.strip().splitlines()[1:] if "," in l]
        f, v = filas[-1][0], num(filas[-1][1])
        out.append({"banco": "Banco de Inglaterra", "tasa": v, "detalle": "Bank Rate", "fecha": datetime.strptime(f.strip(), "%d %b %Y").date().isoformat()})
    except Exception as e:  # noqa: BLE001
        log.warning("tasa BoE: %s", e)
    # Banco de Japón y Brasil: base de tasas de política del BIS (diaria, todos los bancos centrales)
    bis = {}
    try:
        txt = http_get("https://stats.bis.org/api/v1/data/WS_CBPOL/D.JP+BR/all",
                       params={"startPeriod": (today_ar() - timedelta(days=60)).isoformat(), "format": "csv"},
                       headers={"User-Agent": "Mozilla/5.0"}, as_json=False, timeout=30).text
        for r in csv.DictReader(io.StringIO(txt)):
            if r.get("OBS_VALUE") not in (None, "", "NaN"):
                bis[r["REF_AREA"]] = (r["TIME_PERIOD"], float(r["OBS_VALUE"]))  # filas en orden: queda la última
    except Exception as e:  # noqa: BLE001
        log.warning("tasas BIS: %s", e)
    if "JP" in bis:
        out.append({"banco": "Banco de Japón", "tasa": bis["JP"][1], "detalle": "call rate objetivo", "fecha": bis["JP"][0]})
    else:
        log.warning("tasa BoJ: el BIS no devolvió dato")
    # Brasil: meta Selic (Banco Central do Brasil, SGS 432); si no responde, BIS
    try:
        r = http_get("https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1", params={"formato": "json"},
                     headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=30)[-1]
        d, m, y = r["data"].split("/")
        out.append({"banco": "Banco Central de Brasil (Copom)", "tasa": num(r["valor"]), "detalle": "meta Selic", "fecha": f"{y}-{m}-{d}"})
    except Exception as e:  # noqa: BLE001
        log.warning("tasa Selic (BCB): %s", e)
        if "BR" in bis:
            out.append({"banco": "Banco Central de Brasil (Copom)", "tasa": bis["BR"][1], "detalle": "meta Selic", "fecha": bis["BR"][0]})
    if not out:
        raise RuntimeError("ningún banco central respondió")
    return out, "FRED (Fed, BCE), Bank of England, BIS (BoJ), Banco Central do Brasil (respaldo: BIS)"


def fichas_bonos():
    """Historia de un año (precio y TIR/TEM) de cada bono y letra, un archivo por papel para la ficha."""
    import fichas
    am = (((read_json(DATA / "prices.json", {}) or {}).get("ar_market") or {}).get("data")) or {}
    if not am:
        raise RuntimeError("todavía no hay precios de Argentina")
    papeles = fichas.papeles_de(am, BONOS, today_ar())
    cer = a35 = None
    if any(p["clase"] == "cer" for p in papeles.values()):
        try:
            cer_id = ((((read_json(DATA / "daily.json", {}) or {}).get("ar_bcra") or {}).get("data") or {}).get("cer") or {}).get("id")
            if not cer_id:
                cer_id = next(v["idVariable"] for v in _bcra_list() if re.search(r"^\s*CER\b|Coeficiente de Estabilizaci", v.get("descripcion", "")))
            cer = [(d, v) for d, v in _bcra_series(cer_id, days=420) if v]
        except Exception as e:  # noqa: BLE001
            log.warning("CER histórico: %s", e)
    if any(p["clase"] == "dl" for p in papeles.values()):
        try:
            a35 = [(d, v) for d, v in _bcra_series(5, days=400) if v]
        except Exception as e:  # noqa: BLE001
            log.warning("A3500 histórico: %s", e)
    res = fichas.armar(papeles, cer, a35, read_json(HIST / "ar_closes.json", {}) or {}, DATA / "fichas")
    return res, "BYMA (serie histórica 24hs); respaldo: cierres de data912. TIR/TEM: cálculo propio"


def fichas_empresas():
    """Ficha de cada empresa de la pestaña Empresas: historia, negocio, balances, analistas y noticias."""
    import empresas
    items = [it for g in ("megacaps_eeuu", "megacaps_global", "empresas_seleccion") for it in CFG["mercados"].get(g, [])]
    res = empresas.armar(items, DATA / "fichas" / "emp", FINNHUB_KEY)
    return res, "Yahoo Finance (respaldo: Finnhub y Stooq)"


def fichas_acciones():
    """Ficha de cada acción argentina del panel líder: historia en pesos y dólares, Merval, sector y ADR."""
    import acciones_ar
    pg = read_json(HIST / "panel_general.json", {}) or {}
    res = acciones_ar.armar(CFG["argentina"], DATA / "fichas" / "acc", read_json(HIST / "dolares.json", {}) or {},
                            read_json(HIST / "ar_closes.json", {}) or {}, extra=pg.get("tickers", []), nombres=pg.get("nombres", {}))
    return res, "BYMA (serie 24hs), argentinadatos (CCL), Yahoo Finance (Merval y ADR)"


def tamar_terms():
    """Bonos TAMAR: fechas (ficha de BYMA), margen (config) y TAMAR promedio del período, para la TIR en precios."""
    import lecaps
    import tamar
    a = CFG["argentina"]
    margenes = a.get("tamar_margenes", {})
    previos = read_json(HIST / "tamar_terms.json", {}) or {}
    tickers = sorted(set(a.get("tamar", [])) | set(margenes) | {t for t in _tickers_d912() if re.match(tamar.PATRON, t)})
    serie = [(d, v) for d, v in _bcra_series(44, days=900) if v is not None]  # TAMAR bancos privados
    out, faltan = {}, []
    for t in tickers:
        e = dict(previos.get(t) or {})
        if not e.get("emision") or not e.get("vto"):
            try:
                f = lecaps.ficha_byma(t) or {}
                e["emision"], e["vto"] = str(f.get("fechaEmision") or "")[:10] or None, str(f.get("fechaVencimiento") or "")[:10] or None
            except Exception as ex:  # noqa: BLE001
                log.warning("ficha BYMA %s: %s", t, ex)
        if not e.get("emision") or not e.get("vto") or e["vto"] <= today_ar().isoformat():
            if e.get("vto", "9") > today_ar().isoformat():
                faltan.append(f"{t}: sin fechas de emisión/vencimiento")
            continue
        e["margen"] = margenes.get(t)
        if e["margen"] is None:
            faltan.append(f"{t}: falta el margen sobre TAMAR en config/instruments.json (tamar_margenes)")
        em, vt = date.fromisoformat(e["emision"]), date.fromisoformat(e["vto"])
        p = tamar.tamar_promedio(serie, em, vt)
        if p and e["margen"] is not None:
            e.update({"tamar_prom": p[0], "tamar_publicada": p[1], "dias_publicados": p[2], "dias_totales": p[3], "tamar_ultima": p[4],
                      "tem": tamar.tem(p[0], e["margen"]) * 100, "pago_final": tamar.pago_final(em, vt, p[0], e["margen"]),
                      "valor_tecnico": tamar.valor_tecnico(em, today_ar(), p[1], e["margen"])})
        out[t] = e
    write_json(HIST / "tamar_terms.json", out)
    return {"bonos": out, "faltan": faltan, "tamar_ultima": serie[-1] if serie else None}, \
        "BCRA (TAMAR bancos privados), BYMA (fechas), margen de licitación (config)"


def panel_general():
    """Las acciones más operadas del panel general (fuera del panel líder), por monto promedio de 20 ruedas.
    Guarda el monto de cada día en history/montos_ar.json y la selección en history/panel_general.json."""
    import feriados
    import lecaps
    a = CFG["argentina"]
    n_sel = a.get("panel_general_cantidad", 15)
    lider = set(a.get("panel_lider", [])) | set(a.get("acciones", []))
    filas = http_get("https://data912.com/live/arg_stocks", timeout=30)
    if not isinstance(filas, list) or not filas:
        raise RuntimeError("data912 no devolvió acciones")
    simbolos = {r.get("symbol") for r in filas}
    montos = read_json(HIST / "montos_ar.json", {}) or {}
    hoy = today_ar()
    if feriados.es_habil(hoy):
        for r in filas:
            t = r.get("symbol") or ""
            # fuera del panel líder; sin las especies en dólares (YPFDD, ...)
            if t in lider or (t[-1:] in ("D", "C") and t[:-1] in simbolos):
                continue
            m = (num(r.get("v")) or 0) * (num(r.get("c")) or 0)
            montos.setdefault(t, {})[hoy.isoformat()] = m
    corte = (hoy - timedelta(days=45)).isoformat()
    montos = {t: {d: v for d, v in s.items() if d >= corte} for t, s in montos.items()}
    montos = {t: s for t, s in montos.items() if s}
    write_json(HIST / "montos_ar.json", montos)
    prom = {t: sum(sorted(s.items())[-20:][i][1] for i in range(min(20, len(s)))) / min(20, len(s)) for t, s in montos.items()}
    sel = [t for t, _ in sorted(prom.items(), key=lambda x: -x[1])[:n_sel] if prom[t] > 0]
    nombres = read_json(HIST / "nombres_ar.json", {}) or {}
    for t in sel:
        if t not in nombres:
            try:
                f = lecaps.ficha_byma(t) or {}
                n = f.get("emisor") or f.get("razonSocial") or f.get("denominacion") or f.get("descripcion")
                # la ficha a veces trae la descripción del título ("ACCIONES ORDINARIAS ...") y no la empresa
                if n and not re.search(r"ACCION|LETRA|BONO|CEDEAR|OBLIGACI", str(n), re.I):
                    ws = str(n).split()
                    nombres[t] = " ".join(w.capitalize() if (len(w) > 3 or i == 0) else w.lower() for i, w in enumerate(ws))
            except Exception as e:  # noqa: BLE001
                log.warning("nombre BYMA %s: %s", t, e)
    write_json(HIST / "nombres_ar.json", nombres)
    nombres.update(a.get("nombres_panel_general", {}))  # nombres cargados a mano, si hiciera falta
    out = {"tickers": sel, "nombres": {t: nombres.get(t) for t in sel}, "monto_prom": {t: prom[t] for t in sel},
           "ruedas": max((len(montos[t]) for t in sel), default=0)}
    write_json(HIST / "panel_general.json", out)
    return out, "data912 (monto operado), BYMA (nombres)"


def lecaps_auto():
    """Altas automáticas de LECAPs/BONCAPs: busca condiciones de emisión de los tickers nuevos."""
    import lecaps
    tickers = _tickers_d912()
    if not tickers:
        raise RuntimeError("data912 no devolvió tickers")
    manuales = BONOS.get("pago_final_pesos", {})
    terms, resumen = lecaps.actualizar(tickers, manuales)
    resumen["automaticas"] = sorted(t for t, e in terms.items() if e.get("pago_final") and t not in manuales)
    return resumen, "BYMA ficha técnica; respaldo: Secretaría de Finanzas"


if __name__ == "__main__":
    run_blocks(DATA / "daily.json", primero=("feriados", "panel_general"), hilos=12, builders={
        "feriados": feriados_block,   # primero: los cálculos de días hábiles lo usan
        # los más lentos arrancan primero, así no quedan esperando lugar
        "panel_general": panel_general,       # elige las acciones del panel general antes de armar las fichas
        "fichas_empresas": fichas_empresas,   # también da la capitalización de cada empresa
        "fichas_acciones": fichas_acciones,
        "fichas_bonos": fichas_bonos,
        "earnings": earnings,
        "ar_backfill": ar_backfill,
        "calendar_ar": calendar_ar,
        "lecaps_auto": lecaps_auto,
        "cer_auto": cer_auto,
        "tamar_terms": tamar_terms,
        "us_macro": us_macro,
        "fed": fed,
        "treasuries": treasuries,
        "ar_bcra": ar_bcra,
        "ipc": ipc,
        "riesgo_pais": riesgo_pais,
        "emae": emae,
        "rem": rem,
        "bandas": bandas,
        "dolares_hist": dolares_hist,
        "calendar_us": calendar_us,
        "calendar_intl": calendar_intl,
        "us_senales": us_senales,
        "futuros_dolar": futuros_dolar,
        "licitaciones_resultado": licitaciones_resultado,
        "tasas_bc": tasas_bancos_centrales,
        "avisos": avisos,
    })
    log.info("daily.json actualizado %s", now_iso())
