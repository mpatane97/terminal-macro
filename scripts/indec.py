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


def _columnas(page):
    """El PDF puede tener dos meses lado a lado. Se detectan las columnas por la posición horizontal
    de los números de día seguidos del día de la semana ("13 MA") y se lee cada columna por separado."""
    palabras = page.extract_words(keep_blank_chars=False)
    xs = []
    for a, b in zip(palabras, palabras[1:]):
        if re.fullmatch(r"\d{1,2}", a["text"]) and re.fullmatch(DIAS, b["text"]) and abs(a["top"] - b["top"]) < 3:
            xs.append(a["x0"])
    if not xs:
        return [page]
    xs.sort()
    inicios = [xs[0]]
    for x in xs[1:]:
        if x - inicios[-1] > page.width * 0.25:
            inicios.append(x)
    if len(inicios) == 1:
        return [page]
    bordes = [max(0, x - 4) for x in inicios] + [page.width]
    return [page.crop((bordes[i], 0, bordes[i + 1], page.height)) for i in range(len(inicios))]


def _texto_pdf(contenido):
    import pdfplumber
    partes = []
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for page in pdf.pages:
            for col in _columnas(page):
                partes.append(col.extract_text() or "")
    return "\n".join(partes)


# desfase normal entre el mes de publicación y el período que informa (para descartar lecturas raras)
DESFASE = {"IPC": (1,), "EMAE": (2,), "Balanza comercial": (1,), "Salarios": (2,)}
MES_NUM = {**MESES}


def _plausible(e):
    corto = e["evento"].split(" (")[0]
    if corto.startswith(("PBI trimestral", "Desempleo", "Pobreza")):
        return "trimestre" in corto or "semestre" in corto
    for k, des in DESFASE.items():
        if corto.startswith(k + " "):
            mes_txt = corto[len(k) + 1:].split(" ")[0].lower()
            if mes_txt in MES_NUM:
                pub = int(e["fecha"][5:7])
                return ((pub - MES_NUM[mes_txt]) % 12) in des
    return True


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
            texto = _texto_pdf(r.content)
            try:  # copia del texto leído, para poder revisar el formato si algo no cierra
                from common import HIST
                (HIST / f"indec_{anio}_{s}.txt").write_text(texto, encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
            ev = [e for e in parsear(texto, anio) if _plausible(e)]
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
