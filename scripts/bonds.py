"""Flujos de fondos, TIR, duration y TEM de bonos argentinos."""
import re
from datetime import date, timedelta

MESES = {"E": 1, "F": 2, "M": 3, "A": 4, "Y": 5, "J": 6, "L": 7, "G": 8, "S": 9, "O": 10, "N": 11, "D": 12}


def _d(s):
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)


def build_flows(fam):
    """Devuelve lista de (fecha, cupón, amortización) por 100 VN original."""
    am = fam["amortizacion"]
    first = _d(am["primera"])
    cuotas = am["cuotas_pct"]
    if not isinstance(cuotas, list):
        cuotas = [cuotas] * am["n"]
    md = [tuple(map(int, x.split("-"))) for x in fam["pago_mes_dia"]]

    # fechas de pago semestrales desde el primer cupón hasta la última amortización
    start = _d(fam["cupones"][0][0])
    dates = []
    y = start.year
    while True:
        for m, d in md:
            dt = date(y, m, d)
            if dt > start:
                dates.append(dt)
        y += 1
        if dates and len([x for x in dates if x >= first]) >= len(cuotas):
            break
    amort_dates = [x for x in dates if x >= first][: len(cuotas)]
    last = amort_dates[-1]
    dates = [x for x in dates if x <= last]

    def rate_at(period_start):
        r = fam["cupones"][0][1]
        for f, t in fam["cupones"]:
            if _d(f) <= period_start:
                r = t
        return r

    residual = 100.0
    flows = []
    prev = start
    for dt in dates:
        cup = residual * rate_at(prev) / 100 / 2  # cupón semestral sobre valor residual (30/360)
        amort = 0.0
        if dt in amort_dates:
            amort = cuotas[amort_dates.index(dt)]
        flows.append((dt, cup, amort))
        residual -= amort
        prev = dt
    return flows


def xirr(cashflows, guess=0.1):
    """cashflows: lista de (fecha, monto). Tasa efectiva anual (base 365)."""
    t0 = cashflows[0][0]
    def f(r):
        return sum(c / (1 + r) ** ((d - t0).days / 365) for d, c in cashflows)
    def df(r):
        return sum(-((d - t0).days / 365) * c / (1 + r) ** ((d - t0).days / 365 + 1) for d, c in cashflows)
    r = guess
    for _ in range(100):
        v, dv = f(r), df(r)
        if dv == 0:
            break
        nr = r - v / dv
        if nr <= -0.99:
            nr = (r - 0.99) / 2
        if abs(nr - r) < 1e-10:
            return nr
        r = nr
    return r if abs(f(r)) < 1e-6 else None


def bond_metrics(flows, price, settle):
    """price: precio limpio+corrido por 100 VN original (precio de pantalla). settle: fecha de liquidación."""
    fut = [(d, c + a) for d, c, a in flows if d > settle]
    if not fut or not price or price <= 0:
        return None
    residual = 100 - sum(a for d, c, a in flows if d <= settle)
    cfs = [(settle, -price)] + fut
    tir = xirr(cfs)
    if tir is None:
        return None
    pv = [(d, v / (1 + tir) ** ((d - settle).days / 365)) for d, v in fut]
    tot = sum(v for _, v in pv)
    mac = sum((d - settle).days / 365 * v for d, v in pv) / tot
    # paridad: precio sobre valor técnico (residual + corrido)
    prev_pay = max([d for d, c, a in flows if d <= settle], default=None)
    next_flow = next((x for x in flows if x[0] > settle), None)
    corrido = 0.0
    if prev_pay and next_flow:
        corrido = next_flow[1] * (settle - prev_pay).days / (next_flow[0] - prev_pay).days
    vt = residual + corrido
    return {
        "tir": tir * 100,
        "dur_mod": mac / (1 + tir),
        "paridad": price / vt * 100 if vt else None,
        "residual": residual,
        "proximo_pago": fut[0][0].isoformat(),
    }


def settle_date(today, days=1):
    d = today
    n = 0
    while n < days:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return d


def maturity_from_ticker(t):
    """S30N6 -> 2026-11-30; T15E7 -> 2027-01-15. Devuelve None si no aplica."""
    m = re.fullmatch(r"[ST](\d{2})([EFMAYJLGSOND])(\d)", t)
    if not m:
        return None
    dd, mm, yy = int(m.group(1)), MESES[m.group(2)], 2020 + int(m.group(3))
    try:
        return date(yy, mm, dd)
    except ValueError:
        return None


def tem(price, payoff, settle, maturity):
    days = (maturity - settle).days
    if days <= 0 or not price or not payoff:
        return None
    g = payoff / price
    tem_ = g ** (30 / days) - 1
    tirea = g ** (365 / days) - 1
    tna = (g - 1) * 365 / days
    return {"tem": tem_ * 100, "tirea": tirea * 100, "tna": tna * 100, "dias": days}
