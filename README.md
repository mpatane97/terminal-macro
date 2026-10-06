# Terminal Macro

Terminal personal de macro y mercados (EE.UU., Argentina y global), al estilo Bloomberg pero solo para mirar: no opera. No tiene servidor ni costo. GitHub Actions baja los datos de fuentes públicas, los guarda en la rama `datos` del repositorio y GitHub Pages publica la página que está en `docs/`.

Página: `https://<usuario>.github.io/terminal-macro/`

---

## Cómo funciona

```
fuentes públicas ──► GitHub Actions (scripts/*.py) ──► rama "datos" (prices.json, daily.json, history/)
                                                              │
                         docs/ (index.html, app.js, style.css) ◄── la página lee los JSON de la rama "datos"
```

| Corrida (Actions) | Cuándo (hora Argentina) | Qué hace | Tarda |
| --- | --- | --- | --- |
| **Precios cada 15 min** | lun a vie, 10:07 a 17:12 | `scripts/fetch_prices.py` → `prices.json` | ~20 s |
| **Datos diarios** | lun a vie, 20:07 | `scripts/fetch_daily.py` → `daily.json` y `fichas/` | ~1 min |
| **Prueba** | cada vez que se sube algo a `main` | `tests/regresion.py` + `tests/mock_run.py`: si falla, GitHub manda un mail | ~1 min |
| **Mantenimiento mensual** | día 1 de cada mes | reactiva las corridas y deja un commit, para que GitHub no las apague por inactividad | segundos |

- **Rama `main`**: el código. Solo cambia cuando se sube una actualización.
- **Rama `datos`**: los datos (incluye la carpeta `fichas/`, un archivo por bono con su historia). Cada corrida la reescribe con un único commit, así el repositorio no crece.
- Cada fuente es un "bloque" independiente que corre en paralelo con los demás. Si una fuente falla, ese bloque conserva su último dato válido marcado como viejo (punto amarillo en el panel), y el resto se actualiza igual.
- Arriba a la derecha aparece el aviso rojo **"! N datos a revisar"** si un dato lleva más de 2 días hábiles sin actualizarse, si un valor no tiene sentido, si el ratio de un ADR no cierra con el CCL o si falta una condición (por ejemplo, el margen de un bono TAMAR nuevo) (un bono que salta más de 15% en el día, una TEM o TIR fuera de rango, un CCL implícito lejos del CCL).
- Las librerías tienen versión fija en `requirements.txt`: se actualizan a propósito, no solas.

GitHub puede demorar las corridas programadas entre 5 y 30 minutos. Si el repositorio pasa 60 días sin cambios, GitHub desactiva las corridas programadas; se reactivan desde la pestaña Actions.

## Uso

- **Buscador** (arriba, o tecla `/`): escribí un ticker o un nombre (GD30, MELI, Galicia) y Enter abre su ficha.
- **Fichas**: cualquier fila con `›` (bonos, letras, acciones, ADRs, empresas y "Qué se movió hoy") abre la ficha del activo.

## Archivos

| Archivo | Para qué |
| --- | --- |
| `docs/index.html`, `docs/app.js`, `docs/style.css` | La página: pestañas, tablas, gráficos, calendario y ficha de cada bono, empresa y acción argentina (clic en la fila). |
| `scripts/common.py` | Pedidos HTTP con reintentos, bloques con último dato válido, corrida en paralelo. |
| `scripts/fetch_prices.py` | Precios: mercados, dólares, bonos y acciones argentinas, cauciones, probabilidades de la Fed, noticias. |
| `scripts/fetch_daily.py` | Datos diarios: macro EE.UU., Fed, Treasuries, BCRA, INDEC, REM, bandas, dólar futuro, calendarios, balances, feriados. |
| `scripts/bonds.py` | Matemática de bonos: flujos, TIR, duration, paridad, TEM, liquidación T+1. |
| `scripts/lecaps.py` | Alta automática de LECAP/BONCAP y bonos CER nuevos. |
| `scripts/licitaciones.py` | Resultado de las licitaciones del Tesoro (noticias de Finanzas). |
| `scripts/empresas.py` | Ficha de cada empresa: historia de precio contra S&P 500 y sector, valuación, negocio, balances, analistas y noticias. |
| `scripts/acciones_ar.py` | Ficha de cada acción del panel líder: en pesos y dólares CCL, contra Merval y sector, ADR y valuación aproximada. |
| `scripts/tamar.py` | Bonos TAMAR: TAMAR promedio del período, pago final proyectado y valor técnico. |
| `scripts/fichas.py` | Historia de un año de cada bono y letra (precio y TIR/TEM de cada día) para la ficha. |
| `scripts/indec.py` | Lectura del calendario de difusión del INDEC (PDF). |
| `scripts/feriados.py` | Feriados de Argentina y de las bolsas del exterior. |
| `config/instruments.json` | Qué se muestra: índices, monedas, commodities, empresas, acciones (con su ADR y ratio), CEDEARs, sectores, bancos centrales, feeds de noticias. |
| `config/bonos.json` | Condiciones de emisión de bonos en dólares, BOPREAL y CER. También los pagos finales de LECAP cargados a mano, que ya no hace falta mantener. |
| `config/calendario_ar.json` | Eventos argentinos extra para sumar a mano (opcional). |
| `tests/mock_run.py` | Prueba sin internet: corre todo con respuestas simuladas. |
| `.github/workflows/*.yml` | Las dos corridas programadas. |

