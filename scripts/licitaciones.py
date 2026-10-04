"""Resultados de las licitaciones del Tesoro, leídos de las noticias de la Secretaría de Finanzas.

Cada resultado trae un resumen ("se recibieron ofertas por un total de valor efectivo de $ X billones ...
se adjudicó un total de valor efectivo $ Y billones") y una tabla por tipo de instrumento con lo adjudicado,
el precio y la tasa de corte. Las columnas se reconocen por su encabezado, no por su posición.
"""
import re
from datetime import date

from common import HIST, log
from lecaps import FINANZAS, MESES, _filas, _html, _texto, _vto_de_texto

TICKER = re.compile(r"\b([A-Z]{1,2}\d{2}[EFMAYJLGSOND]\d|T[A-Z]{1,3}\d{2}|[A-Z]{2,5}\d{2}[A-Z]?)\b")


def _num(txt):
    """'$ 6.085.000' -> 6085000; '1.217,00' -> 1217.0; '29,75%' -> 29.75; 'USD 279' -> 279."""
    m = re.search(r"-?\d[\d.]*(?:,\d+)?", txt or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _fecha(texto):
    m = re.search(r"(\d{1,2}) de ([a-záéíóú]+) de (\d{4})", texto, re.I)
    if m and m.group(2).upper() in MESES:
        try:
            return date(int(m.group(3)), MESES[m.group(2).upper()], int(m.group(1))).isoformat()
        except ValueError:
            return None
    return None


def _billones(patron, texto):
    m = re.search(patron + r"[^\d$]{0,40}\$?\s*([\d.,]+)\s*(billones|millones)?", texto, re.I)
    if not m:
        return None
    v = _num(m.group(1))
    if v is None:
        return None
    return v * (1e6 if (m.group(2) or "").lower() == "millones" else 1e12) if m.group(2) else v


def parsear(html):
    texto = _texto(html)
    res = {
        "fecha": _fecha(texto),
        "ofertado": _billones(r"ofertas por un total de valor efectivo de", texto),
        "adjudicado": _billones(r"adjudic[oó] un total de valor efectivo(?: de)?", texto),
        "rollover": None,
        "instrumentos": [],
    }
    m = re.search(r"rollover[^\d]{0,40}([\d.,]+)\s*%", texto, re.I)
    if m:
        res["rollover"] = _num(m.group(1))
    encabezado = None
    for celdas in _filas(html):
        bajo = [c.lower() for c in celdas]
        if any("adjudicado" in c for c in bajo) and len(celdas) >= 3 and not any(_num(c) for c in celdas[1:2]):
            encabezado = bajo  # nueva tabla: guardar qué es cada columna
            continue
        if not encabezado or len(celdas) < 3 or not celdas[0].strip():
            continue
        if celdas[0].lower().startswith(("total", "cantidad", "ofertas")):
            continue

        def col(*claves):
            for i, h in enumerate(encabezado):
                if all(k in h for k in claves) and i < len(celdas):
                    return celdas[i]
            return None
        nombre = celdas[0]
        t = TICKER.search(nombre.upper())
        vto = _vto_de_texto(nombre)
        etiqueta = t.group(1) if t else (f"Nueva, vto {vto.strftime('%d/%m/%y')}" if vto else nombre[:40])
        fila = {
            "instrumento": etiqueta,
            "nueva": not t or "reapert" not in nombre.lower(),
            "ve_adjudicado": _num(col("adjudicado", "ve") or col("adjudicado", "efectivo")),
            "vn_adjudicado": _num(col("adjudicado", "vn") or col("adjudicado", "nominal")),
            "precio": None if "%" in (col("precio") or "") else _num(col("precio")),
            "tirea": _num(col("tirea")),
            # en las emisiones nuevas la columna "precio" trae la TEM de corte (un porcentaje)
            "tem": _num(col("tem")) if col("tem") else (_num(col("precio")) if "%" in (col("precio") or "") else None),
            "margen": _num(col("margen")),
            "usd": "usd" in " ".join(celdas).lower(),
        }
        if any(fila[k] is not None for k in ("ve_adjudicado", "vn_adjudicado", "tirea")):
            res["instrumentos"].append(fila)
    return res


def resultados(n=4):
    """Los últimos `n` resultados de licitación (por efectivo; se excluyen conversiones y canjes)."""
    slugs = []
    for pag in range(3):
        url = f"{FINANZAS}/economia/finanzas/noticias" + (f"?page={pag}" if pag else "")
        try:
            html = _html(url)
        except Exception as e:  # noqa: BLE001
            log.warning("finanzas listado: %s", e)
            break
        for s in re.findall(r'href="(/noticias/[^"?#]+)"', html):
            if "resultado" in s and "licitacion" in s and "conversion" not in s and "canje" not in s and s not in slugs:
                slugs.append(s)
        if len(slugs) >= n:
            break
    out = []
    for i, s in enumerate(slugs[:n]):
        try:
            html = _html(FINANZAS + s)
            if i == 0:
                (HIST / "licitacion_ultima.html").write_text(html, encoding="utf-8")  # copia para revisar el formato
            r = parsear(html)
            r["url"] = FINANZAS + s
            out.append(r)
        except Exception as e:  # noqa: BLE001
            log.warning("resultado %s: %s", s, e)
    out.sort(key=lambda r: r.get("fecha") or "", reverse=True)
    return out
