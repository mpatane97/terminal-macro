"""Alta automática de LECAPs y BONCAPs nuevas.

Cuando el Tesoro emite una letra nueva, su ticker aparece en data912 pero falta el pago al vencimiento,
sin el cual no hay TEM. Este módulo lo calcula solo:

1. Descubre tickers de tasa fija (S30N6, T15E7…) que cotizan y no tienen pago final cargado.
2. Busca su ficha técnica en BYMA (fecha de emisión, vencimiento y TEM de emisión).
3. Si la ficha no trae la TEM (pasa con las recién emitidas), la busca en el resultado de la licitación
   publicado por la Secretaría de Finanzas, y sólo la acepta si cierra contra la TIREA de la misma fila.
4. Pago final = 100 × (1 + TEM)^(meses enteros + días remanentes / 30), convención del Tesoro.

Guarda todo en docs/data/history/lecaps_terms.json: las condiciones de una letra no cambian nunca,
así que cada ficha se pide una sola vez.
"""
import re
import time
from datetime import date, timedelta

import requests

import bonds
from common import HIST, UA, http_get, log, read_json, today_ar, write_json

BYMA = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/bnown/fichatecnica/especies/general"
FINANZAS = "https://www.argentina.gob.ar"
ARCHIVO = HIST / "lecaps_terms.json"
MAX_FICHAS = 12          # por corrida, para no castigar a BYMA
PAUSA = 1.0              # segundos entre fichas
MESES = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
         "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12}


# ---------- cálculo ----------

def _sumar_meses(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    ultimo = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, ultimo))


def exponente(emision, vto):
    """Meses calendario enteros entre emisión y vencimiento + remanente en días / 30."""
    meses = (vto.year - emision.year) * 12 + (vto.month - emision.month)
    if vto.day < emision.day:
        meses -= 1
    return meses + (vto - _sumar_meses(emision, meses)).days / 30


def pago_final(tem, emision, vto):
    return round(100 * (1 + tem) ** exponente(emision, vto), 4)


# ---------- BYMA ----------

def ficha_byma(symbol):
    verify = True
    for intento in range(3):
        try:
            r = requests.post(BYMA, json={"symbol": symbol, "Content-Type": "application/json"},
                              headers={**UA, "Content-Type": "application/json"}, timeout=15, verify=verify)
            r.raise_for_status()
            data = (r.json() or {}).get("data") or []
            return data[0] if data else None
        except requests.exceptions.SSLError:
            verify = False
        except Exception as e:  # noqa: BLE001
            if intento == 2:
                raise
            log.warning("ficha BYMA %s: %s", symbol, e)
        time.sleep(2 * (intento + 1))
    return None


def clasificar(f):
    nombre = (f.get("denominacion") or "").upper()
    if (f.get("moneda") or "").lower() not in ("pesos", "ars", "$"):
        return f"moneda {f.get('moneda')}"
    for clave, motivo in (("TAMAR", "tasa TAMAR"), ("CER", "ajusta por CER"), ("DOLAR", "dólar linked"), ("DÓLAR", "dólar linked")):
        if clave in nombre:
            return motivo
    if "CAPITALIZABLE" not in nombre:
        return "no es capitalizable"
    return None


def tem_de_ficha(f):
    """Junta todos los porcentajes del texto de intereses y exige que quede uno solo en rango mensual."""
    vals = {float(x.replace(",", ".")) for x in re.findall(r"(\d+(?:[.,]\d+)?)\s*%", f.get("interes") or "")}
    vals = {v for v in vals if 0.1 <= v <= 15}
    return vals.pop() / 100 if len(vals) == 1 else None


def _fecha(s):
    return date.fromisoformat(str(s)[:10]) if s else None


# ---------- Secretaría de Finanzas (respaldo) ----------

def _texto(html):
    return re.sub(r"\s+", " ", re.sub(r"&nbsp;", " ", re.sub(r"<[^>]+>", " ", html))).strip()