## Qué se actualiza solo

- **LECAP y BONCAP nuevas.** El pago final se calcula con la ficha técnica de BYMA. Si la ficha no trae la tasa, se usa el resultado de licitación de Finanzas.
- **Bonos CER cero cupón nuevos.** El CER inicial se toma del BCRA, 10 días hábiles antes de la emisión. Las especies en otra moneda del mismo bono se descartan.
- **Calendario.** Se arma con varias fuentes:
  - INDEC: PDF semestral.
  - Licitaciones del Tesoro: PDF del cronograma, leído por los colores.
  - Reuniones de la Fed: página oficial.
  - Pagos de deuda: flujos propios.
  - Feriados.
- **Splits y cambios de ratio de acciones y CEDEARs.** Se ajusta la historia de precios.
- **Panel general.** Cada día se eligen las 15 acciones más operadas fuera del panel líder (`panel_general_cantidad`).

## Qué sigue siendo manual (y avisa si se queda sin datos)

- Margen sobre TAMAR de cada bono TAMAR nuevo: `config/instruments.json` → `tamar_margenes` (sale del resultado de su licitación). Los bonos nuevos aparecen solos; si falta el margen, aparece el aviso rojo.
- Ratio de cada ADR argentino: `config/instruments.json` → `argentina.empresas`. Si una empresa cambia el ratio (como YPF), el aviso rojo lo detecta.
- Fechas de decisión del BCE, Banco de Inglaterra, Banco de Japón y Copom: `config/instruments.json` → `bancos_centrales`. Cargadas hasta mediados de 2027. Si un banco se queda sin fechas futuras, aparece el aviso rojo.
- Bonos en dólares con cupón (AL/GD, AO/AN, BOPREAL) y CER con cupón (TX26/TX28/TX31): sus condiciones están en `config/bonos.json`. Solo hay que tocarlo si se emite un bono nuevo de este tipo.

## Fuentes y alternativas

"Respaldo automático" = el código ya prueba otra fuente si la principal falla. Si no hay respaldo, se muestra el último dato válido con el aviso.

