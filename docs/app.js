/* Terminal: lee docs/data/*.json (generados por GitHub Actions) y arma las pestañas. Sin dependencias. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const NF = (d) => new Intl.NumberFormat("es-AR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const fmt = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "—" : NF(d).format(v));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const cls = (v) => (v === null || v === undefined ? "na" : v > 0.0001 ? "up" : v < -0.0001 ? "down" : "flat");
  const chg = (v, d = 2, suf = "%") => (v === null || v === undefined ? `<span class="na">—</span>` : `<span class="${cls(v)}">${v > 0 ? "+" : ""}${fmt(v, d)}${suf}</span>`);
  // para indicadores donde subir es malo (riesgo país): mismo número, colores invertidos
  const chgInv = (v, d = 2, suf = "%") => chg(v, d, suf).replace(/class="(up|down)"/, (m, c) => `class="${c === "up" ? "down" : "up"}"`);
  const dec = (v) => (v === null || v === undefined ? 2 : Math.abs(v) >= 1000 ? 0 : Math.abs(v) >= 100 ? 1 : Math.abs(v) >= 10 ? 2 : 3);
  const hhmm = (iso) => { if (!iso) return "—"; const d = new Date(iso); return isNaN(d) ? "—" : d.toLocaleString("es-AR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "America/Argentina/Buenos_Aires" }); };
  const dmy = (iso) => { if (!iso) return "—"; const [y, m, d] = String(iso).slice(0, 10).split("-"); return `${d}/${m}/${y.slice(2)}`; };

  let P = {}, D = {};
  const blk = (src, name) => (src[name] && src[name].data) ?? null;
  const meta = (src, name) => src[name] || {};

  function panel(title, inner, opts = {}) {
    const m = opts.meta || {};
    const stale = m.stale ? `<span class="stale-dot" title="Dato viejo: ${esc(m.error || "la fuente no respondió")}"></span>` : "";
    const src = opts.src ?? (m.source ? `${esc(m.source)} · ${hhmm(m.updated)}` : "");
    return `<section class="panel ${opts.lead ? "lead" : ""}"><h2><span>${esc(title)}${stale}</span><span class="src">${src}</span></h2><div class="body">${inner}</div></section>`;
  }
  const table = (head, rows, left = []) => rows.length
    ? `<div class="scroll"><table><thead><tr>${head.map((h, i) => `<th${left.includes(i) ? ' class="txt"' : ""}>${h}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td${left.includes(i) ? ' class="txt"' : ""}>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
    : `<div class="empty">Sin datos todavía.</div>`;
  const byId = (arr, id) => (arr || []).find((x) => x.id === id) || {};

  // filas de precio: nombre, último, variaciones elegidas
  const priceRows = (items, cols) => (items || []).map((i) => [
    `${esc(i.nombre)}${i.unidad ? `<span class="sub">${esc(i.unidad)}</span>` : ""}`,
    fmt(i.last, dec(i.last)), ...cols.map((c) => chg(i[c])),
  ]);
  const VARS = { d: "Día", w: "Sem", m: "Mes", y: "Año" };

  /* ---------- Gráfico de dispersión/curva (SVG propio) ---------- */
  function curve(series, o) {
    const W = 640, H = 260, L = 46, R = 40, T = 14, B = 34;
    const pts = series.flatMap((s) => s.points).filter((p) => p.x != null && p.y != null);
    if (!pts.length) return `<div class="empty">Sin datos para la curva.</div>`;
    let x0 = o.xmin ?? Math.min(...pts.map((p) => p.x)), x1 = Math.max(...pts.map((p) => p.x));
    let y0 = Math.min(...pts.map((p) => p.y)), y1 = Math.max(...pts.map((p) => p.y));
    const py = (y1 - y0) * 0.15 || 0.5; y0 -= py; y1 += py; if (x1 === x0) x1 = x0 + 1;
    const fx = o.xfn || ((v) => v);
    const X = (v) => L + ((fx(v) - fx(x0)) / (fx(x1) - fx(x0))) * (W - L - R);
    const Y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
    const yt = niceTicks(y0, y1, 5);
    const xt = o.xticks || niceTicks(x0, x1, 6);
    let g = yt.map((t) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(t)}" y2="${Y(t)}"/><text x="${L - 6}" y="${Y(t) + 4}" text-anchor="end">${fmt(t, o.ydec ?? 1)}</text>`).join("");
    const xdec = !o.xticks && xt.length > 1 && xt[1] - xt[0] < 1 ? 1 : 0;
    g += xt.map((t) => `<text x="${X(t.v ?? t)}" y="${H - B + 16}" text-anchor="middle">${esc(t.l ?? fmt(t, xdec))}</text>`).join("");
    g += `<text x="${(L + W - R) / 2}" y="${H - 4}" text-anchor="middle">${esc(o.xlabel || "")}</text>`;
    g += `<text x="12" y="${T + 4}" transform="rotate(-90 12 ${T + 4})" text-anchor="end">${esc(o.ylabel || "")}</text>`;
    series.forEach((s, si) => {
      const ps = s.points.filter((p) => p.x != null && p.y != null).sort((a, b) => a.x - b.x);
      if (s.fit && ps.length > 2) {
        // ajuste logarítmico y = a + b·ln(x), como las curvas de bonistas
        const xs = ps.map((p) => Math.log(Math.max(p.x, 0.05))), ys = ps.map((p) => p.y), n = xs.length;
        const mx = xs.reduce((a, b) => a + b) / n, my = ys.reduce((a, b) => a + b) / n;
        const b = xs.reduce((acc, x, i) => acc + (x - mx) * (ys[i] - my), 0) / (xs.reduce((acc, x) => acc + (x - mx) ** 2, 0) || 1);
        const a = my - b * mx, xa = ps[0].x, xb = ps[ps.length - 1].x;
        const fitPts = Array.from({ length: 40 }, (_, k) => { const x = xa + (xb - xa) * k / 39; return `${X(x)},${Y(a + b * Math.log(Math.max(x, 0.05)))}`; });
        g += `<polyline class="${s.cls}" fill="none" stroke-width="2" stroke-opacity="0.55" points="${fitPts.join(" ")}"/>`;
      }
      if (s.line && ps.length > 1) g += `<polyline class="${s.cls}" fill="none" stroke-width="${s.ghost ? 1 : 2}" ${s.ghost ? 'stroke-dasharray="4 4"' : ""} points="${ps.map((p) => `${X(p.x)},${Y(p.y)}`).join(" ")}"/>`;
      if (!s.nodots) g += ps.map((p) => `<circle class="${s.cls}" cx="${X(p.x)}" cy="${Y(p.y)}" r="${s.ghost ? 2.5 : 3.5}"><title>${esc(p.label || "")} ${fmt(p.y, o.tdec ?? 2)}${o.ysuf ?? "%"}</title></circle>${p.label && !s.ghost && !s.nolabel ? `<text class="lbl" x="${X(p.x) + 5}" y="${Y(p.y) + (si % 2 ? 15 : -7)}">${esc(p.label)}</text>` : ""}`).join("");
    });
    const leg = series.length > 1 ? `<div class="legend">${series.map((s) => `<span><i class="${s.cls}" style="background:currentColor"></i>${esc(s.name)}</span>`).join("")}</div>` : "";
    return `${leg}<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.title || "curva")}">${g}</svg></div>`;
  }
  function niceTicks(a, b, n) {
    const span = b - a, step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || mag * 10;
    const out = []; for (let v = Math.ceil(a / step) * step; v <= b + 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }

  /* ---------- Gráfico con dos ejes: tasa (izquierda) y pesos por dólar (derecha) ---------- */
  function curvaDoble(izq, der, o) {
    const W = 640, H = 280, L = 46, R = 56, T = 14, B = 34;
    const pi = izq.flatMap((s) => s.points), pd = der.flatMap((s) => s.points);
    if (!pi.length) return `<div class="empty">Sin datos para la curva.</div>`;
    const x0 = 0, x1 = Math.max(...pi.map((p) => p.x), ...pd.map((p) => p.x)) * 1.03;
    const rango = (ps) => { let a = Math.min(...ps.map((p) => p.y)), b = Math.max(...ps.map((p) => p.y)); const m = (b - a) * 0.12 || 1; return [a - m, b + m]; };
    const [a0, a1] = rango(pi), [b0, b1] = pd.length ? rango(pd) : [0, 1];
    const X = (v) => L + ((v - x0) / (x1 - x0)) * (W - L - R);
    const YA = (v) => T + (1 - (v - a0) / (a1 - a0)) * (H - T - B), YB = (v) => T + (1 - (v - b0) / (b1 - b0)) * (H - T - B);
    let g = niceTicks(a0, a1, 5).map((t) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${YA(t)}" y2="${YA(t)}"/><text x="${L - 6}" y="${YA(t) + 4}" text-anchor="end">${fmt(t, 2)}</text>`).join("");
    if (pd.length) g += niceTicks(b0, b1, 5).map((t) => `<text x="${W - R + 6}" y="${YB(t) + 4}" text-anchor="start">${fmt(t, 0)}</text>`).join("");
    g += niceTicks(x0, x1, 6).map((t) => `<text x="${X(t)}" y="${H - B + 16}" text-anchor="middle">${fmt(t, 0)}</text>`).join("");
    g += `<text x="${(L + W - R) / 2}" y="${H - 4}" text-anchor="middle">${esc(o.xlabel || "")}</text>`;
    g += `<text x="12" y="${T + 4}" transform="rotate(-90 12 ${T + 4})" text-anchor="end">${esc(o.ylabel || "")}</text>`;
    g += `<text x="${W - 6}" y="${T + 4}" transform="rotate(-90 ${W - 6} ${T + 4})" text-anchor="end">${esc(o.ylabel2 || "")}</text>`;
    const dibujar = (s, Y, suf, dec) => {
      const ps = s.points.filter((p) => p.x != null && p.y != null).sort((a, b) => a.x - b.x);
      let h = "";
      if (s.fit && ps.length > 2) {
        const xs = ps.map((p) => Math.log(Math.max(p.x, 0.05))), ys = ps.map((p) => p.y), n = xs.length;
        const mx = xs.reduce((a, b) => a + b) / n, my = ys.reduce((a, b) => a + b) / n;
        const b = xs.reduce((acc, x, i) => acc + (x - mx) * (ys[i] - my), 0) / (xs.reduce((acc, x) => acc + (x - mx) ** 2, 0) || 1), a = my - b * mx;
        const xa = ps[0].x, xb = ps[ps.length - 1].x;
        h += `<polyline class="${s.cls}" fill="none" stroke-width="2" stroke-opacity="0.55" points="${Array.from({ length: 40 }, (_, k) => { const x = xa + (xb - xa) * k / 39; return `${X(x)},${Y(a + b * Math.log(Math.max(x, 0.05)))}`; }).join(" ")}"/>`;
      }
      if (s.line && ps.length > 1) h += `<polyline class="${s.cls}" fill="none" stroke-width="${s.ghost ? 1 : 2}" ${s.ghost ? 'stroke-dasharray="4 4"' : ""} points="${ps.map((p) => `${X(p.x)},${Y(p.y)}`).join(" ")}"/>`;
      if (!s.nodots) h += ps.map((p, i) => `<circle class="${s.cls}" cx="${X(p.x)}" cy="${Y(p.y)}" r="${s.small ? 2.5 : 3.5}"><title>${esc(p.label || "")} ${fmt(p.y, dec)}${suf}</title></circle>`
        + (p.label && s.labels ? `<text class="lbl" x="${X(p.x) + 5}" y="${Y(p.y) + (i % 2 ? 14 : -7)}">${esc(p.label)}</text>` : "")).join("");
      return h;
    };
    izq.forEach((s) => { g += dibujar(s, YA, "%", 2); });
    der.forEach((s) => { g += dibujar(s, YB, "", 0); });
    const leg = `<div class="legend">${[...izq.map((s) => [s, "eje izq."]), ...der.map((s) => [s, "eje der."])].map(([s, e]) => `<span class="${s.cls}"><i class="${s.cls}"></i>${esc(s.name)} <span class="na">(${e})</span></span>`).join("")}</div>`;
    return `${leg}<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.title || "curva")}">${g}</svg></div>`;
  }

  /* ---------- Fed: probabilidades de la próxima reunión ---------- */
  function fedOutlook(i = 0) {
    const ev = (blk(P, "fed_probs") || [])[i];
    const fed = blk(D, "fed");
    if (!ev || !fed || !fed.rango) return null;
    const hi = fed.rango[1];
    // Los umbrales de Kalshi KXFED se refieren al techo del rango. Tramo "desde s" = techo s+0,25.
    let cut = ev.prob_debajo || 0, hold = 0, hike = 0, esperado = (ev.prob_debajo || 0) * ev.debajo_de;
    for (const t of ev.tramos) {
      const techo = +(t.desde + 0.25).toFixed(2);
      esperado += t.prob * techo;
      if (techo < hi - 0.001) cut += t.prob; else if (Math.abs(techo - hi) < 0.001) hold += t.prob; else hike += t.prob;
    }
    const tot = cut + hold + hike || 100;
    return { ev, cut, hold, hike, esperado: esperado / tot };
  }

  /* ---------- Vistas ---------- */

  /* ---------- Qué se movió hoy: mayores subas y bajas del día entre todos los activos ---------- */
  const GRUPO = { indices_eeuu: "Índice", futuros: "Futuro", volatilidad: "Volatilidad", indices_mundo: "Índice", monedas: "Moneda", commodities: "Commodity",
    cripto: "Cripto", argentina: "Índice AR", sectores: "Sector EE.UU.", bonos_etf: "ETF bonos", adrs: "ADR", megacaps_eeuu: "Acción EE.UU.", megacaps_global: "Acción global", empresas_seleccion: "Tu selección" };
  function movers() {
    const mk = blk(P, "markets") || {}, arm = blk(P, "ar_market") || {};
    const seen = new Set(), all = [];
    const add = (nombre, tipo, d, key) => { if (d == null || !isFinite(d) || Math.abs(d) > 40 || seen.has(key)) return; seen.add(key); all.push({ nombre, tipo, d }); };
    for (const [g, arr] of Object.entries(mk)) for (const r of arr || []) add(r.nombre, GRUPO[g] || g, r.d, "Y:" + r.id);
    for (const r of [...(arm.panel_lider || []), ...(arm.acciones || [])]) add(r.ticker, "Acción AR", r.d, "A:" + r.ticker);
    for (const r of [...(arm.soberanos || []), ...(arm.bopreal || [])]) add(r.ticker, "Bono USD", r.d, "B:" + r.ticker);
    for (const r of [...(arm.pesos_fija || []), ...(arm.cer_tamar || [])]) add(r.ticker, r.tipo || "Bono $", r.d, "P:" + r.ticker);
    if (!all.length) return "";
    const ord = [...all].sort((a, b) => b.d - a.d);
    const li = (r) => `<li><span>${esc(r.nombre)}<span class="sub">${esc(r.tipo)}</span></span>${chg(r.d)}</li>`;
    const nUp = all.filter((r) => r.d > 0).length;
    return `<section class="panel lead movers"><h2>Qué se movió hoy <span class="src">${all.length} activos · ${nUp} suben, ${all.length - nUp} bajan o sin cambio</span></h2>
      <div class="mv-grid"><div><h3>Mayores subas</h3><ul class="mv">${ord.slice(0, 6).map(li).join("")}</ul></div>
      <div><h3>Mayores bajas</h3><ul class="mv">${ord.slice(-6).reverse().map(li).join("")}</ul></div></div></section>`;
  }

  function viewResumen() {
    const mk = blk(P, "markets") || {};
    const all = Object.values(mk).flat();
    const pick = (ids) => ids.map((id) => all.find((x) => x.id === id)).filter(Boolean);
    const cols = ["d", "m"];
    const head = ["", "Último", "Día", "Mes"];
    const tsy = (blk(D, "treasuries") || {}).curva || [];
    const fed = blk(D, "fed") || {};
    const fo = fedOutlook(0);
    const macro = blk(D, "us_macro") || [];
    const cpi = macro.find((r) => r.id === "CPIAUCSL") || {}, un = macro.find((r) => r.id === "UNRATE") || {};

    const us = table(head, priceRows(pick(["SPX", "NDX", "DJI", "ES", "NQ", "YM", "VIX"]), cols))
      + `<h3>Tasas y Fed</h3>` + table(["", "Tasa", "Día", "Mes"], tsy.filter((r) => ["2y", "5y", "10y"].includes(r.plazo)).map((r) => [`Treasury ${r.plazo}`, fmt(r.tasa, 2) + "%", chg(r.d_pb, 0, " pb"), chg(r.m_pb, 0, " pb")]))
      + `<dl class="kv"><dt>Fed funds</dt><dd>${fed.rango ? `${fmt(fed.rango[0], 2)}–${fmt(fed.rango[1], 2)}%` : "—"}</dd>
         <dt>Próximo FOMC</dt><dd>${dmy((fed.proximo_fomc || [])[0])}</dd>
         ${fo ? `<dt>Recorte / mantener / suba</dt><dd>${fmt(fo.cut, 0)} / ${fmt(fo.hold, 0)} / ${fmt(fo.hike, 0)}%</dd>` : ""}
         <dt>CPI (${esc(cpi.periodo || "—")})</dt><dd>${fmt(cpi.valor, 1)}% i.a.</dd>
         <dt>Desempleo (${esc(un.periodo || "—")})</dt><dd>${fmt(un.valor, 1)}%</dd></dl>`;

    const dol = blk(P, "dolares") || {}, cot = dol.cotizaciones || [], br = dol.brechas || {};
    const ban = blk(D, "bandas"), rp = blk(D, "riesgo_pais") || {}, bc = blk(D, "ar_bcra") || {}, ip = blk(D, "ipc") || {};
    const arm = blk(P, "ar_market") || {}, sob = arm.soberanos || [];
    const a3500 = byId(cot, "mayorista").venta;
    const ar = table(head, ["mayorista", "bolsa", "contadoconliqui"].map((id) => { const r = byId(cot, id); return [esc(r.nombre || id), fmt(r.venta, 2), chg(r.d), chg(r.m)]; })
      .concat([["Riesgo país", fmt(rp.last, 0), chgInv(rp.d_pb, 0, " pb"), chgInv(rp.m)]])
      .concat(priceRows(pick(["MERVAL"]), cols)))
      + `<h3>Brechas y banda</h3><dl class="kv"><dt>CCL / A3500</dt><dd>${fmt(br.ccl_a3500, 1)}%</dd><dt>MEP / A3500</dt><dd>${fmt(br.mep_a3500, 1)}%</dd><dt>CCL / MEP</dt><dd>${fmt(br.ccl_mep, 1)}%</dd>
         <dt>Techo de banda</dt><dd>${ban ? fmt(ban.techo, 2) : "—"}</dd><dt>Distancia al techo</dt><dd>${ban && a3500 ? fmt((ban.techo / a3500 - 1) * 100, 1) + "%" : "—"}</dd></dl>`
      + `<h3>Bonos y tasas</h3>` + table(["", "USD", "Día", "TIR"], sob.filter((r) => ["AL30", "GD30"].includes(r.ticker)).map((r) => [r.ticker, fmt(r.usd, 2), chg(r.d), r.tir != null ? fmt(r.tir, 1) + "%" : "—"]))
      + `<dl class="kv"><dt>TAMAR</dt><dd>${fmt(bc.tamar?.valor, 2)}%</dd><dt>IPC ${esc(ip.periodo || "")}</dt><dd>${fmt(ip.mensual, 1)}% m/m · ${fmt(ip.interanual, 1)}% i.a.</dd><dt>REM 12 meses</dt><dd>${fmt(bc.rem_12m?.valor, 1)}%</dd></dl>`;

    const gl = table(head, priceRows(pick(["DXY", "EURUSD", "USDBRL", "SX5E", "N225", "BVSP", "WTI", "BRENT", "ORO", "PLATA", "SOJA", "TRIGO", "MAIZ", "BTC"]), cols));

    return `<div class="cols-3">${panel("EE.UU. y Fed", us, { lead: true, meta: meta(P, "markets") })}${panel("Argentina", ar, { meta: meta(P, "dolares") })}${panel("Global y commodities", gl, { meta: meta(P, "markets") })}</div>
      ${movers()}<div class="cols-2">${panel("Próximos eventos", eventsList(upcoming().slice(0, 5)), { src: "" })}${panel("Titulares", newsList(mergedNews().slice(0, 5)), { meta: meta(P, "news") })}</div>`;
  }

  const chip = (estado, txt) => `<span class="chip ${estado}">${txt}</span>`;
  function lecturaEEUU() {
    const fed = blk(D, "fed") || {}, ts = blk(D, "treasuries") || {}, macro = blk(D, "us_macro") || [], sen = blk(D, "us_senales") || {};
    const mk = blk(P, "markets") || {}, vix = (mk.volatilidad || [])[0] || {};
    const t = Object.fromEntries((ts.curva || []).map((r) => [r.plazo, r.tasa]));
    const cpi = macro.find((r) => r.id === "CPIAUCSL") || {}, pce = macro.find((r) => r.id === "PCEPILFE") || {}, un = macro.find((r) => r.id === "UNRATE") || {};
    const mid = fed.rango ? (fed.rango[0] + fed.rango[1]) / 2 : null;
    const c10_3 = t["10y"] != null && t["3m"] != null ? (t["10y"] - t["3m"]) * 100 : null;
    const o0 = fedOutlook(0), oDic = [0, 1, 2].map(fedOutlook).find((o) => o && String(o.ev.fecha).slice(5, 7) === "12");
    const dot26 = ((fed.dot_plot || {}).mediana || []).find((m) => m.periodo === String(new Date().getFullYear()));
    const kalDic = oDic ? oDic.esperado - 0.125 : null;   // techo esperado → punto medio del rango
    const realPce = mid != null && pce.valor != null ? mid - pce.valor : null, realCpi = mid != null && cpi.valor != null ? mid - cpi.valor : null;

    // semáforo
    const sem = [];
    if (c10_3 != null) sem.push(["Curva 10 años – 3 meses", `${fmt(c10_3, 0)} pb`, c10_3 < 0 ? chip("rojo", "Invertida") : c10_3 < 50 ? chip("amarillo", "Plana") : chip("verde", "Con pendiente"), "Invertida: señal histórica de recesión"]);
    if (vix.last != null) sem.push(["VIX", fmt(vix.last, 1), vix.last > 25 ? chip("rojo", "Estrés") : vix.last > 15 ? chip("amarillo", "Normal") : chip("verde", "Calma"), "Menos de 15 calma · más de 25 estrés"]);
    if (cpi.valor != null && cpi.anterior != null) { const dlt = cpi.valor - cpi.anterior; sem.push(["Tendencia del CPI", `${fmt(cpi.anterior, 1)}% → ${fmt(cpi.valor, 1)}%`, dlt > 0.05 ? chip("rojo", "Acelera") : dlt < -0.05 ? chip("verde", "Desacelera") : chip("amarillo", "Estable"), "Interanual vs. mes anterior"]); }
    if (sen.sahm != null) sem.push(["Regla de Sahm", fmt(sen.sahm, 2), sen.sahm >= 0.5 ? chip("rojo", "Señal de recesión") : sen.sahm >= 0.3 ? chip("amarillo", "Atención") : chip("verde", "Sin señal"), "Desempleo (prom. 3 meses) vs. mínimo de 12 meses · 0,5 = señal"]);

    // mercado vs Fed
    const mvf = [];
    if (kalDic != null && dot26) mvf.push(["Tasa a fin de año", `${fmt(kalDic, 2)}%`, `${fmt(dot26.tasa, 2)}%`, kalDic - dot26.tasa]);
    if (t["2y"] != null && mid != null) mvf.push(["Treasury 2 años vs. fed funds", `${fmt(t["2y"], 2)}%`, `${fmt(mid, 2)}%`, t["2y"] - mid]);

    // lectura automática
    const L = [];
    if (cpi.valor != null) L.push(`La inflación ${cpi.valor > cpi.anterior + 0.05 ? "acelera" : cpi.valor < cpi.anterior - 0.05 ? "desacelera" : "se mantiene"}: el CPI interanual pasó de ${fmt(cpi.anterior, 1)}% a ${fmt(cpi.valor, 1)}%, y el Core PCE (la medida que sigue la Fed) está en ${fmt(pce.valor, 1)}%, ${pce.valor > 2.2 ? "por encima" : "cerca"} del objetivo de 2%.`);
    if (realPce != null) L.push(`La tasa real de la Fed (fed funds menos Core PCE) es ${fmt(realPce, 1)}%: la política monetaria es ${realPce > 1 ? "restrictiva" : realPce >= 0 ? "neutral o apenas restrictiva" : "expansiva"}.`);
    if (o0) L.push(`Para la próxima reunión (${dmy(o0.ev.fecha)}) Kalshi asigna ${fmt(o0.hold, 0)}% a mantener, ${fmt(o0.hike, 0)}% a una suba y ${fmt(o0.cut, 0)}% a un recorte.`);
    if (kalDic != null && dot26) { const dd = kalDic - dot26.tasa; L.push(`El mercado espera la tasa en ${fmt(kalDic, 2)}% a fin de año, ${Math.abs(dd) < 0.1 ? "en línea con" : dd > 0 ? "por encima de" : "por debajo de"} la mediana del dot plot (${fmt(dot26.tasa, 2)}%).`); }
    if (c10_3 != null) L.push(`La curva 10 años – 3 meses está ${c10_3 < 0 ? "invertida" : c10_3 < 50 ? "casi plana" : "con pendiente positiva"} (${fmt(c10_3, 0)} pb)${t["10y"] != null ? `, con el 10 años en ${fmt(t["10y"], 2)}%` : ""}.`);
    if (un.valor != null && sen.sahm != null) L.push(`El desempleo está en ${fmt(un.valor, 1)}% y la regla de Sahm en ${fmt(sen.sahm, 2)}: ${sen.sahm >= 0.5 ? "activó la señal de recesión" : sen.sahm >= 0.3 ? "se acerca a la señal de recesión (0,5)" : "lejos de la señal de recesión (0,5)"}.`);

    const lect = `<ul class="lectura">${L.map((x) => `<li>${esc(x)}</li>`).join("")}</ul><div class="note">Texto generado con reglas fijas a partir de los datos de esta pestaña; no es una recomendación.</div>`;
    const semT = table(["Señal", "Valor", "Estado", "Cómo leerla"], sem, [3]);
    const mvfT = table(["", "Mercado", "Fed", "Diferencia"], mvf.map((r) => [r[0], r[1], r[2], chg(r[3] * 100, 0, " pb")]))
      + `<div class="note">Mercado: Kalshi (diciembre) y Treasury 2 años. Fed: mediana del dot plot y punto medio del rango.</div>`;
    const realT = table(["", "Tasa real"], [["Fed funds − CPI", realCpi != null ? chg(realCpi, 2) : "—"], ["Fed funds − Core PCE", realPce != null ? chg(realPce, 2) : "—"]])
      + `<div class="note">Positiva: la política frena la economía. Negativa: la estimula.</div>`;
    return { lect: panel("Lectura del momento", lect, { lead: true, src: "" }), sem: panel("Semáforo de señales", semT, { src: "" }),
      mvf: panel("Mercado vs. Fed", mvfT, { src: "" }), real: panel("Tasa real", realT, { src: "" }) };
  }

  function viewEEUU() {
    const fed = blk(D, "fed") || {}, ts = blk(D, "treasuries") || {}, curva = ts.curva || [];
    const yrs = { "3m": 0.25, "2y": 2, "5y": 5, "10y": 10, "30y": 30 };
    const fedHtml = `<dl class="kv"><dt>Rango objetivo</dt><dd>${fed.rango ? `${fmt(fed.rango[0], 2)}–${fmt(fed.rango[1], 2)}%` : "—"}</dd>
      <dt>EFFR ${fed.effr ? `(${dmy(fed.effr.fecha)})` : ""}</dt><dd>${fmt(fed.effr?.valor, 2)}%</dd>
      <dt>Próximas reuniones</dt><dd>${(fed.fomc || []).map(dmy).join(" · ") || "—"}</dd></dl>`
      + `<h3>Trayectoria esperada · Kalshi</h3>` + table(["Reunión", "Recorte", "Mantener", "Suba", "Techo esperado"],
          [0, 1, 2].map(fedOutlook).filter(Boolean).map((o) => [dmy(o.ev.fecha), fmt(o.cut, 0) + "%", fmt(o.hold, 0) + "%", fmt(o.hike, 0) + "%", fmt(o.esperado, 2) + "%"]))
      + `<div class="note">Probabilidades respecto del techo actual (${fmt(fed.rango?.[1], 2)}%). Mercado de predicción: no equivale a CME FedWatch.</div>`
      + (fed.dot_plot ? `<h3>Dot plot · mediana del FOMC (${dmy(fed.dot_plot.fecha)})</h3>` + table(["Fin de", ...fed.dot_plot.mediana.map((m) => esc(m.periodo))], [["Fed funds", ...fed.dot_plot.mediana.map((m) => fmt(m.tasa, 2) + "%")]]) : "");
    const tsyHtml = table(["Plazo", "Tasa", "Día", "Mes", "Año"], curva.map((r) => [r.plazo, fmt(r.tasa, 2) + "%", chg(r.d_pb, 0, " pb"), chg(r.m_pb, 0, " pb"), chg(r.y_pb, 0, " pb")]))
      + `<dl class="kv"><dt>Spread 10y – 2y</dt><dd>${chg(ts.spread_10_2_pb, 0, " pb")}</dd></dl>`
      + curve([{ name: "Hoy", cls: "s1", line: true, points: curva.map((r) => ({ x: yrs[r.plazo], y: r.tasa, label: r.plazo })) },
               { name: "Hace 1 mes", cls: "ghost", line: true, ghost: true, points: curva.map((r) => ({ x: yrs[r.plazo], y: r.hace_1m })) }],
        { xfn: Math.sqrt, xmin: 0, xticks: [0.25, 2, 5, 10, 30].map((v) => ({ v, l: v < 1 ? "3m" : v + "a" })), xlabel: "Plazo", ylabel: "Rendimiento %", ydec: 2, title: "Curva de Treasuries" });
    const macro = blk(D, "us_macro") || [];
    const macroHtml = table(["Indicador", "Período", "Último", "Anterior", "Próximo"], macro.map((r) => [
      `${esc(r.nombre)}<span class="sub">${esc(r.tema)}</span>`, esc(r.periodo || "—"),
      `${fmt(r.valor, r.unidad === "miles" ? 0 : 1)}<span class="sub">${esc(r.unidad)}</span>`, fmt(r.anterior, r.unidad === "miles" ? 0 : 1), dmy(r.proximo)]));
    const L = lecturaEEUU();
    return `${L.lect}<div class="cols-2"><div class="view">${L.sem}${panel("Fed", fedHtml, { meta: meta(D, "fed") })}${L.real}</div>
      <div class="view">${panel("Treasuries", tsyHtml, { meta: meta(D, "treasuries") })}${L.mvf}</div></div>
      ${panel("Macro EE.UU.", macroHtml, { meta: meta(D, "us_macro") })}`;
  }

  // rendimiento relativo: cuánto le ganó (o perdió) un activo a su referencia en el mismo período
  const rel = (a, b) => (a == null || b == null ? null : ((1 + a / 100) / (1 + b / 100) - 1) * 100);
  const pct = (v, d = 2) => (v === null || v === undefined ? "—" : fmt(v, d) + "%");
  const merv = () => ((blk(P, "markets") || {}).argentina || [])[0] || {};

  function viewArMacro() {
    const dol = blk(P, "dolares") || {}, cot = dol.cotizaciones || [], br = dol.brechas || {};
    const ban = blk(D, "bandas"), bc = blk(D, "ar_bcra") || {}, rp = blk(D, "riesgo_pais") || {};
    const ip = blk(D, "ipc") || {}, em = blk(D, "emae") || {}, rem = blk(D, "rem") || {};
    const a3500 = byId(cot, "mayorista").venta;
    const dolHtml = table(["", "Compra", "Venta", "Día", "Sem", "Mes", "Año"], cot.filter((r) => r.id !== "oficial").map((r) => [esc(r.nombre), fmt(r.compra, 2), fmt(r.venta, 2), chg(r.d), chg(r.w), chg(r.m), chg(r.y)]))
      + `<h3>Brechas y banda</h3><dl class="kv"><dt>CCL / A3500</dt><dd>${pct(br.ccl_a3500, 1)}</dd><dt>MEP / A3500</dt><dd>${pct(br.mep_a3500, 1)}</dd><dt>CCL / MEP</dt><dd>${pct(br.ccl_mep, 1)}</dd>
        <dt>Piso / techo ${ban ? `(${dmy(ban.fecha)})` : ""}</dt><dd>${ban ? `${fmt(ban.piso, 2)} / ${fmt(ban.techo, 2)}` : "—"}</dd><dt>Distancia del A3500 al techo</dt><dd>${ban && a3500 ? pct((ban.techo / a3500 - 1) * 100, 1) : "—"}</dd></dl>`;
    const riesgoHtml = `<dl class="kv"><dt>Riesgo país (${dmy(rp.date)})</dt><dd>${fmt(rp.last, 0)} pb</dd><dt>Variación diaria</dt><dd>${chgInv(rp.d_pb, 0, " pb")} · ${chgInv(rp.d)}</dd>
      <dt>Variación semanal</dt><dd>${chgInv(rp.w)}</dd><dt>Variación mensual</dt><dd>${chgInv(rp.m)}</dd><dt>Variación anual</dt><dd>${chgInv(rp.y)}</dd></dl>
      <div class="note">Colores invertidos: verde = baja el riesgo país.</div>`;
    const bcraHtml = `<dl class="kv"><dt>Reservas brutas (${dmy(bc.reservas?.fecha)})</dt><dd>US$ ${fmt(bc.reservas?.valor, 0)} M · ${chg(bc.reservas?.m)} mes</dd>
      <dt>Compras del BCRA (${dmy(bc.compras?.fecha)})</dt><dd>US$ ${fmt(bc.compras?.valor, 0)} M</dd>
      <dt>Compras acumuladas en el mes</dt><dd>US$ ${fmt(bc.compras?.mes_acum, 0)} M</dd><dt>Compras acumuladas en el año</dt><dd>US$ ${fmt(bc.compras?.anio_acum, 0)} M</dd></dl>`;
    const tasasHtml = table(["", "TNA", "Fecha"], [["TAMAR bancos privados", bc.tamar], ["BADLAR bancos privados", bc.badlar], ["Plazo fijo 30 días", bc.plazo_fijo]].map(([n, v]) => [n, v ? pct(v.valor) : "—", dmy(v?.fecha)]));
    const actHtml = `<dl class="kv"><dt>IPC ${esc(ip.periodo || "")}</dt><dd>${pct(ip.mensual, 1)} m/m · ${pct(ip.interanual, 1)} i.a.</dd>
      <dt>EMAE ${esc(em.periodo || "")} (desest.)</dt><dd>${chg(em.mensual_desest, 1)} m/m · ${chg(em.interanual, 1)} i.a.</dd></dl>`
      + `<h3>Inflación esperada · REM ${esc(rem.informe || "")}</h3>` + table(["", ...(rem.ipc_mensual || []).map((r) => r.mes.slice(5, 7) + "/" + r.mes.slice(2, 4)), "12 meses"],
        rem.ipc_mensual ? [["IPC mensual (mediana)", ...rem.ipc_mensual.map((r) => pct(r.mediana, 1)), pct(rem.ipc_12m, 1)]] : [])
      + ((rem.tipo_cambio || []).length ? table(["", ...rem.tipo_cambio.map((r) => r.mes.slice(5, 7) + "/" + r.mes.slice(2, 4))], [["Dólar mayorista esperado", ...rem.tipo_cambio.map((r) => fmt(r.mediana, 0))]]) : "");
    return `<div class="cols-2"><div class="view">${panel("Dólares", dolHtml, { lead: true, meta: meta(P, "dolares") })}${panel("Riesgo país", riesgoHtml, { meta: meta(D, "riesgo_pais") })}</div>
      <div class="view">${panel("BCRA", bcraHtml, { meta: meta(D, "ar_bcra") })}${panel("Tasas de referencia", tasasHtml, { meta: meta(D, "ar_bcra") })}${panel("Inflación y actividad", actHtml, { meta: meta(D, "rem") })}</div></div>`;
  }

  // Tabla estilo bonistas para bonos en dólares
  const BH = ["Ticker", "Precio", "Dif", "TIR", "TNA", "MD", "Vol (M)", "Paridad", "VT", "Próx. pago", "Días vto."];
  const bRow = (r) => [r.ticker, fmt(r.usd, 2), chg(r.d), pct(r.tir, 1), pct(r.tna, 1), fmt(r.dur_mod, 2), fmt(r.vol, 1), pct(r.paridad, 1), fmt(r.vt, 2),
    r.dias_prox != null ? `${r.dias_prox} d<span class="sub">${fmt(r.monto_prox, 2)}</span>` : "—", r.dias_vto ?? "—"];

  function viewArUSD() {
    const arm = blk(P, "ar_market") || {}, sob = arm.soberanos || [], bop = arm.bopreal || [];
    const byMd = (a) => [...a].sort((x, y) => (x.dur_mod ?? 99) - (y.dur_mod ?? 99));
    const ny = byMd(sob.filter((r) => r.ley === "NY")), ar = byMd(sob.filter((r) => r.ley === "Local"));
    const m = meta(P, "ar_market");
    const tablas = panel("Bonos USD · Ley Nueva York", table(BH, ny.map(bRow)), { lead: true, meta: m })
      + panel("Bonos USD · Ley Argentina", table(BH, ar.map(bRow)), { meta: m });
    const grafico = panel("Curva en dólares MEP", curve([
        { name: "Ley Nueva York", cls: "s1", fit: true, points: ny.filter((r) => r.tir != null).map((r) => ({ x: r.dur_mod, y: r.tir, label: r.ticker })) },
        { name: "Ley Argentina", cls: "s2", fit: true, points: ar.filter((r) => r.tir != null).map((r) => ({ x: r.dur_mod, y: r.tir, label: r.ticker })) }],
        { xlabel: "Duration modificada (años)", ylabel: "TIR %", title: "Curva de bonos en dólares" })
      + `<div class="note">Precio por 100 VN en dólares MEP, liquidación ${dmy(arm.liquidacion)}. Línea: ajuste logarítmico de cada curva. Próx. pago: días y monto por 100 VN.</div>`, { src: "" });
    return `<div class="cols-split"><div class="view">${tablas}</div><div class="sticky">${grafico}</div></div>
      ${panel("BOPREAL", table(BH, bop.map(bRow)) + `<div class="note">Serie 1 (A a D): vencimiento 31/10/27. Serie 2028 (A8, B8): sin flujos cargados, se muestra solo el precio.</div>`, { meta: m })}`;
  }

  function viewArPesos() {
    const arm = blk(P, "ar_market") || {}, bc = blk(D, "ar_bcra") || {}, rem = blk(D, "rem") || {};
    const pf = (arm.pesos_fija || []).filter((r) => r.precio != null);
    const cer = (arm.cer_tamar || []).filter((r) => r.tipo === "CER"), tamar = (arm.cer_tamar || []).filter((r) => r.tipo === "TAMAR");
    const m = meta(P, "ar_market");
    const ref = `<div class="strip">${[["TAMAR", bc.tamar], ["BADLAR", bc.badlar], ["Plazo fijo 30 d", bc.plazo_fijo]].map(([n, v]) => `<span><b>${n}</b> ${v ? pct(v.valor) : "—"} TNA</span>`).join("")}
      ${(blk(P, "cauciones") || []).map((c) => `<span><b>Caución ${c.plazo} d</b> ${pct(c.tna)} TNA</span>`).join("")}
      <span><b>CER</b> ${fmt(bc.cer?.valor, 2)}</span><span><b>UVA</b> ${fmt(bc.uva?.valor, 2)}</span></div>`;
    const fija = panel("Tasa fija · LECAP y BONCAP", table(["Ticker", "Tipo", "Vto.", "Días", "Precio", "Dif", "Pago final", "TEM", "TNA", "TIREA"],
        pf.map((r) => [r.ticker, r.tipo, dmy(r.vto), r.dias, fmt(r.precio, 2), chg(r.d), fmt(r.pago_final, 2), pct(r.tem), pct(r.tna, 1), pct(r.tirea, 1)]))
      + (() => { const la = blk(D, "lecaps_auto") || {}, sinPago = pf.filter((r) => r.pago_final == null).map((r) => r.ticker);
          return `<div class="note">Las letras nuevas se suman solas: el pago final se calcula con la TEM y la fecha de emisión de la ficha de BYMA (o del resultado de licitación de Finanzas).${(la.automaticas || []).length ? ` Calculadas automáticamente: ${esc(la.automaticas.join(", "))}.` : ""}${sinPago.length ? ` Todavía sin condiciones publicadas: ${esc(sinPago.join(", "))} (se reintenta cada día).` : ""}</div>`; })(), { lead: true, meta: m });
    const cerT = panel("Bonos CER", table(["Ticker", "Vto.", "Días", "Precio", "Dif", "TIR real", "MD"],
        cer.map((r) => [r.ticker, dmy(r.vto), r.dias_vto ?? "—", fmt(r.precio, 2), chg(r.d), pct(r.tir), fmt(r.dur_mod, 2)]))
      + `<div class="note">TIR real: precio deflactado por CER (t−10 hábiles) sobre el CER inicial de cada bono.</div>`, { meta: m });
    const cerCurva = panel("Curva CER", curve([{ name: "TIR real", cls: "s2", fit: true, points: cer.filter((r) => r.tir != null).map((r) => ({ x: r.dur_mod, y: r.tir, label: r.ticker })) }],
        { xlabel: "Duration modificada (años)", ylabel: "TIR real %", title: "Curva CER" }), { src: "" });
    // inflación implícita vs REM (promedio de las medianas mensuales disponibles hasta el vencimiento)
    const remM = rem.ipc_mensual || [];
    const remHasta = (vto) => { const v = remM.filter((r) => r.mes <= vto.slice(0, 7)); return v.length ? v.reduce((a, r) => a + r.mediana, 0) / v.length : null; };
    const be = pf.filter((r) => r.inflacion_implicita != null);
    const beT = panel("Inflación implícita (tasa fija vs. CER)", table(["Letra", "Vto.", "TEM fija", "TEM real CER", "Inflación mensual implícita", "REM promedio"],
        be.map((r) => [r.ticker, dmy(r.vto), pct(r.tem), pct(r.tem_real_cer), `<b>${pct(r.inflacion_implicita)}</b>`, pct(remHasta(r.vto), 1)]))
      + `<div class="note">Inflación mensual que iguala el rendimiento de la letra a tasa fija con el de un bono CER del mismo plazo (curva CER interpolada). Si es mayor que el REM, el mercado espera más inflación que los analistas.</div>`, { meta: m });
    // dólar de equilibrio: el mayorista al vencimiento que iguala invertir en la letra con comprar dólares hoy
    const cot = (blk(P, "dolares") || {}).cotizaciones || [], ban = blk(D, "bandas"), ipm = (blk(D, "ipc") || {}).mensual;
    const a35 = byId(cot, "mayorista").venta;
    const techoAl = (dias) => (ban && ban.techo && ipm != null ? ban.techo * Math.pow(1 + ipm / 100, dias / 30.4) : null);
    const eqRows = a35 ? pf.filter((r) => r.pago_final && r.dias > 0).map((r) => {
      const eq = a35 * r.pago_final / r.precio, te = techoAl(r.dias);
      const vsTecho = te ? (eq / te - 1) * 100 : null;
      return [r.ticker, dmy(r.vto), r.dias, `<b>${fmt(eq, 0)}</b>`, chg((eq / a35 - 1) * 100, 1), te ? fmt(te, 0) : "—",
        vsTecho == null ? "—" : `<span class="${vsTecho > 0 ? "up" : "flat"}">${fmt(vsTecho, 1)}%</span>`];
    }) : [];
    const eqT = panel("Dólar de equilibrio (carry trade)", table(["Letra", "Vto.", "Días", "Dólar equil.", "Suba que tolera", "Techo est.", "Equil. vs. techo"], eqRows)
      + `<div class="note">Dólar mayorista al vencimiento que deja igual invertir en la letra que comprar dólares hoy (A3500 ${fmt(a35, 2)} × pago final ÷ precio). Si al vencimiento el dólar queda por debajo, la letra le ganó al dólar. Techo de banda estimado: el de hoy ajustado por la última inflación mensual (${pct(ipm, 1)}), según la regla vigente. Equilibrio vs. techo negativo = si el dólar llegara al techo, la letra perdería contra el dólar; en verde, gana igual.</div>`, { meta: m });
    // curva del dólar de equilibrio contra la banda cambiaria proyectada
    const pfEq = a35 ? pf.filter((r) => r.pago_final && r.dias > 0) : [];
    const maxD = Math.max(30, ...pfEq.map((r) => r.dias));
    const pasos = Array.from({ length: 13 }, (_, k) => Math.round(maxD * k / 12));
    // un solo gráfico: la curva de tasa fija (eje izquierdo) y, en pesos por dólar, el dólar de equilibrio de cada letra
    // contra el techo de la banda proyectado y el mayorista de hoy (eje derecho)
    const curvaPesos = panel("Curva de tasa fija y banda cambiaria", curvaDoble(
        [{ name: "TEM de cada letra", cls: "s1", fit: true, labels: true, points: pf.filter((r) => r.tem != null).map((r) => ({ x: r.dias, y: r.tem, label: r.ticker })) }],
        [{ name: "Dólar de equilibrio", cls: "s3", line: true, small: true, points: pfEq.map((r) => ({ x: r.dias, y: a35 * r.pago_final / r.precio, label: r.ticker })) },
         { name: "Techo de la banda", cls: "s2", line: true, nodots: true, points: pasos.map((d) => ({ x: d, y: techoAl(d) })).filter((p) => p.y != null) },
         { name: "Mayorista hoy", cls: "ghost", line: true, ghost: true, nodots: true, points: a35 ? [{ x: 0, y: a35 }, { x: maxD, y: a35 }] : [] }],
        { xlabel: "Días al vencimiento", ylabel: "TEM %", ylabel2: "$ por US$", title: "Curva de tasa fija y banda cambiaria" })
      + `<div class="note">Eje izquierdo: TEM de cada letra. Eje derecho: dólar de equilibrio (el mayorista al vencimiento que empata la letra con comprar dólares hoy) contra el techo de la banda estimado. Mientras el dólar termine por debajo de la línea verde, la letra le gana al dólar.</div>`, { src: "" });
    const cau = blk(P, "cauciones") || [];
    const cauT = panel("Cauciones en pesos", table(["Plazo", "TNA", "Día", "TEM", "TEA"],
        cau.map((c) => [`${c.plazo} día${c.plazo > 1 ? "s" : ""}`, pct(c.tna), chg(c.d_pb, 0, " pb"), pct(c.tem), pct(c.tea, 1)]))
      + `<div class="note">Tasa colocadora de BYMA. TEM y TEA: renovando la caución al mismo plazo y tasa. Sirve para comparar contra la LECAP más corta.</div>`, { meta: meta(P, "cauciones") });
    const tam = panel("TAMAR", table(["Ticker", "Precio", "Dif"], tamar.map((r) => [r.ticker, fmt(r.precio, 2), chg(r.d)])), { meta: m });
    return `${ref}<div class="cols-split"><div class="view">${fija}${eqT}</div><div class="sticky view">${curvaPesos}${cauT}</div></div>
      <div class="cols-split"><div class="view">${cerT}</div><div class="sticky">${cerCurva}</div></div>
      <div class="cols-split"><div class="view">${beT}</div><div>${tam}</div></div>`;
  }

  function viewArAcciones() {
    const arm = blk(P, "ar_market") || {}, mk = blk(P, "markets") || {}, cot = (blk(P, "dolares") || {}).cotizaciones || [];
    const mv = merv(), ccl = byId(cot, "contadoconliqui").venta;
    const m = meta(P, "ar_market");
    const head = `<div class="strip"><span><b>Merval</b> ${fmt(mv.last, 0)} ${chg(mv.d)}</span><span><b>Merval en USD (CCL)</b> ${mv.last && ccl ? fmt(mv.last / ccl, 0) : "—"}</span>
      <span><b>Mes</b> ${chg(mv.m)}</span><span><b>Año</b> ${chg(mv.y)}</span></div>`;
    const pl = arm.panel_lider || [], secs = arm.sectores || {};
    const secDe = (t) => Object.keys(secs).find((k) => secs[k].includes(t));
    // referencia de sector: promedio de los demás papeles del mismo sector (sin contar al propio)
    const promSector = (t, k) => { const s = secDe(t); if (!s || s === "Otros") return null; const v = pl.filter((r) => r.ticker !== t && secs[s].includes(r.ticker) && r[k] != null).map((r) => r[k]); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
    const panelT = panel("Panel líder", table(["Ticker", "Sector", "Precio", "Día", "Sem", "Mes", "Año", "vs. Merval (mes)", "vs. sector (mes)", "vs. Merval (año)"],
        pl.map((r) => [r.ticker, `<span class="na">${esc(secDe(r.ticker) || "—")}</span>`, fmt(r.precio, 2), chg(r.d), chg(r.w), chg(r.m), chg(r.y),
          chg(rel(r.m, mv.m)), chg(rel(r.m, promSector(r.ticker, "m"))), chg(rel(r.y, mv.y))]), [1])
      + `<div class="note">"vs." = cuánto le ganó (verde) o perdió (rojo) cada acción a su referencia en el período, en pesos. Sector: promedio simple de los otros papeles del panel del mismo sector.</div>`, { lead: true, meta: m });
    const adrs = panel("ADRs en Nueva York", table(["", "USD", "Día", "Sem", "Mes", "Año"], priceRows(mk.adrs, ["d", "w", "m", "y"])), { meta: meta(P, "markets") });
    const ced = panel("CEDEARs", table(["Ticker", "Precio", "Día", "Mes", "MEP implícito", "CCL implícito"], (arm.cedears || []).map((r) => [r.ticker, fmt(r.precio, 2), chg(r.d), chg(r.m), fmt(r.mep, 2), fmt(r.ccl, 2)])), { meta: m });
    return `${head}${panelT}<div class="cols-2">${adrs}${ced}</div>`;
  }

  function viewEmpresas() {
    const mk = blk(P, "markets") || {}, cap = blk(D, "megacaps_info") || {}, earn = blk(D, "earnings") || [];
    const cm = (blk(P, "ar_market") || {}).cedears_mega || {};
    const prox = (id) => { const e = earn.filter((r) => r.ticker === id).sort((a, b) => (a.fecha < b.fecha ? -1 : 1))[0]; return e ? dmy(e.fecha) : "—"; };
    const spx = (mk.indices_eeuu || []).find((x) => x.id === "SPX") || {};
    const secs = Object.fromEntries((mk.sectores || []).map((x) => [x.id, x]));
    const rows = (arr) => [...(arr || [])].sort((a, b) => (cap[b.id] ?? 0) - (cap[a.id] ?? 0)).map((r) => {
      const sx = secs[r.sector] || {};
      const c = r.cedear ? cm[r.cedear] : null;
      return [`${esc(r.nombre)}<span class="sub">${esc(r.id)}</span>`, cap[r.id] != null ? fmt(cap[r.id], 0) : "—", fmt(r.last, 2), chg(r.d), chg(r.m), chg(r.y),
        chg(rel(r.m, spx.m)), chg(rel(r.y, spx.y)), `${chg(rel(r.y, sx.y))}<span class="sub" title="${esc(sx.nombre || "")}">${esc(sx.id || "")}</span>`, chg(r.dd52, 1), prox(r.id),
        c ? `${fmt(c.ccl, 0)}` : (r.cedear ? "—" : `<span class="na">sin CEDEAR</span>`)];
    });
    const H = ["Empresa", "Cap. US$ mM", "Precio US$", "Día", "Mes", "Año", "vs S&P mes", "vs S&P año", "vs sector año", "vs máx 52s", "Balance", "CCL CEDEAR"];
    const m = meta(P, "markets");
    return `${panel("Grandes del S&P 500", table(H, rows(mk.megacaps_eeuu)), { lead: true, meta: m })}
      ${panel("Gigantes fuera de EE.UU.", table(H, rows(mk.megacaps_global)) + `<div class="note">Precios en US$ de su ADR o cotización en EE.UU. (Saudi Aramco en Riad, convertida a US$). Capitalización: cierre del día anterior. Cap.: capitalización en miles de millones de US$. Ordenadas por capitalización; hacé clic en un encabezado para reordenar. "vs." = cuánto le ganó (verde) o perdió (rojo) al S&P 500 o al ETF de su sector en EE.UU. (XLK tecnología, XLC comunicaciones, XLY consumo discrecional, XLP consumo básico, XLF financiero, XLV salud, XLE energía, XLB materiales, XLI industria).</div>`, { meta: m })}
      ${panel("Tu selección", table(H, rows(mk.empresas_seleccion)) + `<div class="note">Empresas elegidas a mano (Argentina, Brasil, tecno). Se editan en config/instruments.json → empresas_seleccion.</div>`, { meta: m })}`;
  }

  // Bolsas abiertas o cerradas (lunes a viernes, sin contemplar feriados)
  const BOLSAS = [["Nueva York", "America/New_York", 570, 960], ["Londres", "Europe/London", 480, 990], ["Fráncfort", "Europe/Berlin", 540, 1050],
    ["Tokio", "Asia/Tokyo", 540, 930], ["Hong Kong", "Asia/Hong_Kong", 570, 960], ["San Pablo", "America/Sao_Paulo", 600, 1020], ["BYMA", "America/Argentina/Buenos_Aires", 660, 1020]];
  function bolsas() {
    return `<div class="strip">${BOLSAS.map(([n, tz, a, b]) => {
      const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(new Date()).map((x) => [x.type, x.value]));
      const mins = (+p.hour % 24) * 60 + +p.minute, open = !["Sat", "Sun"].includes(p.weekday) && mins >= a && mins < b;
      return `<span class="${open ? "abierta" : "cerrada"}"><i></i>${n} ${p.hour}:${p.minute}</span>`;
    }).join("")}</div>`;
  }

  function viewMercados() {
    const mk = blk(P, "markets") || {};
    const head = ["", "Último", ...Object.values(VARS)];
    const g = (k) => table(head, priceRows(mk[k], Object.keys(VARS)));
    const m = meta(P, "markets");
    return `${bolsas()}<div class="cols-2">
      <div class="view">${panel("EE.UU.", g("indices_eeuu") + `<h3>Futuros</h3>` + g("futuros") + `<h3>Volatilidad</h3>` + g("volatilidad"), { lead: true, meta: m })}${panel("Sectores del S&P 500", g("sectores"), { meta: m })}${panel("Bonos globales (ETFs)", g("bonos_etf"), { meta: m })}</div>
      <div class="view">${panel("Resto del mundo", g("indices_mundo"), { meta: m })}${panel("Monedas", g("monedas"), { meta: m })}${panel("Commodities y cripto", g("commodities") + `<h3>Cripto</h3>` + g("cripto"), { meta: m })}</div></div>`;
  }

  function upcoming() {
    const now = new Date().toISOString();
    const ev = [];
    for (const r of blk(D, "calendar_us") || []) if (new Date(r.fecha) >= new Date()) ev.push({ t: r.fecha, txt: `EE.UU. · ${r.evento}${r.esperado ? ` · esp. ${r.esperado}` : ""}${r.previo ? ` · prev. ${r.previo}` : ""}`, imp: r.impacto });
    for (const r of blk(D, "calendar_ar") || []) ev.push({ t: `${r.fecha}T${r.hora || "00:00"}:00-03:00`, txt: `Argentina · ${r.evento}`, imp: "High" });
    for (const f of (blk(D, "fed") || {}).fomc || []) ev.push({ t: `${f}T15:00:00-03:00`, txt: "Fed · Decisión FOMC", imp: "High" });
    for (const b of ((blk(D, "calendar_intl") || {}).bancos || [])) ev.push({ t: `${b.fecha}T${b.hora || "08:00"}:00-03:00`, txt: `${b.banco} · Decisión de tasa`, imp: "High" });
    return ev.filter((e) => new Date(e.t) >= (() => { const t0 = new Date(); t0.setHours(0, 0, 0, 0); return t0; })()).sort((a, b) => (new Date(a.t) - new Date(b.t)));
  }
  function eventsList(ev) {
    return ev.length ? `<ul class="events">${ev.map((e) => `<li><span class="t">${hhmm(e.t)}</span><span class="imp-${esc(e.imp)}">${esc(e.txt)}</span></li>`).join("")}</ul>` : `<div class="empty">Sin eventos cargados.</div>`;
  }
  function mergedNews() { const n = blk(P, "news") || {}; return [...(n.eeuu || []), ...(n.argentina || [])].sort((a, b) => ((a.hora || "") < (b.hora || "") ? 1 : -1)); }
  function newsList(items) {
    return items.length ? `<ul class="news">${items.map((n) => `<li><span class="t">${hhmm(n.hora)}</span><span><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.titulo)}</a> <span class="f">${esc(n.fuente)}</span></span></li>`).join("")}</ul>` : `<div class="empty">Sin titulares.</div>`;
  }

  /* ---------- Calendario unificado: una sola agenda, cada tipo de evento con su color ---------- */
  const CATS = { us: "Datos EE.UU.", fed: "Fed", ar: "Argentina", bc: "Bancos centrales", intl: "Datos internacionales", earn: "Balances" };
  let calOff = new Set();
  try { calOff = new Set(JSON.parse(localStorage.getItem("calOff") || "[]")); } catch {}
  function agenda() {
    const hoy = new Date(); hoy.setHours(0, 0, 0, 0);
    const ev = [];
    const imp = (x) => (x === "High" ? "alto" : x === "Medium" ? "medio" : "");
    for (const r of blk(D, "calendar_us") || []) ev.push({ cat: "us", t: r.fecha, hora: true, txt: r.evento, det: [r.esperado && `esp. ${r.esperado}`, r.previo && `prev. ${r.previo}`].filter(Boolean).join(" · "), imp: imp(r.impacto) });
    for (const f of (blk(D, "fed") || {}).fomc || []) ev.push({ cat: "fed", t: `${f}T15:00:00-03:00`, hora: true, txt: "Decisión de tasas (FOMC)", det: "", imp: "alto" });
    for (const r of blk(D, "calendar_ar") || []) ev.push({ cat: "ar", t: `${r.fecha}T${r.hora || "00:00"}:00-03:00`, hora: !!r.hora, txt: r.evento, det: "", imp: "alto" });
    const intl = blk(D, "calendar_intl") || {};
    for (const r of intl.bancos || []) ev.push({ cat: "bc", t: `${r.fecha}T${r.hora || "12:00"}:00-03:00`, hora: !!r.hora, txt: `${r.banco} · decisión de tasa`, det: "", imp: "alto" });
    for (const r of intl.datos_semana || []) ev.push({ cat: "intl", t: r.fecha, hora: true, txt: `${r.pais} · ${r.evento}`, det: [r.esperado && `esp. ${r.esperado}`, r.previo && `prev. ${r.previo}`].filter(Boolean).join(" · "), imp: "alto" });
    for (const r of blk(D, "earnings") || []) ev.push({ cat: "earn", t: `${r.fecha}T12:00:00-03:00`, hora: false, txt: r.ticker, det: [r.hora, r.eps_estimado != null && `EPS est. ${fmt(r.eps_estimado, 2)}`].filter(Boolean).join(" · "), imp: "" });
    const fin = new Date(hoy.getTime() + 60 * 864e5);
    return ev.filter((e) => new Date(e.t) >= hoy && new Date(e.t) < fin).sort((x, y) => new Date(x.t) - new Date(y.t));
  }
  const diaAR = (iso) => new Date(iso).toLocaleDateString("es-AR", { weekday: "long", day: "2-digit", month: "2-digit", timeZone: "America/Argentina/Buenos_Aires" });
  const horaAR = (iso) => new Date(iso).toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "America/Argentina/Buenos_Aires" });
  function viewCalendario() {
    const ev = agenda();
    const cuenta = Object.fromEntries(Object.keys(CATS).map((k) => [k, ev.filter((e) => e.cat === k).length]));
    const filtros = `<div class="cal-filtros">${Object.entries(CATS).map(([k, n]) => `<button class="cal-f cat-${k}" data-cat="${k}" aria-pressed="${!calOff.has(k)}"><i></i>${n} <span>${cuenta[k]}</span></button>`).join("")}</div>`;
    const vis = ev.filter((e) => !calOff.has(e.cat));
    let html = "", dia = "";
    for (const e of vis) {
      const d = diaAR(e.t);
      if (d !== dia) { if (dia) html += "</ul>"; html += `<h3 class="cal-dia">${esc(d)}</h3><ul class="cal">`; dia = d; }
      html += `<li class="cat-${e.cat}"><span class="t">${e.hora ? horaAR(e.t) : ""}</span><span class="tag"><i></i>${esc(CATS[e.cat])}</span>
        <span class="e${e.imp === "alto" ? " alto" : ""}">${esc(e.txt)}</span><span class="d">${esc(e.det || "")}</span></li>`;
    }
    html = html ? html + "</ul>" : `<div class="empty">No hay eventos con los filtros elegidos.</div>`;
    const n = blk(P, "news") || {};
    return `${panel("Calendario", filtros + html + `<div class="note">Hora de Argentina. Datos de EE.UU. e internacionales: semana en curso (Forex Factory). Bancos centrales, Fed e INDEC: fechas oficiales. Balances: Finnhub. Se muestran los próximos 60 días. Tocá un tipo para ocultarlo o mostrarlo.</div>`, { lead: true, src: "" })}
      <div class="cols-2">${panel("Noticias EE.UU.", newsList(n.eeuu || []), { meta: meta(P, "news") })}${panel("Noticias Argentina", newsList(n.argentina || []), { meta: meta(P, "news") })}</div>`;
  }

  const VIEWS = { resumen: viewResumen, eeuu: viewEEUU, ar_macro: viewArMacro, ar_usd: viewArUSD, ar_pesos: viewArPesos, ar_acciones: viewArAcciones,
    mercados: viewMercados, empresas: viewEmpresas, calendario: viewCalendario };
  let current = "resumen";

  function render() {
    try { $("#view").innerHTML = VIEWS[current](); }
    catch (e) { $("#view").innerHTML = `<div class="empty">Error al dibujar la pestaña: ${esc(e.message)}</div>`; console.error(e); }
    document.querySelectorAll("nav.tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.v === current));
    const stale = [...Object.entries(P), ...Object.entries(D)].filter(([k, v]) => v && v.stale).map(([k]) => k);
    $("#status").innerHTML = `<span>Precios ${hhmm(P.generated)}</span><span>Diario ${hhmm(D.generated)}</span>${stale.length ? `<span class="bad" title="${esc(stale.join(", "))}">${stale.length} fuente(s) con dato viejo</span>` : ""}`;
  }

  async function load() {
    if (window.__SAMPLE__) { P = window.__SAMPLE__.prices; D = window.__SAMPLE__.daily; $("#sample").hidden = false; return render(); }
    const bust = `?t=${Date.now()}`;
    const get = (u) => fetch(u + bust).then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
    [P, D] = await Promise.all([get("data/prices.json"), get("data/daily.json")]);
    render();
  }

  // ordenar tablas al hacer clic en el encabezado
  const parseCell = (t) => { const s = t.replace(/\s.*$/, "").replace(/\./g, "").replace(",", ".").replace(/[^\d.+-]/g, ""); const n = parseFloat(s); return Number.isNaN(n) ? t : n; };
  document.addEventListener("click", (e) => {
    const th = e.target.closest("thead th"); if (!th) return;
    const table_ = th.closest("table"), idx = [...th.parentNode.children].indexOf(th), tb = table_.tBodies[0];
    const dir = th.dataset.dir === "asc" ? "desc" : "asc";
    table_.querySelectorAll("th").forEach((x) => { delete x.dataset.dir; });
    th.dataset.dir = dir;
    const rows = [...tb.rows].sort((a, b) => {
      const va = parseCell(a.cells[idx]?.textContent.trim() || ""), vb = parseCell(b.cells[idx]?.textContent.trim() || "");
      const r = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
      return dir === "asc" ? r : -r;
    });
    rows.forEach((r) => tb.appendChild(r));
  });
  document.addEventListener("click", (e) => {
    const f = e.target.closest(".cal-f"); if (!f) return;
    const k = f.dataset.cat; if (calOff.has(k)) calOff.delete(k); else calOff.add(k);
    try { localStorage.setItem("calOff", JSON.stringify([...calOff])); } catch {}
    render();
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("nav.tabs button"); if (!b) return;
    current = b.dataset.v; try { history.replaceState(null, "", "#" + current); } catch {}
    render();
  });
  const h = location.hash.slice(1); if (VIEWS[h]) current = h;
  load();
  setInterval(load, 5 * 60 * 1000);
})();
