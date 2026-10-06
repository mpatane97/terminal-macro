"""Bonos TAMAR del Tesoro (TMF27, TML27, ...): pago al vencimiento proyectado y TIR.

Condiciones (Secretaría de Finanzas, llamado a licitación):
- Capitalizan mensualmente a la "TAMAR TEM" hasta el vencimiento, base 30/360:
      VPV = VNO × (1 + TAMAR TEM) ^ (DÍAS / 360 × 12)
      TAMAR TEM = [(1 + (TAMAR + MARGEN) × 32/365) ^ (365/32)] ^ (1/12) − 1
- TAMAR: promedio simple de la TAMAR de bancos privados publicada por el BCRA desde 10 días hábiles antes
  de la emisión hasta 10 días hábiles antes del vencimiento.
- MARGEN: el de la licitación de origen (config/instruments.json → argentina.tamar_margenes).
Para la parte que todavía no ocurrió se supone que la TAMAR se queda en el último valor publicado
(misma convención que usan las calculadoras de mercado). Fechas de emisión y vencimiento: ficha técnica de BYMA.
"""
from datetime import date

import feriados

PATRON = r"^TM[EFMAYJLGSOND]\d{2}$"


def dias_30_360(d1, d2):
    a1, a2 = min(d1.day, 30), d2.day
    if a2 == 31 and a1 == 30:
        a2 = 30
    return (d2.year - d1.year) * 360 + (d2.month - d1.month) * 30 + (a2 - a1)


def tem(tamar_pct, margen_pct):
    """TAMAR TEM (fracción) a partir de la TAMAR promedio y el margen, ambos en % anual."""
    r = (tamar_pct + margen_pct) / 100
    return ((1 + r * 32 / 365) ** (365 / 32)) ** (1 / 12) - 1


def tamar_promedio(serie, emision, vto):
    """Promedio de la TAMAR del período del bono: lo ya publicado y, para los días hábiles que faltan, el último
    valor publicado. serie: [(fecha ISO, valor)] ordenada.
    Devuelve (promedio total, promedio publicado, días publicados, días totales, último valor) o None."""
    serie = [(d, v) for d, v in serie if v is not None]
    if not serie:
        return None
    ini, fin = feriados.sumar_habiles(emision, -10), feriados.sumar_habiles(vto, -10)
    ult_fecha, ultimo = date.fromisoformat(serie[-1][0]), serie[-1][1]
    reales = [v for d, v in serie if ini.isoformat() <= d <= fin.isoformat()]
    faltan, d = 0, max(ult_fecha, ini - __import__("datetime").timedelta(days=1))
    while True:
        d = feriados.sumar_habiles(d, 1)
        if d > fin:
            break
        faltan += 1
    n = len(reales) + faltan
    if not n:
        return None
    prom_pub = sum(reales) / len(reales) if reales else ultimo
    return (sum(reales) + faltan * ultimo) / n, prom_pub, len(reales), n, ultimo


def pago_final(emision, vto, tamar_prom, margen):
    """Valor al vencimiento por 100 VNO."""
    return 100 * (1 + tem(tamar_prom, margen)) ** (dias_30_360(emision, vto) / 360 * 12)


def valor_tecnico(emision, hoy, tamar_hasta_hoy, margen):
    """Capital más intereses capitalizados hasta hoy (con la TAMAR promedio publicada hasta hoy)."""
    return 100 * (1 + tem(tamar_hasta_hoy, margen)) ** (dias_30_360(emision, hoy) / 360 * 12)