def _filas(html):
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    for tabla in re.findall(r"<table.*?</table>", html, flags=re.S | re.I):
        for fila in re.findall(r"<tr.*?</tr>", tabla, flags=re.S | re.I):
            celdas = [_texto(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", fila, flags=re.S | re.I)]
            if celdas:
                yield celdas


def _vto_de_texto(t):
    m = re.search(r"VENCIMIENTO\s+(?:EL\s+)?(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚ]+)\s+DE\s+(\d{4})", t.upper())
    if not m or m.group(2) not in MESES:
        return None
    return date(int(m.group(3)), MESES[m.group(2)], int(m.group(1)))


def _pct(c):
    m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*%", c)
    return float(m.group(1).replace(",", ".")) / 100 if m else None


_cache_html = {}


def _html(url):
    if url not in _cache_html:
        _cache_html[url] = http_get(url, as_json=False, timeout=20).text
    return _cache_html[url]


def tem_de_licitacion(vto):
    """TEM adjudicada a la letra capitalizable que vence en `vto`, leída del resultado de licitación.
    Sólo se acepta si TEM y TIREA de la misma fila cierran: (1+TEM)^12 − 1 ≈ TIREA."""
    slugs = []
    for pag in range(3):
        url = f"{FINANZAS}/economia/finanzas/noticias" + (f"?page={pag}" if pag else "")
        try:
            html = _html(url)
        except Exception as e:  # noqa: BLE001
            log.warning("finanzas listado: %s", e)
            break
        for s in re.findall(r'href="(/noticias/[^"?#]+)"', html):
            if "resultado" in s and "licitacion" in s and "conversion" not in s and s not in slugs:
                slugs.append(s)
        if len(slugs) >= 6:
            break
    for s in slugs[:6]:
        try:
            html = _html(FINANZAS + s)
        except Exception as e:  # noqa: BLE001
            log.warning("finanzas %s: %s", s, e)
            continue
        for celdas in _filas(html):
            if len(celdas) < 3 or "CAPITALIZABLE" not in celdas[0].upper() or _vto_de_texto(celdas[0]) != vto:
                continue
            for a, b in zip(celdas[1:], celdas[2:]):
                tem, tirea = _pct(a), _pct(b)
                if tem and tirea and 0.001 <= tem <= 0.15 and abs((1 + tem) ** 12 - 1 - tirea) <= 0.001:
                    return tem, FINANZAS + s
    return None, None


# ---------- orquestación ----------

def actualizar(tickers, manuales):
    """`tickers`: los que cotizan hoy. `manuales`: pagos finales cargados a mano en config/bonos.json.
    Devuelve el archivo de condiciones actualizado y un resumen de la corrida."""
    terms = read_json(ARCHIVO, {}) or {}
    hoy = today_ar()
    pendientes = []
    for t in sorted(set(tickers)):
        vto = bonds.maturity_from_ticker(t)
        if not vto or vto <= hoy:
            continue
        e = terms.get(t) or {}
        if e.get("pago_final") or e.get("descartado"):
            continue
        # las cargadas a mano se consultan igual una vez, como control del cálculo automático
        pendientes.append(t)
    # primero las que no tienen pago final por ningún lado
    pendientes.sort(key=lambda t: t in manuales)

    nuevas, controles, sin_resolver = [], [], []
    for t in pendientes[:MAX_FICHAS]:
        vto = bonds.maturity_from_ticker(t)
        try:
            f = ficha_byma(t)
        except Exception as e:  # noqa: BLE001
            log.warning("ficha %s: %s", t, e)
            f = None
        time.sleep(PAUSA)
        if not f:
            sin_resolver.append(t)
            terms[t] = {**terms.get(t, {}), "intentos": terms.get(t, {}).get("intentos", 0) + 1, "ultimo_intento": hoy.isoformat()}
            continue
        motivo = clasificar(f)
        if motivo:
            terms[t] = {"descartado": motivo, "denominacion": f.get("denominacion")}
            continue
        emision = _fecha(f.get("fechaEmision"))
        vto_f = _fecha(f.get("fechaVencimiento")) or vto
        tem, fuente = tem_de_ficha(f), "BYMA ficha técnica"
        # BYMA a veces redondea la TEM a un decimal (2,4% en vez de 2,42%): eso solo mueve el pago final
        # ~0,4%. Si viene con menos de dos decimales se prefiere la de la licitación, que se verifica sola.
        if tem is None or abs(tem * 1000 - round(tem * 1000)) < 1e-9:
            tem_l, url = tem_de_licitacion(vto_f)
            if tem_l:
                tem, fuente = tem_l, f"Finanzas, resultado de licitación ({url})"
        if tem is None or not emision:
            sin_resolver.append(t)
            terms[t] = {"emision": emision.isoformat() if emision else None, "vto": vto_f.isoformat(),
                        "denominacion": f.get("denominacion"), "intentos": terms.get(t, {}).get("intentos", 0) + 1,
                        "ultimo_intento": hoy.isoformat()}
            continue
        pf = pago_final(tem, emision, vto_f)
        terms[t] = {"pago_final": pf, "tem_emision": round(tem * 100, 4), "emision": emision.isoformat(),
                    "vto": vto_f.isoformat(), "fuente": fuente, "alta": hoy.isoformat()}
        if t in manuales:
            controles.append({"ticker": t, "automatico": pf, "manual": manuales[t], "dif_pct": round((pf / manuales[t] - 1) * 100, 3)})
        else:
            nuevas.append(t)
    # limpiar letras vencidas
    terms = {t: e for t, e in terms.items() if (bonds.maturity_from_ticker(t) or hoy) > hoy - timedelta(days=30)}
    write_json(ARCHIVO, terms)
    return terms, {"nuevas": nuevas, "controles": controles, "sin_resolver": sin_resolver,
                   "pendientes_proxima": max(0, len(pendientes) - MAX_FICHAS)}


# ---------- Bonos y letras CER cero cupón ----------

ARCHIVO_CER = HIST / "cer_terms.json"
PATRON_CER = re.compile(r"^(TZX[A-Z0-9]{2,3}|X\d{2}[EFMAYJLGSOND]\d|X[A-Z]{2}\d{2})$")


def clasificar_cer(f):
    nombre = (f.get("denominacion") or "").upper()
    if "CER" not in nombre:
        return "no ajusta por CER"
    if any(k in nombre for k in ("TAMAR", "DUAL", "DOLAR", "DÓLAR")):
        return "dual o ajusta por otra referencia"
    if not ("CERO CUP" in nombre or "LETRA" in nombre):
        return "paga cupones (carga manual)"
    return None


def actualizar_cer(tickers, manuales, cer_en, vtos_manuales=None):
    """`cer_en(fecha)`: valor del CER publicado a esa fecha. El capital se ajusta por el CER de 10 días
    hábiles antes de la emisión (CER inicial), igual que en las condiciones de emisión del Tesoro."""
    import feriados
    terms = read_json(ARCHIVO_CER, {}) or {}
    hoy = today_ar()
    # un mismo bono cotiza también en dólares o con otro plazo de liquidación (p. ej. TZX27 y TZX7D): se queda uno solo
    usados = {v: t for t, v in (vtos_manuales or {}).items()}
    for t in sorted(terms, key=lambda x: (x[-1] in "DC", x)):
        e = terms[t]
        if e.get("cer_inicial") and e.get("vto"):
            if e["vto"] in usados and usados[e["vto"]] != t:
                terms[t] = {"descartado": f"otra especie de {usados[e['vto']]}", "denominacion": e.get("denominacion")}
            else:
                usados[e["vto"]] = t
    pendientes = [t for t in sorted(set(tickers)) if PATRON_CER.match(t)
                  and not (terms.get(t, {}).get("cer_inicial") or terms.get(t, {}).get("descartado"))]
    pendientes.sort(key=lambda t: (t in manuales, t[-1] in "DC"))
    nuevas, controles, sin_resolver = [], [], []
    for t in pendientes[:MAX_FICHAS]:
        try:
            f = ficha_byma(t)
        except Exception as e:  # noqa: BLE001
            log.warning("ficha %s: %s", t, e)
            f = None
        time.sleep(PAUSA)
        if not f:
            sin_resolver.append(t)
            continue
        motivo = clasificar_cer(f) or (None if (f.get("moneda") or "").lower() in ("pesos", "ars", "$") else f"moneda {f.get('moneda')}")
        if motivo:
            terms[t] = {"descartado": motivo, "denominacion": f.get("denominacion")}
            continue
        emision, vto = _fecha(f.get("fechaEmision")), _fecha(f.get("fechaVencimiento"))
        if not emision or not vto or vto <= hoy:
            sin_resolver.append(t)
            continue
        if vto.isoformat() in usados and usados[vto.isoformat()] != t:
            terms[t] = {"descartado": f"otra especie de {usados[vto.isoformat()]}", "denominacion": f.get("denominacion")}
            continue
        ref = feriados.sumar_habiles(emision, -10)
        try:
            ci = cer_en(ref.isoformat())
        except Exception as e:  # noqa: BLE001
            log.warning("CER %s: %s", ref, e)
            ci = None
        if not ci:
            sin_resolver.append(t)
            continue
        usados[vto.isoformat()] = t
        terms[t] = {"cer_inicial": ci, "emision": emision.isoformat(), "vto": vto.isoformat(),
                    "fecha_cer": ref.isoformat(), "denominacion": f.get("denominacion"), "alta": hoy.isoformat()}
        if t in manuales:
            controles.append({"ticker": t, "automatico": round(ci, 4), "manual": round(manuales[t], 4),
                              "dif_pct": round((ci / manuales[t] - 1) * 100, 3)})
        else:
            nuevas.append(t)
    terms = {t: e for t, e in terms.items() if not e.get("vto") or e["vto"] > (hoy - timedelta(days=30)).isoformat()}
    write_json(ARCHIVO_CER, terms)
    return terms, {"nuevas": nuevas, "controles": controles, "sin_resolver": sin_resolver,
                   "pendientes_proxima": max(0, len(pendientes) - MAX_FICHAS)}
