"""Cálculos con resultados conocidos. Si alguno cambia, algo se rompió (o se subió un archivo equivocado).

Valores de referencia verificados contra fuentes externas:
- Flujos del AL30: igual a bonistas (11/01/27: saldo 64, cupón 0,24, amortización 8).
- Pago final de la T15E7: 161,10 (TEM de emisión 2,05%, emisión 31/01/2025).
- Calendario del INDEC y feriados de octubre de 2026.
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import bonds  # noqa: E402
import feriados  # noqa: E402
import fichas  # noqa: E402
import acciones_ar  # noqa: E402
import indec  # noqa: E402
import lecaps  # noqa: E402

fallas = []


def chequear(nombre, obtenido, esperado, tol=0.0):
    ok = abs(obtenido - esperado) <= tol if isinstance(esperado, (int, float)) and isinstance(obtenido, (int, float)) else obtenido == esperado
    print(("OK   " if ok else "FALLA"), nombre, "→", obtenido, "" if ok else f"(esperado {esperado})")
    if not ok:
        fallas.append(nombre)


BONOS = json.load(open(ROOT / "config" / "bonos.json", encoding="utf-8"))
fam = next(f for f in BONOS["familias"].values() if "AL30" in f["tickers"])
flujos = bonds.tabla_flujos(bonds.build_flows(fam), date(2026, 10, 5))
chequear("AL30 primer pago: fecha", flujos[0][0], "2027-01-11")
chequear("AL30 primer pago: saldo", flujos[0][1], 64.0, 1e-6)
chequear("AL30 primer pago: cupón", flujos[0][2], 0.24, 1e-6)
chequear("AL30 primer pago: amortización", flujos[0][3], 8.0, 1e-6)
chequear("AL30 cantidad de pagos restantes", len(flujos), 8)
m = bonds.bond_metrics(bonds.build_flows(fam), 54.51, date(2026, 10, 5))
chequear("AL30 TIR a 54,51", round(m["tir"], 1), 10.3, 0.15)

chequear("T15E7 pago final", lecaps.pago_final(0.0205, date(2025, 1, 31), date(2027, 1, 15)), 161.10, 0.01)
chequear("S30N6 vencimiento por ticker", bonds.maturity_from_ticker("S30N6"), date(2026, 11, 30))

# serie de BYMA ajustada por pagos (AL30, pago del 09/01/2026, fecha ex 08/01; cierres reales 67,11 y 58,53).
# BYMA reescala los precios anteriores a la fecha ex: 67,11 × (1 − pago / 67,11). Se deshace el ajuste:
papel = {"clase": "usd", "flujos": bonds.build_flows(fam)}
pago = next(c + a for d, c, a in papel["flujos"] if d == date(2026, 1, 9))
real = fichas.desajustar([("2026-01-07", 67.11 - pago, None), ("2026-01-08", 58.53, None)], papel)
chequear("AL30 historia BYMA desajustada (07/01/26)", real[0][1], 67.11, 1e-6)
chequear("AL30 historia BYMA sin cambio desde la fecha ex", real[1][1], 58.53, 1e-9)

# estados que Yahoo marca en pesos pero están en dólares (YPF): patrimonio de US$ 7.700 M tomado como pesos
f = acciones_ar._verificar_moneda({"patrimonio": 7.7e9 / 1623.8, "utilidad_12m": 7.45e8 / 1623.8, "moneda": "ARS"}, 19.47e9, 1623.8)
chequear("Estados de YPF detectados en dólares", f["moneda"], "USD")
chequear("YPF precio/valor libro corregido", round(19.47e9 / f["patrimonio"], 2), 2.53, 0.01)
g = acciones_ar._verificar_moneda({"patrimonio": 9.2e12 / 1623.8, "moneda": "ARS"}, 6.08e9, 1623.8)
chequear("Estados de Galicia siguen en pesos", g["moneda"], "ARS")

s4 = BONOS["familias"].get("BOPREAL_S4")
chequear("BOPREAL Serie 4 cargado", bool(s4), True)
if s4:
    chequear("BOPREAL Serie 4 último pago", bonds.build_flows(s4)[-1][2], 100.0, 1e-6)

chequear("12/10/2026 es feriado", feriados.es_habil(date(2026, 10, 12)), False)
chequear("Liquidación del 09/10/2026 (viernes antes de feriado)", bonds.settle_date(date(2026, 10, 9)), date(2026, 10, 13))

texto = """Octubre
13 MA Índice de precios al consumidor (IPC). Cobertura nacional. Septiembre de 2026
21 MI Estimador mensual de actividad económica (EMAE). Agosto
de 2026"""
ev = indec.parsear(texto, 2026)
chequear("INDEC: IPC del 13/10", [e["evento"] for e in ev if e["fecha"] == "2026-10-13"], ["IPC septiembre (INDEC)"])
chequear("INDEC: EMAE del 21/10", [e["evento"] for e in ev if e["fecha"] == "2026-10-21"], ["EMAE agosto (INDEC)"])

for f in ("instruments.json", "bonos.json", "calendario_ar.json"):
    json.load(open(ROOT / "config" / f, encoding="utf-8"))
print("OK    archivos de config/ son JSON válidos")

if fallas:
    print(f"\n{len(fallas)} chequeo(s) fallaron: {', '.join(fallas)}")
    sys.exit(1)
print("\nTodo bien.")
