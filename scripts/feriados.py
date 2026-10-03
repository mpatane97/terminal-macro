"""Feriados de Argentina, EE.UU. y las demás bolsas que muestra la página.

Argentina: API de argentinadatos (feriados oficiales, incluye los puentes turísticos que se deciden cada año);
si no responde, la librería `holidays`. Bolsas del exterior: calendarios de la librería `holidays`
(NYSE para EE.UU., B3 para San Pablo, y los feriados nacionales del país para el resto).
La corrida diaria guarda el resultado en history/feriados.json para que los otros scripts lo usen sin pedirlo de nuevo.
"""
from datetime import date, timedelta

import holidays

from common import HIST, http_get, log, read_json, today_ar, write_json

ARCHIVO = HIST / "feriados.json"


def _lib(clave, anios):
    if clave == "us":
        cal = holidays.financial_holidays("NYSE", years=anios)
    elif clave == "br":
        cal = holidays.financial_holidays("BVMF", years=anios)
    elif clave == "uk":
        cal = holidays.country_holidays("GB", subdiv="ENG", years=anios)
    else:
        cal = holidays.country_holidays({"ar": "AR", "de": "DE", "jp": "JP", "hk": "HK"}[clave], years=anios)
    return [{"fecha": d.isoformat(), "nombre": n} for d, n in sorted(cal.items())]


def _argentina(anios):
    out = []
    for a in anios:
        try:
            rows = http_get(f"https://api.argentinadatos.com/v1/feriados/{a}", timeout=20)
            out += [{"fecha": r["fecha"], "nombre": r.get("nombre", "")} for r in rows if r.get("fecha")]
        except Exception as e:  # noqa: BLE001
            log.warning("feriados AR %s: %s (uso la librería holidays)", a, e)
            out += _lib("ar", [a])
    return sorted({r["fecha"]: r for r in out}.values(), key=lambda r: r["fecha"])


def actualizar():
    """Feriados del año actual y el siguiente, por mercado. Guarda una copia para los otros scripts."""
    hoy = today_ar()
    anios = [hoy.year, hoy.year + 1]
    out = {"ar": _argentina(anios)}
    for k in ("us", "uk", "de", "jp", "hk", "br"):
        try:
            out[k] = _lib(k, anios)
        except Exception as e:  # noqa: BLE001
            log.warning("feriados %s: %s", k, e)
            out[k] = []
    write_json(ARCHIVO, out)
    return out


_cache = {}


def set_de(mercado="ar"):
    """Conjunto de fechas feriadas (date) de un mercado, leído del archivo guardado o, si no está, de la librería."""
    if mercado not in _cache:
        data = read_json(ARCHIVO, {}) or {}
        filas = data.get(mercado)
        if not filas:
            hoy = date.today()
            try:
                filas = _lib(mercado, [hoy.year - 1, hoy.year, hoy.year + 1])
            except Exception:  # noqa: BLE001
                filas = []
        _cache[mercado] = {date.fromisoformat(r["fecha"]) for r in filas}
    return _cache[mercado]


def es_habil(d, mercado="ar"):
    return d.weekday() < 5 and d not in set_de(mercado)


def sumar_habiles(d, n, mercado="ar"):
    """Avanza (n > 0) o retrocede (n < 0) n días hábiles."""
    paso = 1 if n > 0 else -1
    while n:
        d += timedelta(days=paso)
        if es_habil(d, mercado):
            n -= paso
    return d
