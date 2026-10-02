"""Utilidades compartidas: HTTP con reintentos, escritura de JSON y manejo del último dato válido."""
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
HIST = DATA / "history"
CONFIG = ROOT / "config"
AR_TZ = timezone(timedelta(hours=-3))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("terminal")

UA = {"User-Agent": "Mozilla/5.0 (terminal-personal; uso no comercial)"}


def now_iso():
    return datetime.now(AR_TZ).isoformat(timespec="seconds")


def today_ar():
    return datetime.now(AR_TZ).date()


def load_config(name):
    with open(CONFIG / name, encoding="utf-8") as f:
        return json.load(f)


def http_get(url, params=None, headers=None, timeout=20, retries=2, as_json=True, verify=True):
    """GET con reintentos. Si falla el certificado (pasa con api.bcra.gob.ar), reintenta sin verificar:
    son datos públicos de solo lectura."""
    h = dict(UA)
    if headers:
        h.update(headers)
    last = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout, verify=verify)
            r.raise_for_status()
            return r.json() if as_json else r
        except requests.exceptions.SSLError as e:
            last = e
            if verify:
                log.warning("SSL inválido en %s, reintento sin verificar", url)
                verify = False
                continue
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), default=str)
    os.replace(tmp, path)


class Block:
    """Un bloque de datos del archivo de salida. Si la fuente falla, conserva el último valor válido
    y lo marca como viejo (stale) para que la página lo muestre así."""

    def __init__(self, name, previous):
        self.name = name
        self.prev = (previous or {}).get(name)

    def ok(self, data, source):
        return {"data": data, "source": source, "updated": now_iso(), "stale": False, "error": None}

    def fail(self, err):
        log.error("bloque %s: %s", self.name, err)
        if self.prev and self.prev.get("data") is not None:
            out = dict(self.prev)
            out["stale"] = True
            out["error"] = str(err)[:200]
            return out
        return {"data": None, "source": None, "updated": None, "stale": True, "error": str(err)[:200]}


def run_blocks(path, builders):
    """Ejecuta cada constructor de bloque de forma aislada y escribe el archivo resultante."""
    previous = read_json(path, {}) or {}
    out = {"generated": now_iso()}
    for name, fn in builders.items():
        b = Block(name, previous)
        try:
            data, source = fn()
            out[name] = b.ok(data, source)
        except Exception as e:  # noqa: BLE001
            out[name] = b.fail(e)
    write_json(path, out)
    return out


def num(x):
    try:
        if x is None or x == "" or x == ".":
            return None
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


def pct(a, b):
    if a is None or b in (None, 0):
        return None
    return (a / b - 1) * 100


def changes_from_series(series, last=None):
    """series: lista ordenada de (fecha 'YYYY-MM-DD', valor). Devuelve último y variaciones
    diaria, semanal, mensual e interanual en %."""
    s = [(d, v) for d, v in series if v is not None]
    if not s:
        return None
    s.sort()
    d_last, v_last = s[-1]
    if last is not None:
        v_last = last
    dt_last = datetime.strptime(d_last[:10], "%Y-%m-%d").date()

    def at_or_before(days):
        target = (dt_last - timedelta(days=days)).isoformat()
        cand = [v for d, v in s if d[:10] <= target]
        return cand[-1] if cand else None

    prev = s[-2][1] if len(s) > 1 else None
    return {
        "last": v_last, "date": d_last,
        "d": pct(v_last, prev),
        "w": pct(v_last, at_or_before(7)),
        "m": pct(v_last, at_or_before(30)),
        "y": pct(v_last, at_or_before(365)),
    }
