# Terminal Macro

Dashboard personal de macro y mercados (EE.UU., Argentina y global). Sin servidor y sin costo: GitHub Actions baja los datos y los guarda en `docs/data/`, y GitHub Pages publica la página de `docs/`.

## Puesta en marcha (una sola vez)

1. Crear un repositorio **público** nuevo en GitHub, por ejemplo `terminal-macro`. Si es privado, el plan gratuito de Actions no alcanza para correr cada 15 minutos.
2. Subir todo el contenido de esta carpeta, incluida la carpeta oculta `.github`.
3. **Settings → Secrets and variables → Actions → New repository secret**. Cargar:
   - `FRED_API_KEY`
   - `FINNHUB_API_KEY`
4. **Settings → Pages → Build and deployment**: Source "Deploy from a branch", Branch `main`, carpeta `/docs`.
5. **Actions**: habilitar los workflows y correr a mano "Datos diarios" y después "Precios cada 15 min" (botón *Run workflow*).
6. La página queda en `https://<tu-usuario>.github.io/terminal-macro/`.

## Qué corre y cuándo

| Workflow | Horario (hora Argentina) | Archivo |
| --- | --- | --- |
| Precios cada 15 min | lun a vie, 10:00 a 17:00 | `docs/data/prices.json` |
| Datos diarios | lun a vie, 20:00 | `docs/data/daily.json` |

GitHub puede demorar las corridas programadas entre 5 y 30 minutos. Si el repositorio pasa 60 días sin cambios manuales, GitHub desactiva los workflows: se reactivan desde la pestaña Actions.

## Configuración editable

- `config/instruments.json`: tickers, monedas, commodities, acciones, CEDEARs, empresas para earnings, watchlist, fechas FOMC y feeds de noticias.
- `config/bonos.json`: condiciones de emisión de los bonos para calcular TIR, y pago final de LECAPs/BONCAPs para calcular TEM.
- `config/calendario_ar.json`: fechas de INDEC y licitaciones (carga manual).

## Prueba local sin red

```
pip install -r requirements.txt
python tests/mock_run.py
```

Corre ambos scripts con respuestas simuladas y escribe el resultado en `tests/out/`.
