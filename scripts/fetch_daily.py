"""Corrida diaria (20 h): macro de EE.UU. y Argentina, Fed, curva de Treasuries, BCRA, riesgo país,
bandas, calendario y earnings. Escribe docs/data/daily.json."""
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
    lo, hi = fred("DFEDTARL")[-1], fred("DFEDTARU")[-1]
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
    acciones = list(dict.fromkeys(a["acciones"] + a.get("panel_lider", [])))
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
    for g in ("megacaps_eeuu", "megacaps_global", "empresas_seleccion"):
        for it in CFG["mercados"].get(g, []):
            try:
                fi = yf.Ticker(it["yahoo"]).fast_info
                cap = getattr(fi, "market_cap", None)
                cur = (getattr(fi, "currency", None) or "USD").upper()
                if cap:
                    out[it["id"]] = cap * tasas.get(cur, 1.0) / 1e9 if cur in tasas or cur == "USD" else None
            except Exception as e:  # noqa: BLE001
                log.warning("market cap %s: %s", it["id"], e)
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
    fuente = "INDEC, calendario de difusión (PDF)" if auto else "INDEC (carga manual; el PDF no respondió)"
    return eventos, fuente + (f" · {'; '.join(leidos)}" if leidos else "")


def earnings():
    if not FINNHUB_KEY:
        raise RuntimeError("falta FINNHUB_API_KEY")
    d = today_ar()
    mega = [it["id"] for g in ("megacaps_eeuu", "megacaps_global", "empresas_seleccion") for it in CFG["mercados"].get(g, [])]
    universe = set(CFG["earnings_top20"]) | set(CFG.get("watchlist", [])) | set(mega)
    # Finnhub recorta los pedidos por rango: se consulta empresa por empresa (límite 60/min)
    filas = []
    for sym in sorted(universe):
        try:
            filas += http_get("https://finnhub.io/api/v1/calendar/earnings",
                              params={"symbol": sym, "from": d.isoformat(), "to": (d + timedelta(days=90)).isoformat(),
                                      "token": FINNHUB_KEY}).get("earningsCalendar", [])
        except Exception as e:  # noqa: BLE001
            log.warning("earnings %s: %s", sym, e)
        time.sleep(1.1)
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
    tickers = []
    for path in ("/live/arg_bonds", "/live/arg_notes"):
        try:
            tickers += [r.get("symbol") for r in http_get(f"https://data912.com{path}", timeout=25) if r.get("symbol")]
        except Exception as e:  # noqa: BLE001
            log.warning("data912 %s: %s", path, e)
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
    terms, resumen = lecaps.actualizar_cer(tickers, manuales, cer_en)
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


def lecaps_auto():
    """Altas automáticas de LECAPs/BONCAPs: busca condiciones de emisión de los tickers nuevos."""
    import lecaps
    tickers = []
    for path in ("/live/arg_notes", "/live/arg_bonds"):
        try:
            tickers += [r.get("symbol") for r in http_get(f"https://data912.com{path}", timeout=25) if r.get("symbol")]
        except Exception as e:  # noqa: BLE001
            log.warning("data912 %s: %s", path, e)
    if not tickers:
        raise RuntimeError("data912 no devolvió tickers")
    manuales = BONOS.get("pago_final_pesos", {})
    terms, resumen = lecaps.actualizar(tickers, manuales)
    resumen["automaticas"] = sorted(t for t, e in terms.items() if e.get("pago_final") and t not in manuales)
    return resumen, "BYMA ficha técnica; respaldo: Secretaría de Finanzas"


if __name__ == "__main__":
    run_blocks(DATA / "daily.json", {
        "feriados": feriados_block,   # primero: los cálculos de días hábiles lo usan
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
        "ar_backfill": ar_backfill,
        "calendar_us": calendar_us,
        "calendar_ar": calendar_ar,
        "calendar_intl": calendar_intl,
        "us_senales": us_senales,
        "megacaps_info": megacaps_info,
        "earnings": earnings,
        "lecaps_auto": lecaps_auto,
        "cer_auto": cer_auto,
        "avisos": avisos,
    })
    log.info("daily.json actualizado %s", now_iso())