| Dato | Fuente principal | Respaldo automático | Alternativa posible (no implementada) |
| --- | --- | --- | --- |
| Índices, futuros, monedas, commodities, cripto, sectores, ETFs, ADRs, empresas | Yahoo Finance (yfinance) | Stooq, símbolo por símbolo (no cubre Russell 2000, VIX, Merval ni Aramco) | Alpha Vantage (con clave) |
| Capitalización de empresas | Yahoo Finance (sale de la ficha de cada empresa) | — | Financial Modeling Prep (con clave) |
| Dólares (mayorista, MEP, CCL, blue, cripto) | dolarapi.com | argentinadatos.com (último dato de cada casa) | Ámbito |
| Bonos, letras, acciones y CEDEARs argentinos | data912.com | BYMA open data (paneles públicos; sin MEP/CCL implícito de CEDEARs) | — |
| Historia de precios argentinos | data912.com (histórico) | se arma sola con los cierres diarios | BYMA serie histórica |
| Cauciones 1, 7 y 14 días | Rava (página pública) | BYMA open data (sin probar todavía con datos reales) | — |
| Dólar futuro | A3 Mercados (cierres oficiales) | — | Rava, sinelefantesblancos |
| Probabilidades de la Fed | Kalshi | — | Polymarket; CME FedWatch (sin API gratis) |
| Macro EE.UU. (CPI, PCE, empleo, PBI) y Treasuries | FRED (con clave) | — | APIs de BLS / BEA / Tesoro de EE.UU. |
| ISM manufacturero | Comunicado de prensa (PR Newswire) | — | — |
| Tasa de la Fed / EFFR / dot plot | FRED, NY Fed, federalreserve.gov | — | — |
| Fechas de reuniones FOMC | federalreserve.gov | lista en `instruments.json` | — |
| BCRA (A3500, reservas, compras, tasas, CER, UVA, REM 12m) | API BCRA v4 | si falla el certificado, reintenta sin verificar | argentinadatos.com |
| IPC y EMAE | datos.gob.ar (INDEC) | — | API BCRA (inflación) |
| Riesgo país, REM, historia del dólar | argentinadatos.com | — | Ámbito, BCRA (REM en Excel) |
| Bandas cambiarias | BCRA (Excel) | — | cálculo con la regla vigente |
| Calendario INDEC | PDF de calendario de difusión | eventos de `calendario_ar.json` | — |
| Licitaciones del Tesoro | PDF del cronograma de Finanzas | — | anuncios "Llamado a licitación" |
| Resultado de licitaciones | Noticias de la Secretaría de Finanzas (tablas del resultado) | — | comunicado del Ministerio de Economía |
| Ficha de empresas (valuación, negocio, balances, analistas, noticias, historia) | Yahoo Finance (yfinance) | Finnhub (datos), Stooq (precios) | Financial Modeling Prep (con clave) |
| Ficha de acciones argentinas | BYMA (historia), argentinadatos (CCL), Yahoo (Merval, ADR y estados contables) | cierres de data912; Stooq para ADRs | — |
| Historia de bonos y letras (ficha) | BYMA open data (serie histórica 24hs) | bonos en dólares: cierres guardados de data912 | — |
| Bonos TAMAR (TIR) | BCRA (TAMAR bancos privados) + fechas de la ficha de BYMA + margen de licitación (`tamar_margenes` en config) | — | — |
| Panel general (más operadas) | data912 (monto operado) | — | BYMA paneles |
| Dólar linked | data912.com (precios) + A3500 del BCRA | BYMA open data | — |
| Tasas de política (Fed, BCE, BoE, BoJ, Selic) | FRED (Fed, BCE), Bank of England, BIS (BoJ), Banco Central do Brasil (Selic) | Selic: BIS | páginas de cada banco central |
| Condiciones de LECAP/BONCAP nuevas | Ficha técnica de BYMA | Resultado de licitación de Finanzas | carga en `bonos.json` |
| Condiciones de CER nuevos | Ficha técnica de BYMA + CER del BCRA | — | carga en `bonos.json` |
| Calendario EE.UU. e internacional | Forex Factory | — | Investing (sin API) |
| Balances de empresas | Finnhub (con clave) | — | Nasdaq earnings calendar |
| Feriados | argentinadatos (AR), librería holidays (resto) | librería holidays para Argentina | — |
| Noticias | RSS (WSJ, MarketWatch, Ámbito, La Nación, Bloomberg Línea, Fed) | si un feed falla, siguen los demás | — |

## Subir una actualización

1. Entrar a la carpeta del repo en GitHub (por ejemplo `.../upload/main/scripts`).
2. Arrastrar los archivos y tocar **Commit changes**.
3. Si cambió algo de `scripts/` o `config/`, correr en Actions **Datos diarios** y después **Precios cada 15 min**.
4. Si cambió algo de `docs/`, recargar la página con **Ctrl + F5**.

## Si algo falla

- **Aviso rojo arriba a la derecha**: tocarlo muestra qué dato está viejo y el error de la fuente.
- **Una corrida en Actions con cruz roja**: abrirla y mirar el paso que falló. Si es "Bajar datos", alguna librería o un archivo quedó mal subido. Volver a subir el archivo.
- **La página no muestra cambios nuevos**: Ctrl + F5, o esperar unos minutos a que GitHub Pages se actualice.
- **Los datos no se actualizan**: revisar que las corridas sigan activas en Actions (GitHub las apaga tras 60 días sin cambios).

## Puesta en marcha desde cero

1. Repositorio **público** en GitHub, con todo este contenido, incluida la carpeta `.github`.
2. **Settings → Secrets and variables → Actions**: cargar `FRED_API_KEY` y `FINNHUB_API_KEY`.
3. **Settings → Pages**: "Deploy from a branch", rama `main`, carpeta `/docs`.
4. **Actions**: correr **Datos diarios** y después **Precios cada 15 min**. La primera corrida crea la rama `datos`.

## Prueba local sin internet

```
pip install -r requirements.txt
python tests/mock_run.py
```

Corre todo con respuestas simuladas y escribe el resultado en `tests/out/`.
