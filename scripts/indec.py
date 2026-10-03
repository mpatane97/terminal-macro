"""Calendario de difusión del INDEC, leído de los PDF semestrales que publica en una dirección fija:
https://www.indec.gob.ar/ftp/cuadros/publicaciones/calendario_{1|2}sem{AÑO}.pdf

Cada mes empieza con su nombre ("Octubre") y cada publicación es una línea del tipo
"13 MA Índice de precios al consumidor (IPC). Cobertura nacional. Septiembre de 2026".
Se toman sólo las publicaciones que muestra la terminal."""
import io
import re
from datetime import date

from common import http_get, log, today_ar

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
         "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
DIAS = r"(?:LU|MA|MI|JU|VI|SA|DO)"
# (patrón en el título, nombre corto que se muestra)
BUSCADOS = [
    (r"precios al consumidor", "IPC"),
    (r"estimador mensual de actividad", "EMAE"),
    (r"informe de avance del nivel de actividad", "PBI trimestral"),
    (r"mercado de trabajo.*tasas e indicadores", "Desempleo"),
    (r"intercambio comercial argentino", "Balanza comercial"),
    (r"incidencia de la pobreza", "Pobreza"),
    (r"índice de salarios", "Salarios"),
]


def _url(anio, sem):
    return f"https://www.indec.gob.ar/ftp/cuadros/publicaciones/calendario_{sem}sem{anio}.pdf"


def _texto_pdf(contenido):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def parsear(texto, anio):
    eventos, mes, actual = [], None, None

    def cerrar():
        if actual:
            for patron, corto in BUSCADOS:
                if re.search(patron, actual["texto"], re.I):
                    periodo = re.search(r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)"
                                        r"(?: de)? (\d{4})|(primer|segundo|tercer|cuarto) (?:trimestre|semestre)[^.]*?(\d{4})", actual["texto"], re.I)
                    det = (periodo.group(1).lower() if periodo and periodo.group(1) else
                           f"{periodo.group(3).lower()} {('trimestre' if 'trimestre' in actual['texto'].lower() else 'semestre')} {periodo.group(4)}" if periodo else "")
                    eventos.append({"fecha": actual["fecha"], "hora": "16:00", "evento": f"{corto} {det} (INDEC)".replace("  ", " ")})
                    break

    for linea in texto.splitlines():
        l = linea.strip()
        if not l:
            continue
        m_mes = re.fullmatch(r"([A-Za-zÁÉÍÓÚáéíóú]+)(?:\s+\d{4})?", l)
        if m_mes and m_mes.group(1).lower() in MESES:
            cerrar(); actual = None
            mes = MESES[m_mes.group(1).lower()]
            continue
        m = re.match(rf"^(\d{{1,2}})\s+{DIAS}\s+(.*)$", l)
        if m and mes:
            cerrar()
            try:
                actual = {"fecha": date(anio, mes, int(m.group(1))).isoformat(), "texto": m.group(2)}
            except ValueError:
                actual = None
            continue
        if actual:
            # línea de continuación: si el título anterior ya terminó (tiene su período, "… de 2026"),
            # es otra publicación del mismo día; si no, completa el título anterior
            if re.search(r"\d{4}\.?\s*$", actual["texto"]) and re.match(r"^[A-ZÁÉÍÓÚ]", l):
                cerrar()
                actual = {"fecha": actual["fecha"], "texto": l}
            else:
                actual["texto"] += " " + l
    cerrar()
    return eventos


def calendario():
    """Eventos desde hoy, del semestre actual y el siguiente (si ya está publicado)."""
    hoy = today_ar()
    sem = 1 if hoy.month <= 6 else 2
    pedidos = [(hoy.year, sem), (hoy.year + (sem == 2), 2 if sem == 1 else 1)]
    eventos, leidos = [], []
    for anio, s in pedidos:
        try:
            r = http_get(_url(anio, s), as_json=False, timeout=30)
            ev = parsear(_texto_pdf(r.content), anio)
            eventos += ev
            leidos.append(f"{s}º semestre {anio} ({len(ev)} eventos)")
        except Exception as e:  # noqa: BLE001
            log.warning("calendario INDEC %s-%s: %s", anio, s, e)
    vistos, out = set(), []
    for e in sorted(eventos, key=lambda x: x["fecha"]):
        if e["fecha"] >= hoy.isoformat() and (e["fecha"], e["evento"]) not in vistos:
            vistos.add((e["fecha"], e["evento"]))
            out.append(e)
    return out, leidos
