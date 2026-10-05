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
  // papeles que no operaron en la rueda: ticker con etiqueta "s/op" y fila atenuada
  const tk = (r) => `${esc(r.ticker)}${r.opero === false ? `<span class="sinop-tag" title="No operó en la rueda de hoy: el precio es el último conocido">s/op</span>` : ""}`;
  const fila = (r, celdas) => { if (r.opero === false) celdas.cls = "sinop"; if (r.flujos || r.cond || r.tipo === "TAMAR" || r.tipo === "Dólar linked") { celdas.tk = r.ticker; celdas.cls = `${celdas.cls || ""} clic`.trim(); } return celdas; };
  const table = (head, rows, left = []) => rows.length
    ? `<div class="scroll"><table><thead><tr>${head.map((h, i) => `<th${left.includes(i) ? ' class="txt"' : ""}>${h}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr${r.cls ? ` class="${r.cls}"` : ""}${r.tk ? ` data-tk="${esc(r.tk)}" title="Ver ficha"` : ""}${r.emp ? ` data-emp="${esc(r.emp)}" title="Ver ficha"` : ""}${r.acc ? ` data-acc="${esc(r.acc)}" title="Ver ficha"` : ""}>${r.map((c, i) => `<td${left.includes(i) ? ' class="txt"' : ""}>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
    : `<div class="empty">Sin datos todavía.</div>`;
  const byId = (arr, id) => (arr || []).find((x) => x.id === id) || {};

  // filas de precio: nombre, último, variaciones elegidas
  const priceRows = (items, cols) => (items || []).map((i) => [
    `${esc(i.nombre)}${i.unidad ? `<span class="sub">${esc(i.unidad)}</span>` : ""}`,
    fmt(i.last, dec(i.last)), ...cols.map((c) => chg(i[c])),
  ]);
  const VARS = { d: "Día", w: "Sem", m: "Mes", y: "Año" };

  /* ---------- Gráfico de dispersión/curva (SVG propio) ---------- */
  // Ubica etiquetas sin que se pisen: prueba arriba, abajo y más lejos; si no entra a la derecha, la pone a la izquierda.
  function etiquetador(xmax) {
    const cajas = [];
    const choca = (b) => cajas.some((c) => b.x < c.x + c.w && b.x + b.w > c.x && b.y < c.y + c.h && b.y + b.h > c.y);
    return (x, y, txt) => {
      const w = txt.length * 6.4 + 2, h = 11;
      for (const dy of [-7, 14, -19, 26, -31, 38]) for (const izq of [false, true]) {
        const bx = izq ? x - 5 - w : x + 5;
        if (!izq && bx + w > xmax) continue;
        const b = { x: bx, y: y + dy - 9, w, h };
        if (!choca(b)) { cajas.push(b); return `<text class="lbl" x="${izq ? x - 5 : x + 5}" y="${y + dy}" ${izq ? 'text-anchor="end"' : ""}>${esc(txt)}</text>`; }
      }
      return "";  // si no hay lugar, se omite la etiqueta (el valor sigue en el tooltip del punto)
    };
  }
  // ajuste logarítmico y = a + b·ln(x) con los papeles que operaron (los "s/op" no deforman la curva)
  function ajusteLog(ps) {
    const v = ps.filter((p) => !p.sinop);
    if (v.length < 3) return null;
    const xs = v.map((p) => Math.log(Math.max(p.x, 0.05))), ys = v.map((p) => p.y), n = xs.length;
    const mx = xs.reduce((a, b) => a + b) / n, my = ys.reduce((a, b) => a + b) / n;
    const b = xs.reduce((acc, x, i) => acc + (x - mx) * (ys[i] - my), 0) / (xs.reduce((acc, x) => acc + (x - mx) ** 2, 0) || 1);
    return { f: (x) => my - b * mx + b * Math.log(Math.max(x, 0.05)), xa: ps[0].x, xb: ps[ps.length - 1].x };
  }
  const punto = (cls, cx, cy, r, sinop, tip) => `<circle class="${cls}" cx="${cx}" cy="${cy}" r="${r}" ${sinop ? 'fill-opacity="0" stroke-width="1.5"' : ""}><title>${esc(tip)}${sinop ? " · no operó hoy" : ""}</title></circle>`;

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
    const etiquetas = [];
    series.forEach((s) => {
      const ps = s.points.filter((p) => p.x != null && p.y != null).sort((a, b) => a.x - b.x);
      if (s.fit) {
        const aj = ajusteLog(ps);
        if (aj) g += `<polyline class="${s.cls}" fill="none" stroke-width="2" stroke-opacity="0.55" points="${Array.from({ length: 40 }, (_, k) => { const x = aj.xa + (aj.xb - aj.xa) * k / 39; return `${X(x)},${Y(aj.f(x))}`; }).join(" ")}"/>`;
      }
      if (s.line && ps.length > 1) g += `<polyline class="${s.cls}" fill="none" stroke-width="${s.ghost ? 1 : 2}" ${s.ghost ? 'stroke-dasharray="4 4"' : ""} points="${ps.map((p) => `${X(p.x)},${Y(p.y)}`).join(" ")}"/>`;
      if (!s.nodots) g += ps.map((p) => punto(s.cls, X(p.x), Y(p.y), s.ghost ? 2.5 : 3.5, p.sinop, `${p.label || ""} ${fmt(p.y, o.tdec ?? 2)}${o.ysuf ?? "%"}`)).join("");
      if (!s.ghost && !s.nolabel) ps.forEach((p) => { if (p.label) etiquetas.push([X(p.x), Y(p.y), p.label]); });
    });
    const pon = etiquetador(W - 2);
    g += etiquetas.sort((a, b) => a[0] - b[0]).map(([x, y, t]) => pon(x, y, t)).join("");
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
    const etiquetas = [];
    const dibujar = (s, Y, suf, dec) => {
      const ps = s.points.filter((p) => p.x != null && p.y != null).sort((a, b) => a.x - b.x);
      let h = "";
      if (s.fit) {
        const aj = ajusteLog(ps);
        if (aj) h += `<polyline class="${s.cls}" fill="none" stroke-width="2" stroke-opacity="0.55" points="${Array.from({ length: 40 }, (_, k) => { const x = aj.xa + (aj.xb - aj.xa) * k / 39; return `${X(x)},${Y(aj.f(x))}`; }).join(" ")}"/>`;
      }
      if (s.line && ps.length > 1) h += `<polyline class="${s.cls}" fill="none" stroke-width="${s.ghost ? 1 : 2}" ${s.ghost ? 'stroke-dasharray="4 4"' : ""} points="${ps.map((p) => `${X(p.x)},${Y(p.y)}`).join(" ")}"/>`;
      if (!s.nodots) h += ps.map((p) => punto(s.cls, X(p.x), Y(p.y), s.small ? 2.5 : 3.5, p.sinop, `${p.label || ""} ${fmt(p.y, dec)}${suf}`)).join("");
      if (s.labels) ps.forEach((p) => { if (p.label) etiquetas.push([X(p.x), Y(p.y), p.label]); });
      return h;
    };
    izq.forEach((s) => { g += dibujar(s, YA, "%", 2); });
    der.forEach((s) => { g += dibujar(s, YB, "", 0); });
    const pon = etiquetador(W - R);
    g += etiquetas.sort((a, b) => a[0] - b[0]).map(([x, y, t]) => pon(x, y, t)).join("");
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
    const fu = blk(D, "futuros_dolar") || {};
    const futHtml = table(["Contrato", "Vto.", "Días", "Precio", "Var. día", "Tasa efectiva", "TNA", "TEA", "Int. abierto"],
        (fu.contratos || []).map((c) => [esc(c.especie), dmy(c.vto), c.dias, fmt(c.precio, 2), chg(c.var), pct(c.tasa_efectiva), pct(c.tna), pct(c.tea), fmt(c.interes_abierto, 0)]))
      + `<div class="note">Cierres oficiales de A3 (ex Matba-Rofex). Tasas implícitas contra el mayorista A3500 ${fmt(fu.spot, 2)}: efectiva = futuro ÷ mayorista − 1; TNA en base 365.</div>`;
    return `<div class="cols-2"><div class="view">${panel("Dólares", dolHtml, { lead: true, meta: meta(P, "dolares") })}${panel("Riesgo país", riesgoHtml, { meta: meta(D, "riesgo_pais") })}</div>
      <div class="view">${panel("BCRA", bcraHtml, { meta: meta(D, "ar_bcra") })}${panel("Tasas de referencia", tasasHtml, { meta: meta(D, "ar_bcra") })}${panel("Inflación y actividad", actHtml, { meta: meta(D, "rem") })}</div></div>
      ${panel("Dólar futuro", futHtml, { meta: meta(D, "futuros_dolar") })}`;
  }

  // Tabla estilo bonistas para bonos en dólares
  const BH = ["Ticker", "Precio", "Dif", "TIR", "TNA", "MD", "Vol (M)", "Paridad", "VT", "Próx. pago", "Días vto."];
  const bRow = (r) => fila(r, [tk(r), fmt(r.usd, 2), chg(r.d), pct(r.tir, 1), pct(r.tna, 1), fmt(r.dur_mod, 2), fmt(r.vol, 1), pct(r.paridad, 1), fmt(r.vt, 2),
    r.dias_prox != null ? `${r.dias_prox} d<span class="sub">${fmt(r.monto_prox, 2)}</span>` : "—", r.dias_vto ?? "—"]);

  function viewArUSD() {
    const arm = blk(P, "ar_market") || {}, sob = arm.soberanos || [], bop = arm.bopreal || [];
    const byMd = (a) => [...a].sort((x, y) => (x.dur_mod ?? 99) - (y.dur_mod ?? 99));
    const ny = byMd(sob.filter((r) => r.ley === "NY")), ar = byMd(sob.filter((r) => r.ley === "Local"));
    const m = meta(P, "ar_market");
    const tablas = panel("Bonos USD · Ley Nueva York", table(BH, ny.map(bRow)), { lead: true, meta: m })
      + panel("Bonos USD · Ley Argentina", table(BH, ar.map(bRow)), { meta: m });
    const grafico = panel("Curva en dólares MEP", curve([
        { name: "Ley Nueva York", cls: "s1", fit: true, points: ny.filter((r) => r.tir != null).map((r) => ({ x: r.dur_mod, y: r.tir, label: r.ticker, sinop: r.opero === false })) },
        { name: "Ley Argentina", cls: "s2", fit: true, points: ar.filter((r) => r.tir != null).map((r) => ({ x: r.dur_mod, y: r.tir, label: r.ticker, sinop: r.opero === false })) }],
        { xlabel: "Duration modificada (años)", ylabel: "TIR %", title: "Curva de bonos en dólares" })
      + `<div class="note">Precio por 100 VN en dólares MEP, liquidación ${dmy(arm.liquidacion)}. Línea: ajuste logarítmico de cada curva. Próx. pago: días y monto por 100 VN.</div>`, { src: "" });
    return `${rueda()}<div class="cols-split"><div class="view">${tablas}</div><div class="sticky">${grafico}</div></div>
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
        pf.map((r) => fila(r, [tk(r), r.tipo, dmy(r.vto), r.dias, fmt(r.precio, 2), chg(r.d), fmt(r.pago_final, 2), pct(r.tem), pct(r.tna, 1), pct(r.tirea, 1)])))
      + (() => { const la = blk(D, "lecaps_auto") || {}, sinPago = pf.filter((r) => r.pago_final == null).map((r) => r.ticker);
          return `<div class="note">Las letras nuevas se suman solas: el pago final se calcula con la TEM y la fecha de emisión de la ficha de BYMA (o del resultado de licitación de Finanzas).${(la.automaticas || []).length ? ` Calculadas automáticamente: ${esc(la.automaticas.join(", "))}.` : ""}${sinPago.length ? ` Todavía sin condiciones publicadas: ${esc(sinPago.join(", "))} (se reintenta cada día).` : ""}</div>`; })(), { lead: true, meta: m });
    const cerT = panel("Bonos CER", table(["Ticker", "Vto.", "Días", "Precio", "Dif", "TIR real", "MD"],
        cer.map((r) => fila(r, [tk(r) + (r.auto ? `<span class="sub" title="Dado de alta automáticamente con la ficha de BYMA">auto</span>` : ""), dmy(r.vto), r.dias_vto ?? "—", fmt(r.precio, 2), chg(r.d), pct(r.tir), fmt(r.dur_mod, 2)])))
      + `<div class="note">TIR real: precio deflactado por CER (t−10 hábiles) sobre el CER inicial de cada bono.</div>`, { meta: m });
    const cerCurva = panel("Curva CER", curve([{ name: "TIR real", cls: "s2", fit: true, points: cer.filter((r) => r.tir != null).map((r) => ({ x: r.dur_mod, y: r.tir, label: r.ticker, sinop: r.opero === false })) }],
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
    // dólar futuro interpolado al vencimiento de cada letra (lineal en días entre contratos)
    const fut = ((blk(D, "futuros_dolar") || {}).contratos || []).filter((c) => c.precio && c.vto);
    const hoyMs = Date.now();
    const futPts = fut.map((c) => ({ x: Math.round((new Date(c.vto + "T12:00:00-03:00") - hoyMs) / 864e5), y: c.precio, label: c.especie })).filter((p) => p.x > 0);
    const futAl = (d) => { for (let i = 0; i < futPts.length - 1; i++) { const a = futPts[i], b = futPts[i + 1]; if (d >= a.x && d <= b.x) return a.y + (b.y - a.y) * (d - a.x) / (b.x - a.x); } return null; };
    const eqRows = a35 ? pf.filter((r) => r.pago_final && r.dias > 0).map((r) => {
      const eq = a35 * r.pago_final / r.precio, te = techoAl(r.dias), fu = futAl(r.dias);
      const vsTecho = te ? (eq / te - 1) * 100 : null;
      return [r.ticker, dmy(r.vto), r.dias, `<b>${fmt(eq, 0)}</b>`, chg((eq / a35 - 1) * 100, 1),
        fu ? `${fmt(fu, 0)}<span class="sub ${eq > fu ? "up" : "down"}">${eq > fu ? "letra gana" : "futuro gana"}</span>` : "—", te ? fmt(te, 0) : "—",
        vsTecho == null ? "—" : `<span class="${vsTecho > 0 ? "up" : "flat"}">${fmt(vsTecho, 1)}%</span>`];
    }) : [];
    const eqT = panel("Dólar de equilibrio (carry trade)", table(["Letra", "Vto.", "Días", "Dólar equil.", "Suba que tolera", "Futuro A3", "Techo est.", "Equil. vs. techo"], eqRows)
      + `<div class="note">Dólar mayorista al vencimiento que deja igual invertir en la letra que comprar dólares hoy (A3500 ${fmt(a35, 2)} × pago final ÷ precio). Si al vencimiento el dólar queda por debajo, la letra le ganó al dólar. Techo de banda estimado: el de hoy ajustado por la última inflación mensual (${pct(ipm, 1)}), según la regla vigente. Equilibrio vs. techo negativo = si el dólar llegara al techo, la letra perdería contra el dólar; en verde, gana igual. Futuro A3: dólar futuro interpolado al vencimiento de la letra; si el equilibrio es mayor, la letra rinde más que cubrirse con futuro.</div>`, { meta: m });
    // curva del dólar de equilibrio contra la banda cambiaria proyectada
    const pfEq = a35 ? pf.filter((r) => r.pago_final && r.dias > 0) : [];
    const maxD = Math.max(30, ...pfEq.map((r) => r.dias));
    const pasos = Array.from({ length: 13 }, (_, k) => Math.round(maxD * k / 12));
    // un solo gráfico: la curva de tasa fija (eje izquierdo) y, en pesos por dólar, el dólar de equilibrio de cada letra
    // contra el techo de la banda proyectado y el mayorista de hoy (eje derecho)
    const curvaPesos = panel("Curva de tasa fija y banda cambiaria", curvaDoble(
        [{ name: "TEM de cada letra", cls: "s1", fit: true, labels: true, points: pf.filter((r) => r.tem != null).map((r) => ({ x: r.dias, y: r.tem, label: r.ticker, sinop: r.opero === false })) }],
        [{ name: "Dólar de equilibrio", cls: "s3", line: true, small: true, points: pfEq.map((r) => ({ x: r.dias, y: a35 * r.pago_final / r.precio, label: r.ticker })) },
         { name: "Techo de la banda", cls: "s2", line: true, nodots: true, points: pasos.map((d) => ({ x: d, y: techoAl(d) })).filter((p) => p.y != null) },
         { name: "Dólar futuro A3", cls: "s4", line: true, small: true, points: futPts.filter((p) => p.x <= maxD * 1.05) },
         { name: "Mayorista hoy", cls: "ghost", line: true, ghost: true, nodots: true, points: a35 ? [{ x: 0, y: a35 }, { x: maxD, y: a35 }] : [] }],
        { xlabel: "Días al vencimiento", ylabel: "TEM %", ylabel2: "$ por US$", title: "Curva de tasa fija y banda cambiaria" })
      + `<div class="note">Eje izquierdo: TEM de cada letra. Eje derecho: dólar de equilibrio (el mayorista al vencimiento que empata la letra con comprar dólares hoy) contra el techo de la banda estimado. Mientras el dólar termine por debajo de la línea verde, la letra le gana al dólar.</div>`, { src: "" });
    const cau = blk(P, "cauciones") || [];
    const cauT = panel("Cauciones en pesos", table(["Plazo", "TNA", "Día", "TEM", "TEA"],
        cau.map((c) => [`${c.plazo} día${c.plazo > 1 ? "s" : ""}`, pct(c.tna), chg(c.d_pb, 0, " pb"), pct(c.tem), pct(c.tea, 1)]))
      + `<div class="note">Tasa colocadora de BYMA. TEM y TEA: renovando la caución al mismo plazo y tasa. Sirve para comparar contra la LECAP más corta.</div>`, { meta: meta(P, "cauciones") });
    // dólar linked: TIR en dólares y dólar implícito contra la tasa fija (a qué dólar empatan LECAP y dólar linked)
    const dlk = (arm.dolar_linked || []);
    const temAl = (d) => { const pts = pf.filter((r) => r.tem != null).sort((x, y) => x.dias - y.dias); if (!pts.length) return null;
      if (d <= pts[0].dias) return pts[0].tem; if (d >= pts[pts.length - 1].dias) return pts[pts.length - 1].tem;
      for (let i = 0; i < pts.length - 1; i++) if (d >= pts[i].dias && d <= pts[i + 1].dias) return pts[i].tem + (pts[i + 1].tem - pts[i].tem) * (d - pts[i].dias) / (pts[i + 1].dias - pts[i].dias); return null; };
    const dlT = panel("Dólar linked", dlk.length ? table(["Ticker", "Vto.", "Días", "Precio $", "Precio US$", "TIR en US$", "Dólar implícito", "Futuro A3"],
        dlk.map((r) => { const tf = temAl(r.dias), imp = a35 && r.precio_usd && tf != null ? a35 * Math.pow(1 + tf / 100, r.dias / 30) / (100 / r.precio_usd) : null, fu = futAl(r.dias);
          return fila(r, [tk(r), dmy(r.vto), r.dias, fmt(r.precio, 2), fmt(r.precio_usd, 2), pct(r.tir), imp ? `<b>${fmt(imp, 0)}</b>` : "—", fu ? fmt(fu, 0) : "—"]); }))
      + `<div class="note">Pagan en pesos el valor nominal en dólares al A3500 del vencimiento. TIR en US$: contra el A3500 de hoy (${fmt(a35, 2)}). Dólar implícito: el mayorista al vencimiento que empata el dólar linked con una LECAP del mismo plazo; si el dólar termina arriba, gana el dólar linked.</div>`
      : `<div class="empty">No hay letras dólar linked cotizando.</div>`, { meta: m });
    const lic = blk(D, "licitaciones_resultado") || [], ult = lic[0];
    const bill = (v) => (v == null ? "—" : `$ ${fmt(v / 1e12, 2)} billones`);
    const licT = panel("Última licitación del Tesoro", ult ? `<div class="strip"><span><b>Fecha</b> ${dmy(ult.fecha)}</span><span><b>Ofertado</b> ${bill(ult.ofertado)}</span>
        <span><b>Adjudicado</b> ${bill(ult.adjudicado)}</span>${ult.rollover != null ? `<span><b>Rollover</b> ${pct(ult.rollover, 1)}</span>` : ""}
        ${ult.ofertado && ult.adjudicado ? `<span><b>Adjudicado / ofertado</b> ${pct(ult.adjudicado / ult.ofertado * 100, 0)}</span>` : ""}</div>`
      + table(["Instrumento", "VE adjudicado ($ M)", "Precio", "TEM", "TIREA"], (ult.instrumentos || []).map((i) => [esc(i.instrumento) + (i.nueva ? `<span class="sub">nueva</span>` : ""),
          i.usd ? `${fmt(i.ve_adjudicado, 0)}<span class="sub">en $</span>` : fmt(i.ve_adjudicado, 0), i.precio != null ? fmt(i.precio, 2) : "—", pct(i.tem), pct(i.tirea)]), [0])
      + (lic.length > 1 ? `<h3>Anteriores</h3>` + table(["Fecha", "Ofertado", "Adjudicado", "Adj./ofertado"], lic.slice(1).map((r) => [dmy(r.fecha), bill(r.ofertado), bill(r.adjudicado), r.ofertado ? pct(100 * r.adjudicado / r.ofertado, 0) : "—"])) : "")
      + `<div class="note">Fuente: <a href="${esc(ult.url)}" target="_blank" rel="noopener">resultado publicado por la Secretaría de Finanzas</a>. El rollover aparece solo cuando el comunicado lo informa.</div>`
      : `<div class="empty">Sin resultados leídos todavía.</div>`, { meta: meta(D, "licitaciones_resultado") });
    const tam = panel("TAMAR", table(["Ticker", "Precio", "Dif"], tamar.map((r) => fila(r, [tk(r), fmt(r.precio, 2), chg(r.d)])))
      + `<div class="note">Sin TIR: depende del margen sobre TAMAR de cada emisión y de la historia de la TAMAR desde la emisión; queda pendiente de cargar esas condiciones.</div>`, { meta: m });
    return `${rueda()}${ref}<div class="cols-split"><div class="view">${fija}${eqT}</div><div class="sticky view">${curvaPesos}${cauT}</div></div>
      <div class="cols-split"><div class="view">${cerT}</div><div class="sticky">${cerCurva}</div></div>
      <div class="cols-split"><div class="view">${beT}${dlT}</div><div class="view">${licT}${tam}</div></div>`;
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
        pl.map((r) => Object.assign(fila(r, [tk(r), `<span class="na">${esc(secDe(r.ticker) || "—")}</span>`, fmt(r.precio, 2), chg(r.d), chg(r.w), chg(r.m), chg(r.y),
          chg(rel(r.m, mv.m)), chg(rel(r.m, promSector(r.ticker, "m"))), chg(rel(r.y, mv.y))]), { acc: r.ticker, cls: `${r.opero === false ? "sinop " : ""}clic` })), [1])
      + `<div class="note">"vs." = cuánto le ganó (verde) o perdió (rojo) cada acción a su referencia en el período, en pesos. Sector: promedio simple de los otros papeles del panel del mismo sector.</div>`, { lead: true, meta: m });
    const adrs = panel("ADRs en Nueva York", table(["", "USD", "Día", "Sem", "Mes", "Año"], priceRows(mk.adrs, ["d", "w", "m", "y"])), { meta: meta(P, "markets") });
    const ced = panel("CEDEARs", table(["Ticker", "Precio", "Día", "Mes", "MEP implícito", "CCL implícito"], (arm.cedears || []).map((r) => fila(r, [tk(r), fmt(r.precio, 2), chg(r.d), chg(r.m), fmt(r.mep, 2), fmt(r.ccl, 2)]))), { meta: m });
    return `${rueda()}${head}${panelT}<div class="cols-2">${adrs}${ced}</div>`;
  }

  function viewEmpresas() {
    const mk = blk(P, "markets") || {}, cap = blk(D, "megacaps_info") || {}, earn = blk(D, "earnings") || [];
    const cm = (blk(P, "ar_market") || {}).cedears_mega || {};
    const prox = (id) => { const e = earn.filter((r) => r.ticker === id).sort((a, b) => (a.fecha < b.fecha ? -1 : 1))[0]; return e ? dmy(e.fecha) : "—"; };
    const spx = (mk.indices_eeuu || []).find((x) => x.id === "SPX") || {};
    const secs = Object.fromEntries((mk.sectores || []).map((x) => [x.id, x]));
    const rows = (arr) => [...(arr || [])].sort((a, b) => (cap[b.id] ?? 0) - (cap[a.id] ?? 0)).map((r) => Object.assign(filaEmp(r), { emp: r.id, cls: "clic" }));
    const filaEmp = (r) => {
      const sx = secs[r.sector] || {};
      const c = r.cedear ? cm[r.cedear] : null;
      return [`${esc(r.nombre)}<span class="sub">${esc(r.id)}</span>`, cap[r.id] != null ? fmt(cap[r.id], 0) : "—", fmt(r.last, 2), chg(r.d), chg(r.m), chg(r.y),
        chg(rel(r.m, spx.m)), chg(rel(r.y, spx.y)), `${chg(rel(r.y, sx.y))}<span class="sub" title="${esc(sx.nombre || "")}">${esc(sx.id || "")}</span>`, chg(r.dd52, 1), prox(r.id),
        c ? `${fmt(c.ccl, 0)}` : (r.cedear ? "—" : `<span class="na">sin CEDEAR</span>`)];
    };
    const H = ["Empresa", "Cap. US$ mM", "Precio US$", "Día", "Mes", "Año", "vs S&P mes", "vs S&P año", "vs sector año", "vs máx 52s", "Balance", "CCL CEDEAR"];
    const m = meta(P, "markets");
    return `${panel("Grandes del S&P 500", table(H, rows(mk.megacaps_eeuu)), { lead: true, meta: m })}
      ${panel("Gigantes fuera de EE.UU.", table(H, rows(mk.megacaps_global)) + `<div class="note">Precios en US$ de su ADR o cotización en EE.UU. (Saudi Aramco en Riad, convertida a US$). Capitalización: cierre del día anterior. Cap.: capitalización en miles de millones de US$. Ordenadas por capitalización; hacé clic en un encabezado para reordenar. "vs." = cuánto le ganó (verde) o perdió (rojo) al S&P 500 o al ETF de su sector en EE.UU. (XLK tecnología, XLC comunicaciones, XLY consumo discrecional, XLP consumo básico, XLF financiero, XLV salud, XLE energía, XLB materiales, XLI industria).</div>`, { meta: m })}
      ${panel("Tu selección", table(H, rows(mk.empresas_seleccion)) + `<div class="note">Empresas elegidas a mano (Argentina, Brasil, tecno). Se editan en config/instruments.json → empresas_seleccion.</div>`, { meta: m })}`;
  }

  // Bolsas abiertas o cerradas (lunes a viernes, sin contemplar feriados)
  const BOLSAS = [["Nueva York", "America/New_York", 570, 960, "us"], ["Londres", "Europe/London", 480, 990, "uk"], ["Fráncfort", "Europe/Berlin", 540, 1050, "de"],
    ["Tokio", "Asia/Tokyo", 540, 930, "jp"], ["Hong Kong", "Asia/Hong_Kong", 570, 960, "hk"], ["San Pablo", "America/Sao_Paulo", 600, 1020, "br"], ["BYMA", "America/Argentina/Buenos_Aires", 660, 1020, "ar"]];
  const feriadoHoy = (mercado, tz) => { const hoy = new Date().toLocaleDateString("en-CA", { timeZone: tz }); return ((blk(D, "feriados") || {})[mercado] || []).find((f) => f.fecha === hoy); };
  function bolsas() {
    return `<div class="strip">${BOLSAS.map(([n, tz, a, b, k]) => {
      const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(new Date()).map((x) => [x.type, x.value]));
      const fer = feriadoHoy(k, tz);
      const mins = (+p.hour % 24) * 60 + +p.minute, open = !fer && !["Sat", "Sun"].includes(p.weekday) && mins >= a && mins < b;
      return `<span class="${open ? "abierta" : "cerrada"}" ${fer ? `title="${esc(fer.nombre)}"` : ""}><i></i>${n} ${p.hour}:${p.minute}${fer ? " · feriado" : ""}</span>`;
    }).join("")}</div>`;
  }

  function viewMercados() {
    const mk = blk(P, "markets") || {};
    const head = ["", "Último", ...Object.values(VARS)];
    const g = (k) => table(head, priceRows(mk[k], Object.keys(VARS)));
    const m = meta(P, "markets");
    const tbc = blk(D, "tasas_bc") || [], prox = {};
    for (const b of ((blk(D, "calendar_intl") || {}).bancos || [])) if (!prox[b.banco]) prox[b.banco] = b.fecha;
    prox.Fed = ((blk(D, "fed") || {}).proximo_fomc || [])[0];
    const tbcT = panel("Tasas de política monetaria", table(["Banco central", "Tasa", "Qué tasa", "Dato del", "Próxima decisión"],
      tbc.map((b) => [esc(b.banco), pct(b.tasa, 2), `<span class="na">${esc(b.detalle)}</span>`, dmy(b.fecha), dmy(prox[b.banco] || (b.banco.startsWith("Banco Central de Brasil") ? prox["Banco Central de Brasil (Copom)"] : null))]), [0, 2]), { meta: meta(D, "tasas_bc") });
    return `${bolsas()}${tbcT}<div class="cols-2">
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
  const CATS = { us: "Datos EE.UU.", fed: "Fed", ar: "INDEC", lic: "Licitaciones", pago: "Pagos de deuda AR", bc: "Bancos centrales", intl: "Datos internacionales", earn: "Balances", fer: "Feriados" };
  let calOff = new Set();
  try { calOff = new Set(JSON.parse(localStorage.getItem("calOff") || "[]")); } catch {}
  function agenda() {
    const hoy = new Date(); hoy.setHours(0, 0, 0, 0);
    const ev = [];
    const imp = (x) => (x === "High" ? "alto" : x === "Medium" ? "medio" : "");
    for (const r of blk(D, "calendar_us") || []) ev.push({ cat: "us", t: r.fecha, hora: true, txt: r.evento, det: [r.esperado && `esp. ${r.esperado}`, r.previo && `prev. ${r.previo}`].filter(Boolean).join(" · "), imp: imp(r.impacto) });
    for (const f of (blk(D, "fed") || {}).fomc || []) ev.push({ cat: "fed", t: `${f}T15:00:00-03:00`, hora: true, txt: "Decisión de tasas (FOMC)", det: "", imp: "alto" });
    for (const r of blk(D, "calendar_ar") || []) ev.push({ cat: r.tipo === "licitacion" ? "lic" : r.tipo === "pago" ? "pago" : "ar", t: `${r.fecha}T${r.hora || "12:00"}:00-03:00`, hora: !!r.hora, txt: r.evento, det: "", imp: r.tipo === "pago" ? "" : "alto" });
    const intl = blk(D, "calendar_intl") || {};
    for (const r of intl.bancos || []) ev.push({ cat: "bc", t: `${r.fecha}T${r.hora || "12:00"}:00-03:00`, hora: !!r.hora, txt: `${r.banco} · decisión de tasa`, det: "", imp: "alto" });
    for (const r of intl.datos_semana || []) ev.push({ cat: "intl", t: r.fecha, hora: true, txt: `${r.pais} · ${r.evento}`, det: [r.esperado && `esp. ${r.esperado}`, r.previo && `prev. ${r.previo}`].filter(Boolean).join(" · "), imp: "alto" });
    const fer = blk(D, "feriados") || {};
    for (const r of fer.ar || []) ev.push({ cat: "fer", t: `${r.fecha}T12:00:00-03:00`, hora: false, txt: `Argentina · ${r.nombre}`, det: "BYMA cerrado", imp: "" });
    for (const r of fer.us || []) ev.push({ cat: "fer", t: `${r.fecha}T12:00:00-03:00`, hora: false, txt: `EE.UU. · ${r.nombre}`, det: "Wall Street cerrado", imp: "" });
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

  /* ---------- Flujo de fondos de un bono o letra (clic en la fila) ---------- */
  function buscarRF(t) {
    const a = blk(P, "ar_market") || {};
    return [...(a.soberanos || []), ...(a.bopreal || []), ...(a.pesos_fija || []), ...(a.cer_tamar || []), ...(a.dolar_linked || [])].find((r) => r.ticker === t);
  }
  /* ---------- Ficha de un bono o letra (clic en la fila) ---------- */
  let RAW = null, fichaAbierta = null;
  const HIST_FICHA = {};
  async function historiaFicha(t) {
    if (HIST_FICHA[t] !== undefined) return HIST_FICHA[t];
    const getJ = (u) => fetch(u + `?t=${Date.now()}`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    HIST_FICHA[t] = (RAW && (await getJ(`${RAW}fichas/${t}.json`))) || (await getJ(`data/fichas/${t}.json`));
    return HIST_FICHA[t];
  }
  // gráfico de línea en el tiempo (fechas ISO en x)
  function serieTiempo(f, ys, o) {
    const pts = f.map((d, i) => [i, ys[i]]).filter(([, y]) => y != null);
    if (pts.length < 2) return `<div class="empty">Sin historia suficiente para el gráfico.</div>`;
    const W = 700, H = 230, L = 50, R = 14, T = 12, B = 26;
    const extra = (o.extra || []).map((e) => ({ ...e, pts: f.map((d, i) => [i, e.ys[i]]).filter(([, y]) => y != null) }));
    const todos = [...pts, ...extra.flatMap((e) => e.pts)];
    let y0 = Math.min(...todos.map((p) => p[1])), y1 = Math.max(...todos.map((p) => p[1]));
    const m = (y1 - y0) * 0.08 || Math.abs(y1) * 0.02 || 1; y0 -= m; y1 += m;
    const X = (i) => L + (i / (f.length - 1)) * (W - L - R), Y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
    let g = niceTicks(y0, y1, 5).map((t) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(t)}" y2="${Y(t)}"/><text x="${L - 6}" y="${Y(t) + 4}" text-anchor="end">${fmt(t, o.dec)}</text>`).join("");
    let mes = "";
    f.forEach((d, i) => { const mm = d.slice(0, 7); if (mm !== mes) { if (mes && d.slice(5, 7) % 2 === 1) g += `<text x="${X(i)}" y="${H - 8}" text-anchor="middle">${d.slice(5, 7)}/${d.slice(2, 4)}</text>`; mes = mm; } });
    for (const e of extra) g += `<polyline class="${e.cls}" stroke-width="1.4" points="${e.pts.map(([i, y]) => `${X(i).toFixed(1)},${Y(y).toFixed(1)}`).join(" ")}"/>`;
    if (o.base != null) g += `<line class="grid" stroke-dasharray="4 4" x1="${L}" x2="${W - R}" y1="${Y(o.base)}" y2="${Y(o.base)}"/>`;
    g += `<polyline class="s1" stroke-width="1.8" points="${pts.map(([i, y]) => `${X(i).toFixed(1)},${Y(y).toFixed(1)}`).join(" ")}"/>`;
    const [li, ly] = pts[pts.length - 1];
    g += `<circle class="s1" cx="${X(li)}" cy="${Y(ly)}" r="3"><title>${dmy(f[li])}: ${fmt(ly, o.dec)}${o.suf}</title></circle>`;
    const leg = o.leyenda ? `<div class="legend">${o.leyenda.map(([c, n]) => `<span class="${c}"><i></i>${esc(n)}</span>`).join("")}</div>` : "";
    return `${leg}<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.titulo)}">${g}</svg></div>`;
  }
  // valor de la serie en la última fecha <= iso
  const valorAl = (h, iso, campo = "p") => { let v = null; for (let i = 0; i < h.f.length && h.f[i] <= iso; i++) if (h[campo][i] != null) v = h[campo][i]; return v; };
  const isoMenos = (iso, dias) => new Date(new Date(iso + "T12:00:00Z").getTime() - dias * 864e5).toISOString().slice(0, 10);
  function rendimientoFicha(h) {
    const n = h.f.length, ult = h.p[n - 1], fin = h.f[n - 1];
    const vr = (iso) => { const v = valorAl(h, iso); return v ? (ult / v - 1) * 100 : null; };
    const anio = h.f.filter((d) => d >= isoMenos(fin, 365)), idx0 = h.f.indexOf(anio[0]);
    const ps = h.p.slice(idx0).filter((x) => x != null), max = Math.max(...ps), min = Math.min(...ps);
    const vs = (h.v || []).filter((x) => x != null), vol20 = vs.slice(-21, -1), prom = vol20.length ? vol20.reduce((a, b) => a + b, 0) / vol20.length : null;
    const volU = (h.v || [])[n - 1];
    return `<dl class="kv"><dt>Último cierre</dt><dd>${fmt(ult, dec(ult))} <span class="na">(${dmy(fin)})</span></dd>
      <dt>Semana</dt><dd>${chg(vr(isoMenos(fin, 7)))}</dd><dt>Mes</dt><dd>${chg(vr(isoMenos(fin, 30)))}</dd>
      <dt>En el año</dt><dd>${chg(vr(`${+fin.slice(0, 4) - 1}-12-31`))}</dd><dt>12 meses</dt><dd>${h.f[0] <= isoMenos(fin, 355) ? chg((ult / h.p[Math.max(0, h.f.findIndex((d) => d >= isoMenos(fin, 365)))] - 1) * 100) : `<span class="na">—</span>`}</dd>
      <dt>Rango del período</dt><dd>${fmt(min, dec(min))} – ${fmt(max, dec(max))}</dd><dt>Distancia al máximo</dt><dd>${chg((ult / max - 1) * 100)}</dd>
      <dt>Volumen vs. prom. 20 ruedas</dt><dd>${volU && prom ? `${fmt(volU / prom, 1)}×` : "—"}</dd></dl>`;
  }
  // precio teórico con una TIR dada, descontando el flujo de fondos desde la liquidación
  function precioCon(flujos, tir, liq) {
    const s = new Date(liq + "T12:00:00Z");
    return flujos.reduce((a, f) => { const t = (new Date(f[0] + "T12:00:00Z") - s) / 864e5 / 365; return t > 0 ? a + f[4] / Math.pow(1 + tir / 100, t) : a; }, 0);
  }
  function abrirFlujos(t) {
    const r = buscarRF(t); if (!r) return;
    const arm = blk(P, "ar_market") || {}, liq = arm.liquidacion;
    const usd = r.usd != null, cer = r.tipo === "CER", fija = r.tipo === "LECAP" || r.tipo === "BONCAP", dlnk = r.tipo === "Dólar linked", tamar = r.tipo === "TAMAR";
    const precio = usd ? r.usd : r.precio, tir = r.tir ?? r.tirea, c = r.cond || {};
    const nombre = usd ? (r.ley ? `Bono en dólares · Ley ${r.ley === "NY" ? "Nueva York" : "argentina"}` : "BOPREAL (BCRA)") : r.tipo;
    const kv = (pares) => `<dl class="kv">${pares.filter(Boolean).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
    const strip = [["Precio", fmt(precio, 2) + (usd ? " US$" : " $")], ["Día", chg(r.d)],
      tamar ? null : [fija ? "TEM" : cer ? "TIR real" : dlnk ? "TIR en US$" : "TIR", pct(fija ? r.tem : tir, 2)],
      r.dur_mod != null ? ["Duration mod.", fmt(r.dur_mod, 2)] : null, ["Vencimiento", dmy(r.vto || c.vto)]].filter(Boolean);
    // condiciones de emisión
    const cond = kv([c.emision && ["Emisión", dmy(c.emision)], ["Vencimiento", dmy(c.vto || r.vto)],
      c.cupon != null && (c.cupon === 0 && !c.escalones ? ["Cupón", "Cero cupón"] : [cer ? "Cupón (sobre capital ajustado)" : "Cupón vigente", `${fmt(c.cupon, 3)}% anual, ${c.frecuencia}`]),
      c.escalones && ["Cupón escalonado", c.escalones.map(([f, v]) => `${fmt(v, 3)}% desde ${dmy(f)}`).join("<br>")],
      c.amortizacion && ["Amortización", esc(c.amortizacion)], c.cer_inicial && ["CER inicial", fmt(c.cer_inicial, 4)],
      c.tem_emision != null && ["TEM de emisión", pct(c.tem_emision)], c.pago_final && ["Pago final por 100 VN", fmt(c.pago_final, 3)],
      usd && ["Moneda de pago", "Dólares"], usd && r.ley && ["Ley", r.ley === "NY" ? "Nueva York" : "Argentina"],
      dlnk && ["Moneda", "Pesos, ajustado por A3500 del vencimiento"],
      c.fuente && ["Origen de las condiciones", esc(c.fuente)], tamar && ["Nota", "Paga TAMAR más un margen; sin TIR hasta cargar sus condiciones."]]);
    // métricas y sensibilidad
    let sens = null;
    if (r.flujos && tir != null && liq) {
      const b = precioCon(r.flujos, tir, liq), up = precioCon(r.flujos, tir + 1, liq), dn = precioCon(r.flujos, tir - 1, liq);
      if (b > 0) sens = `${chg((dn / b - 1) * 100)} / ${chg((up / b - 1) * 100)}`;
    }
    const prox = r.flujos && r.flujos.length ? r.flujos[0] : null;
    const met = kv([tir != null && [cer ? "TIR real" : dlnk ? "TIR en US$" : fija ? "TIREA" : "TIR", pct(tir, 2)],
      r.tem != null && ["TEM / TNA", `${pct(r.tem, 2)} / ${pct(r.tna, 2)}`], r.dur_mod != null && ["Duration modificada", fmt(r.dur_mod, 2)],
      r.paridad != null && ["Paridad", pct(r.paridad, 1)], r.vt != null && ["Valor técnico", fmt(r.vt, 3)],
      r.vt != null && r.residual != null && ["Intereses corridos", fmt(r.vt - r.residual, 3)], r.residual != null && ["Valor residual", fmt(r.residual, 2)],
      prox && ["Próximo pago", `${dmy(prox[0])} · ${fmt(prox[4], 3)}`], sens && ["Precio si la TIR baja / sube 1 pto", sens],
      r.coef_cer != null && ["Coeficiente CER", fmt(r.coef_cer, 4)], r.precio_usd != null && ["Precio en US$ (A3500 de hoy)", fmt(r.precio_usd, 2)]]);
    // comparaciones propias de cada tipo
    let extra = "";
    if (r.ley) {
      const par = r.ticker.startsWith("GD") ? (r.ticker === "GD38" ? "AE38" : r.ticker.replace(/^GD/, "AL")) : (r.ticker === "AE38" ? "GD38" : r.ticker.replace(/^AL/, "GD"));
      const o = (arm.soberanos || []).find((x) => x.ticker === par);
      if (o && o.tir != null && tir != null) {
        const [loc, ny] = r.ley === "NY" ? [o, r] : [r, o];
        extra += `<h3>Contra su par de la otra ley</h3>` + kv([[`${par} · TIR`, pct(o.tir, 2)], [`${par} · precio`, fmt(o.usd, 2) + " US$"],
          ["Diferencia de TIR (ley local − ley NY)", `${fmt((loc.tir - ny.tir) * 100, 0)} pb`]]);
      }
    }
    const cot = (blk(P, "dolares") || {}).cotizaciones || [], a35 = byId(cot, "mayorista").venta || arm.a3500_ref;
    const fut = ((blk(D, "futuros_dolar") || {}).contratos || []).filter((x) => x.precio && x.vto)
      .map((x) => ({ d: Math.round((new Date(x.vto + "T12:00:00-03:00") - Date.now()) / 864e5), p: x.precio })).filter((x) => x.d > 0);
    const futAl = (d) => { for (let i = 0; i < fut.length - 1; i++) if (d >= fut[i].d && d <= fut[i + 1].d) return fut[i].p + (fut[i + 1].p - fut[i].p) * (d - fut[i].d) / (fut[i + 1].d - fut[i].d); return null; };
    if (fija && r.pago_final && a35) {
      const rem = (blk(D, "rem") || {}).ipc_mensual || [], rv = rem.filter((x) => x.mes <= r.vto.slice(0, 7));
      extra += `<h3>Contra inflación y dólar</h3>` + kv([r.inflacion_implicita != null && ["Inflación mensual implícita (vs. CER)", pct(r.inflacion_implicita)],
        rv.length && ["REM promedio hasta el vencimiento", pct(rv.reduce((a, x) => a + x.mediana, 0) / rv.length, 1)],
        ["Dólar de equilibrio al vencimiento", fmt(a35 * r.pago_final / r.precio, 0)], futAl(r.dias) && ["Dólar futuro A3 al vencimiento", fmt(futAl(r.dias), 0)]]);
    }
    if (dlnk && a35 && r.precio_usd) {
      const pf = (arm.pesos_fija || []).filter((x) => x.tem != null).sort((x, y) => x.dias - y.dias);
      let tf = null;
      if (pf.length) { tf = r.dias <= pf[0].dias ? pf[0].tem : r.dias >= pf[pf.length - 1].dias ? pf[pf.length - 1].tem : null;
        for (let i = 0; tf == null && i < pf.length - 1; i++) if (r.dias >= pf[i].dias && r.dias <= pf[i + 1].dias) tf = pf[i].tem + (pf[i + 1].tem - pf[i].tem) * (r.dias - pf[i].dias) / (pf[i + 1].dias - pf[i].dias); }
      extra += `<h3>Contra tasa fija y futuro</h3>` + kv([tf != null && ["Dólar implícito (empata con LECAP)", fmt(a35 * Math.pow(1 + tf / 100, r.dias / 30) / (100 / r.precio_usd), 0)],
        futAl(r.dias) && ["Dólar futuro A3 al vencimiento", fmt(futAl(r.dias), 0)], ["A3500 hoy", fmt(a35, 2)]]);
    }
    const tot = r.flujos ? r.flujos.reduce((a, f) => a + f[4], 0) : null;
    const nota = dlnk ? `Paga US$ 100 por cada 100 VN, en pesos al A3500 del vencimiento.`
      : cer ? `Montos por 100 VN ajustados por el CER de hoy; el pago real depende del CER a la fecha de cada pago.`
      : fija ? `Letra capitalizable: un único pago al vencimiento.` : `Montos por 100 VN original. Fechas corridas al día hábil siguiente si caen en feriado o fin de semana.`;
    const flujosHtml = r.flujos ? `<h3>Flujo de fondos</h3>${table(["Fecha", "Saldo", "Cupón", "Amort.", "Total"], r.flujos.map((f) => [dmy(f[0]), fmt(f[1], 3), fmt(f[2], 3), fmt(f[3], 3), `<b>${fmt(f[4], 3)}</b>`]))}
      <div class="note">Total a cobrar por 100 VN: <b>${fmt(tot, 2)}</b>. ${nota}</div>` : "";
    const box = $("#ficha");
    fichaAbierta = { t, modo: tamar ? "p" : "m" };
    box.innerHTML = `<div class="ficha-caja" role="dialog" aria-label="Ficha ${esc(t)}"><button class="cerrar" aria-label="Cerrar">×</button>
      <h2>${esc(t)} <span class="sub">${esc(nombre)}</span></h2>
      <div class="strip">${strip.map(([k, v]) => `<span><b>${k}</b> ${v}</span>`).join("")}</div>
      <div id="ficha-graf"><div class="empty">Cargando historia…</div></div>
      <div class="ficha-cols"><div><h3>Rendimiento del precio</h3><div id="ficha-rend"><div class="empty">Cargando…</div></div></div><div><h3>Condiciones de emisión</h3>${cond}</div></div>
      <div class="ficha-cols"><div><h3>Métricas de hoy</h3>${met}</div><div>${extra}</div></div>
      ${flujosHtml}</div>`;
    box.hidden = false;
    historiaFicha(t).then((h) => { if (fichaAbierta && fichaAbierta.t === t) dibujarFicha(h); });
  }
  function dibujarFicha(h) {
    const g = $("#ficha-graf"), rd = $("#ficha-rend"); if (!g) return;
    if (!h || !h.f || h.f.length < 2) { g.innerHTML = `<div class="empty">Todavía no hay historia de este papel (se arma en la corrida de Datos diarios).</div>`; rd.innerHTML = `<div class="empty">—</div>`; return; }
    const tieneM = h.m && h.m.some((x) => x != null), modo = tieneM ? fichaAbierta.modo : "p";
    const botones = tieneM ? `<div class="togs">${[["m", h.metrica], ["p", "Precio"]].map(([k, n]) => `<button class="tog" data-modo="${k}" aria-pressed="${modo === k}">${esc(n)}</button>`).join("")}</div>` : "";
    g.innerHTML = botones + serieTiempo(h.f, modo === "m" ? h.m : h.p, { dec: modo === "m" ? 1 : dec(h.p[h.p.length - 1]), suf: modo === "m" ? "%" : "", titulo: `${h.ticker} ${modo === "m" ? h.metrica : "precio"}` })
      + `<div class="note">Último año, cierres diarios (${esc(h.fuente || "")}). ${modo === "m" ? `${esc(h.metrica)} calculada con el precio de cada día.` : buscarRF(h.ticker)?.flujos?.length > 1 ? "El precio baja en las fechas de pago de cupón y amortización." : ""}</div>`;
    rd.innerHTML = rendimientoFicha(h);
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".tog"); if (!b || !fichaAbierta) return;
    fichaAbierta.modo = b.dataset.modo;
    if (fichaAbierta.t.startsWith("emp:")) graficoEmpresa(HIST_EMP[fichaAbierta.t.slice(4)]);
    else if (fichaAbierta.t.startsWith("acc:")) graficoAccion(HIST_ACC[fichaAbierta.t.slice(4)]);
    else dibujarFicha(HIST_FICHA[fichaAbierta.t]);
  });

  /* ---------- Ficha de una empresa (clic en la fila de la pestaña Empresas) ---------- */
  const HIST_EMP = {};
  async function historiaEmpresa(id) {
    if (HIST_EMP[id] !== undefined) return HIST_EMP[id];
    const getJ = (u) => fetch(u + `?t=${Date.now()}`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    HIST_EMP[id] = (RAW && (await getJ(`${RAW}fichas/emp/${id}.json`))) || (await getJ(`data/fichas/emp/${id}.json`));
    return HIST_EMP[id];
  }
  const RECOM = { strong_buy: "Compra fuerte", buy: "Compra", hold: "Mantener", underperform: "Bajo rendimiento", sell: "Venta", strong_sell: "Venta fuerte" };
  const montoMM = (v, mon) => (v == null ? "—" : `${mon && mon !== "USD" ? esc(mon) + " " : "US$ "}${fmt(v / 1e9, Math.abs(v) >= 1e11 ? 0 : 1)} mM`);
  function filaEmpresa(id) {
    const mk = blk(P, "markets") || {};
    for (const g of ["megacaps_eeuu", "megacaps_global", "empresas_seleccion"]) { const r = (mk[g] || []).find((x) => x.id === id); if (r) return r; }
    return null;
  }
  function abrirEmpresa(id) {
    const r = filaEmpresa(id); if (!r) return;
    const box = $("#ficha");
    fichaAbierta = { t: "emp:" + id, modo: "p" };
    box.innerHTML = `<div class="ficha-caja" role="dialog" aria-label="Ficha ${esc(r.nombre)}"><button class="cerrar" aria-label="Cerrar">×</button>
      <h2>${esc(r.nombre)} <span class="sub">${esc(id)}</span></h2><div id="emp-cuerpo"><div class="empty">Cargando…</div></div></div>`;
    box.hidden = false;
    historiaEmpresa(id).then((h) => { if (fichaAbierta && fichaAbierta.t === "emp:" + id) dibujarEmpresa(r, h); });
  }
  function dibujarEmpresa(r, h) {
    const cuerpo = $("#emp-cuerpo"); if (!cuerpo) return;
    const i = (h && h.info) || {}, earn = blk(D, "earnings") || [], cap = (blk(D, "megacaps_info") || {})[r.id];
    const kv = (pares) => `<dl class="kv">${pares.filter(Boolean).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
    const x = (v, d = 1) => (v == null ? "—" : `${fmt(v, d)}×`);
    const prox = earn.filter((e) => e.ticker === r.id).sort((a, b) => (a.fecha < b.fecha ? -1 : 1))[0];
    const precio = r.last ?? (h && h.p ? h.p[h.p.length - 1] : null);
    const strip = [["Precio", `${fmt(precio, 2)} US$`], ["Día", chg(r.d)], ["Cap.", cap != null ? `US$ ${fmt(cap, 0)} mM` : montoMM(i.cap)],
      ["P/E", x(i.pe)], ["vs máx. 52s", chg(r.dd52, 1)], ["Próximo balance", prox ? dmy(prox.fecha) : "—"]];
    const sub = [i.sector, i.industria, i.pais].filter(Boolean).map(esc).join(" · ");
    if (!h) { cuerpo.innerHTML = `<div class="strip">${strip.map(([k, v]) => `<span><b>${k}</b> ${v}</span>`).join("")}</div><div class="empty">Todavía no hay ficha de esta empresa (se arma en la corrida de Datos diarios).</div>`; return; }
    // rendimiento comparado: empresa, S&P 500 y ETF del sector en los mismos períodos
    const n = h.f.length, fin = h.f[n - 1];
    const idxDesde = (iso) => { const k = h.f.findIndex((d) => d >= iso); return k < 0 ? null : k; };
    const varS = (arr, k) => (k == null || arr == null || arr[k] == null || arr[n - 1] == null ? null : (arr[n - 1] / arr[k] - 1) * 100);
    const periodos = [["1 mes", isoMenos(fin, 30)], ["3 meses", isoMenos(fin, 91)], ["En el año", `${fin.slice(0, 4)}-01-01`], ["12 meses", isoMenos(fin, 365)]];
    const rendT = table(["", esc(r.id), "S&P 500", `Sector (${esc(h.sector_etf || "—")})`, "Le ganó al S&P", "Le ganó al sector"], periodos.map(([nom, iso]) => {
      const k = idxDesde(iso), e = varS(h.p, k), sp = varS(h.spx, k), se = varS(h.sec, k);
      return [nom, chg(e), chg(sp), chg(se), chg(rel(e, sp)), chg(rel(e, se))];
    }), [0]);
    const ps = h.p.filter((v) => v != null), mx = Math.max(...ps), mn = Math.min(...ps);
    const vs = (h.v || []).filter((v) => v != null), prom = vs.length > 21 ? vs.slice(-21, -1).reduce((a, b) => a + b, 0) / 20 : null;
    const rango = kv([["Rango 12 meses", `${fmt(mn, 2)} – ${fmt(mx, 2)}`], ["Distancia al máximo", chg((h.p[n - 1] / mx - 1) * 100)],
      ["Volumen vs. prom. 20 ruedas", prom && vs[vs.length - 1] ? `${fmt(vs[vs.length - 1] / prom, 1)}×` : "—"], ["Beta", fmt(i.beta, 2)]]);
    const mb = i.moneda_balance;
    const valuacion = kv([["Capitalización", cap != null ? `US$ ${fmt(cap, 0)} mM` : montoMM(i.cap)], ["P/E (últimos 12 meses)", x(i.pe)], ["P/E proyectado", x(i.pe_fwd)],
      ["EV / EBITDA", x(i.ev_ebitda)], ["Precio / ventas", x(i.p_ventas)], ["Precio / valor libro", x(i.p_libro)],
      ["Rendimiento por dividendo", i.div ? pct(i.div, 2) : "—"], i.payout != null && ["Payout", pct(i.payout, 0)]]);
    const negocio = kv([["Ventas (12 meses)", montoMM(i.ventas, mb)], ["Crecimiento de ventas", i.crec_ventas != null ? chg(i.crec_ventas, 1) + ` <span class="sub">interanual</span>` : "—"],
      ["Crecimiento de ganancias", i.crec_ganancias != null ? chg(i.crec_ganancias, 1) + ` <span class="sub">interanual</span>` : "—"],
      ["Margen bruto / operativo / neto", [i.margen_bruto, i.margen_operativo, i.margen_neto].map((v) => (v == null ? "—" : fmt(v, 1) + "%")).join(" / ")],
      ["ROE", i.roe != null ? pct(i.roe, 1) : "—"], ["EBITDA", montoMM(i.ebitda, mb)], ["Flujo de caja libre", montoMM(i.fcf, mb)],
      ["Deuda neta", i.deuda_neta != null ? (i.deuda_neta < 0 ? `caja neta ${montoMM(-i.deuda_neta, mb)}` : montoMM(i.deuda_neta, mb)) : "—"]]);
    const bal = (h.balances || []).length ? table(["Trimestre", "EPS esperado", "EPS real", "Sorpresa"], h.balances.map((b) => [esc(b.trimestre ? dmy(b.trimestre) : "—"), fmt(b.estimado, 2), fmt(b.real, 2), chg(b.sorpresa, 1)]), [0])
      : `<div class="empty">Sin historial de balances.</div>`;
    const rc = h.recomendaciones, totR = rc ? Object.values(rc).reduce((a, b) => a + b, 0) : 0;
    const barra = totR ? `<div class="recom">${[["strongBuy", "Compra fuerte", "rc1"], ["buy", "Compra", "rc2"], ["hold", "Mantener", "rc3"], ["sell", "Venta", "rc4"], ["strongSell", "Venta fuerte", "rc5"]]
      .filter(([k]) => rc[k]).map(([k, nmb, c]) => `<span class="${c}" style="flex:${rc[k]}" title="${nmb}: ${rc[k]}">${rc[k]}</span>`).join("")}</div>
      <div class="recom-ley"><span class="rc1">Compra fuerte</span><span class="rc2">Compra</span><span class="rc3">Mantener</span><span class="rc4">Venta</span><span class="rc5">Venta fuerte</span></div>` : "";
    const local = i.moneda && i.moneda !== "USD", monTxt = local ? ` ${esc(i.moneda)}` : "";
    const precioLocal = local ? h.p[h.p.length - 1] : precio;  // los objetivos vienen en la moneda en que cotiza
    const analistas = kv([["Recomendación promedio", i.recom ? `${esc(RECOM[i.recom] || i.recom)}${i.recom_media ? ` <span class="na">(${fmt(i.recom_media, 1)} de 1 a 5)</span>` : ""}` : "—"],
      ["Analistas", i.analistas ?? (totR || "—")], ["Precio objetivo promedio", i.objetivo ? `${fmt(i.objetivo, 2)}${monTxt} ${precioLocal ? chg((i.objetivo / precioLocal - 1) * 100, 1) : ""}` : "—"],
      i.objetivo_min && ["Rango de precios objetivo", `${fmt(i.objetivo_min, 2)} – ${fmt(i.objetivo_max, 2)}`]]) + barra;
    // CEDEAR: precio en pesos, CCL implícito contra el de mercado y ratio aproximado
    let ced = "";
    const cm = r.cedear ? ((blk(P, "ar_market") || {}).cedears_mega || {})[r.cedear] : null;
    if (cm) {
      const cclM = byId((blk(P, "dolares") || {}).cotizaciones || [], "contadoconliqui").venta;
      const ratio = cm.ccl && precio && cm.precio ? cm.ccl * precio / cm.precio : null;
      ced = `<h3>CEDEAR (${esc(r.cedear)})</h3>` + kv([["Precio en pesos", `$ ${fmt(cm.precio, 2)} ${chg(cm.d)}`], ["CCL implícito", fmt(cm.ccl, 2)],
        ["Contra el CCL de mercado", cm.ccl && cclM ? `${chg((cm.ccl / cclM - 1) * 100, 1)} <span class="na">(CCL ${fmt(cclM, 2)})</span>` : "—"],
        ratio && ["Ratio (aprox.)", `${fmt(ratio, ratio < 3 ? 2 : 0)} CEDEAR por acción`]])
        + `<div class="note">CCL implícito = precio del CEDEAR × ratio ÷ precio en EE.UU. Si está por encima del CCL de mercado, el CEDEAR está caro contra comprar la acción afuera.</div>`;
    }
    const noticias = (h.noticias || []).length ? `<ul class="news">${h.noticias.map((x) => `<li><span class="t">${x.fecha ? hhmm(x.fecha) : ""}</span><span><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.titulo)}</a> <span class="f">${esc(x.fuente || "")}</span></span></li>`).join("")}</ul>` : `<div class="empty">Sin noticias.</div>`;
    cuerpo.innerHTML = `${sub ? `<div class="note" style="margin-top:-6px">${sub}</div>` : ""}<div class="strip">${strip.map(([k, v]) => `<span><b>${k}</b> ${v}</span>`).join("")}</div>
      <div id="emp-graf"></div>
      <h3>Rendimiento comparado</h3>${rendT}
      <div class="ficha-cols"><div><h3>Valuación</h3>${valuacion}${rango}</div><div><h3>Negocio</h3>${negocio}</div></div>
      <div class="ficha-cols"><div><h3>Últimos balances</h3>${bal}${prox ? `<div class="note">Próximo: ${dmy(prox.fecha)}${prox.hora ? `, ${esc(prox.hora)}` : ""}${prox.eps_estimado != null ? ` · EPS esperado ${fmt(prox.eps_estimado, 2)}` : ""}.</div>` : ""}</div><div><h3>Analistas</h3>${analistas}</div></div>
      <div class="ficha-cols"><div><h3>Noticias</h3>${noticias}</div><div>${ced}</div></div>
      <div class="note">Fuente: ${esc(h.fuente || "")}, actualizado ${hhmm(h.updated)}. Precios ajustados por dividendos y splits${local ? `; el gráfico y los precios objetivo están en ${esc(i.moneda)}` : ""}. Montos del negocio en ${esc(mb || "USD")}, mM = miles de millones. EPS: ganancia por acción.${i.multiplos_omitidos ? ` EV/EBITDA, precio/ventas y precio/libro no se muestran: la empresa reporta en ${esc(mb)} y cotiza en ${esc(i.moneda)}, y la fuente los calcula mezclando monedas.` : ""}</div>`;
    graficoEmpresa(h);
  }
  function graficoEmpresa(h) {
    const g = $("#emp-graf"); if (!g || !h || !h.f || h.f.length < 2) { if (g) g.innerHTML = `<div class="empty">Sin historia de precios.</div>`; return; }
    const modo = fichaAbierta.modo;
    const botones = `<div class="togs">${[["p", "Precio"], ["c", "Contra S&P 500 y sector"]].map(([k, n]) => `<button class="tog" data-modo="${k}" aria-pressed="${modo === k}">${esc(n)}</button>`).join("")}</div>`;
    if (modo === "c") {
      const b = (arr) => { const k = (arr || []).findIndex((v) => v != null); return (arr || []).map((v) => (v == null || k < 0 ? null : (v / arr[k]) * 100)); };
      g.innerHTML = botones + serieTiempo(h.f, b(h.p), { dec: 0, suf: "", titulo: `${h.id} contra S&P 500 y sector`, base: 100,
        extra: [{ ys: b(h.spx), cls: "s2" }, ...(h.sec ? [{ ys: b(h.sec), cls: "s3" }] : [])], leyenda: [["s1", h.id], ["s2", "S&P 500"], ...(h.sec ? [["s3", h.sector_etf]] : [])] })
        + `<div class="note">Base 100 hace un año: cuánto rindió cada uno en el período.</div>`;
    } else g.innerHTML = botones + serieTiempo(h.f, h.p, { dec: dec(h.p[h.p.length - 1]), suf: "", titulo: `${h.id} precio` });
  }

  /* ---------- Ficha de una acción argentina (clic en la fila del panel líder) ---------- */
  const HIST_ACC = {};
  async function historiaAccion(t) {
    if (HIST_ACC[t] !== undefined) return HIST_ACC[t];
    const getJ = (u) => fetch(u + `?t=${Date.now()}`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    HIST_ACC[t] = (RAW && (await getJ(`${RAW}fichas/acc/${t}.json`))) || (await getJ(`data/fichas/acc/${t}.json`));
    return HIST_ACC[t];
  }
  function abrirAccion(t) {
    const arm = blk(P, "ar_market") || {};
    const r = [...(arm.panel_lider || []), ...(arm.acciones || [])].find((x) => x.ticker === t); if (!r) return;
    fichaAbierta = { t: "acc:" + t, modo: "u" };
    const box = $("#ficha");
    box.innerHTML = `<div class="ficha-caja" role="dialog" aria-label="Ficha ${esc(t)}"><button class="cerrar" aria-label="Cerrar">×</button>
      <h2>${esc(t)} <span class="sub" id="acc-nombre"></span></h2><div id="acc-cuerpo"><div class="empty">Cargando…</div></div></div>`;
    box.hidden = false;
    historiaAccion(t).then((h) => { if (fichaAbierta && fichaAbierta.t === "acc:" + t) dibujarAccion(r, h); });
  }
  function dibujarAccion(r, h) {
    const cuerpo = $("#acc-cuerpo"); if (!cuerpo) return;
    const kv = (pares) => `<dl class="kv">${pares.filter(Boolean).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
    const cot = (blk(P, "dolares") || {}).cotizaciones || [], cclM = byId(cot, "contadoconliqui").venta;
    const precioUsd = r.precio && cclM ? r.precio / cclM : null;
    const mkAdr = ((blk(P, "markets") || {}).adrs || []);
    const adr = h && h.adr, adrRow = adr ? mkAdr.find((x) => x.yahoo === adr.simbolo || x.id === adr.simbolo) : null;
    const adrUlt = adr ? (adrRow?.last ?? [...adr.p].reverse().find((v) => v != null)) : null;
    const cclImp = adr && adr.ratio && adrUlt && r.precio ? r.precio * adr.ratio / adrUlt : null;
    const strip = [["Precio", `$ ${fmt(r.precio, 2)}`], ["Día", chg(r.d)], ["En dólares CCL", precioUsd ? `US$ ${fmt(precioUsd, precioUsd < 10 ? 3 : 2)}` : "—"],
      adr && ["ADR " + esc(adr.simbolo), `US$ ${fmt(adrUlt, 2)} ${adrRow ? chg(adrRow.d) : ""}`], cclImp && ["CCL implícito", fmt(cclImp, 0)]].filter(Boolean);
    if (h) $("#acc-nombre").textContent = `${h.nombre}${h.sector ? " · " + h.sector : ""}`;
    if (!h) { cuerpo.innerHTML = `<div class="strip">${strip.map(([k, v]) => `<span><b>${k}</b> ${v}</span>`).join("")}</div><div class="empty">Todavía no hay ficha de esta acción (se arma en la corrida de Datos diarios).</div>`; return; }
    const n = h.f.length, fin = h.f[n - 1];
    const enUsd = h.p.map((v, k) => (v != null && h.ccl[k] ? v / h.ccl[k] : null));
    const mvUsd = h.merval ? h.merval.map((v, k) => (v != null && h.ccl[k] ? v / h.ccl[k] : null)) : null;
    h._usd = enUsd; h._mvUsd = mvUsd;
    const idxDesde = (iso) => { const k = h.f.findIndex((d) => d >= iso); return k < 0 ? null : k; };
    const varS = (arr, k) => (k == null || !arr || arr[k] == null || arr[n - 1] == null ? null : (arr[n - 1] / arr[k] - 1) * 100);
    const periodos = [["1 mes", isoMenos(fin, 30)], ["3 meses", isoMenos(fin, 91)], ["En el año", `${fin.slice(0, 4)}-01-01`], ["12 meses", isoMenos(fin, 365)]];
    const rendT = table(["", "En pesos", "En US$ CCL", "Merval US$", "Sector US$", "Le ganó al Merval", "Le ganó al sector"], periodos.map(([nom, iso]) => {
      const k = idxDesde(iso), u = varS(enUsd, k), mv = varS(mvUsd, k), se = varS(h.sector_idx, k);
      return [nom, chg(varS(h.p, k)), chg(u), chg(mv), chg(se), chg(rel(u, mv)), chg(rel(u, se))];
    }), [0]);
    const us = enUsd.filter((v) => v != null), mx = Math.max(...us), mn = Math.min(...us);
    const montos = h.v.map((v, k) => (v != null && h.p[k] && h.ccl[k] ? v * h.p[k] / h.ccl[k] : null)).filter((v) => v != null);
    const prom20 = montos.length > 21 ? montos.slice(-21, -1).reduce((a, b) => a + b, 0) / 20 : null;
    const mercado = kv([["Rango 12 meses (US$)", `${fmt(mn, dec(mn))} – ${fmt(mx, dec(mx))}`], ["Distancia al máximo (US$)", chg((enUsd[n - 1] / mx - 1) * 100)],
      ["Volumen vs. prom. 20 ruedas", montos.length > 21 && montos[montos.length - 1] ? `${fmt(montos[montos.length - 1] / prom20, 1)}×` : "—"],
      ["Monto operado por día (prom. 20 ruedas)", prom20 ? `US$ ${fmt(prom20 / 1e6, 1)} M` : "—"],
      ["Sector", `${esc(h.sector || "—")}${h.pares && h.pares.length ? ` <span class="na">(${esc(h.pares.join(", "))})</span>` : ""}`]]);
    // ADR: arbitraje y rendimiento comparado
    let adrHtml = "";
    if (adr) {
      const kA = idxDesde(`${fin.slice(0, 4)}-01-01`);
      adrHtml = `<h3>ADR en Nueva York (${esc(adr.simbolo)})</h3>` + kv([["Precio del ADR", `US$ ${fmt(adrUlt, 2)}`], ["Equivalencia", `1 ADR = ${fmt(adr.ratio, 0)} ${adr.ratio === 1 ? "acción" : "acciones"} locales`],
        ["CCL implícito", cclImp ? fmt(cclImp, 2) : "—"], ["Contra el CCL de mercado", cclImp && cclM ? `${chg((cclImp / cclM - 1) * 100, 1)} <span class="na">(CCL ${fmt(cclM, 2)})</span>` : "—"],
        ["En el año: ADR / local en US$", `${chg(varS(adr.p, kA))} / ${chg(varS(enUsd, kA))}`]])
        + `<div class="note">CCL implícito = precio local × ${fmt(adr.ratio, 0)} ÷ precio del ADR. Si está por encima del CCL de mercado, la acción está más cara acá que en Nueva York.${cclImp && cclM && Math.abs(cclImp / cclM - 1) > 0.15 ? " <b>Diferencia mayor al 15%: revisar el ratio.</b>" : ""}</div>`;
    }
    // valuación con los estados contables (en pesos) pasados a dólares al CCL de hoy
    const i = h.info || {}, fu = h.fund || {}, cap = i.cap;
    let val = "";
    if (adr && (cap || fu.utilidad_12m)) {
      const banco = h.sector === "Bancos y financieras";
      val = `<h3>Valuación (aprox.)</h3>` + kv([["Capitalización", cap ? `US$ ${fmt(cap / 1e9, 2)} mM` : "—"],
        ["P/E (últimos 12 meses)", cap && fu.utilidad_12m > 0 ? `${fmt(cap / fu.utilidad_12m, 1)}×` : fu.utilidad_12m < 0 ? "pérdida" : "—"],
        ["Precio / valor libro", cap && fu.patrimonio ? `${fmt(cap / fu.patrimonio, 2)}×` : "—"],
        ["ROE (últimos 12 meses)", fu.utilidad_12m != null && fu.patrimonio ? pct(fu.utilidad_12m / fu.patrimonio * 100, 1) : "—"],
        !banco && ["Ventas 12 meses", fu.ventas_12m ? `US$ ${fmt(fu.ventas_12m / 1e9, 2)} mM` : "—"],
        !banco && ["Margen neto", fu.utilidad_12m != null && fu.ventas_12m ? pct(fu.utilidad_12m / fu.ventas_12m * 100, 1) : "—"],
        ["Resultado 12 meses", fu.utilidad_12m != null ? `US$ ${fmt(fu.utilidad_12m / 1e9, 2)} mM` : "—"], ["Patrimonio", fu.patrimonio ? `US$ ${fmt(fu.patrimonio / 1e9, 2)} mM` : "—"],
        ["Beta (del ADR)", fmt(i.beta, 2)]])
        + `<div class="note">Estados contables en pesos (último balance: ${dmy(fu.patrimonio_fecha)}) pasados a dólares al CCL de hoy; la suma de los últimos 4 trimestres mezcla pesos de distintos momentos, por eso es aproximado. ${banco ? "En bancos se mira sobre todo precio/valor libro y ROE." : ""}</div>`;
    }
    const bal = adr && (h.balances || []).length ? `<h3>Últimos balances (ADR)</h3>` + table(["Trimestre", "EPS esperado", "EPS real", "Sorpresa"], h.balances.map((b) => [esc(b.trimestre ? dmy(b.trimestre) : "—"), fmt(b.estimado, 2), fmt(b.real, 2), chg(b.sorpresa, 1)]), [0]) : "";
    const rc = h.recomendaciones, totR = rc ? Object.values(rc).reduce((a, b) => a + b, 0) : 0;
    const ana = adr && (i.recom || totR) ? `<h3>Analistas (ADR)</h3>` + kv([["Recomendación promedio", i.recom ? esc(RECOM[i.recom] || i.recom) : "—"], ["Analistas", i.analistas ?? totR],
      ["Precio objetivo del ADR", i.objetivo && adrUlt ? `US$ ${fmt(i.objetivo, 2)} ${chg((i.objetivo / adrUlt - 1) * 100, 1)}` : "—"]])
      + (totR ? `<div class="recom">${[["strongBuy", "rc1"], ["buy", "rc2"], ["hold", "rc3"], ["sell", "rc4"], ["strongSell", "rc5"]].filter(([k]) => rc[k]).map(([k, c]) => `<span class="${c}" style="flex:${rc[k]}">${rc[k]}</span>`).join("")}</div>
        <div class="recom-ley"><span class="rc1">Compra fuerte</span><span class="rc2">Compra</span><span class="rc3">Mantener</span><span class="rc4">Venta</span><span class="rc5">Venta fuerte</span></div>` : "") : "";
    // noticias: titulares de los diarios argentinos que nombran a la empresa, más las del ADR
    const claves = (h.buscar || []).map((w) => w.toLowerCase());
    const locales = (((blk(P, "news") || {}).argentina) || []).filter((x) => claves.some((w) => (x.titulo || "").toLowerCase().includes(w)))
      .map((x) => ({ titulo: x.titulo, url: x.url, fecha: x.hora, fuente: x.fuente }));
    const notas = [...locales, ...(h.noticias || [])].slice(0, 8);
    const noticias = notas.length ? `<ul class="news">${notas.map((x) => `<li><span class="t">${x.fecha ? hhmm(x.fecha) : ""}</span><span><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.titulo)}</a> <span class="f">${esc(x.fuente || "")}</span></span></li>`).join("")}</ul>`
      : `<div class="empty">Sin noticias recientes que la nombren.</div>`;
    cuerpo.innerHTML = `<div class="strip">${strip.map(([k, v]) => `<span><b>${k}</b> ${v}</span>`).join("")}</div>
      <div id="acc-graf"></div>
      <h3>Rendimiento comparado</h3>${rendT}
      <div class="ficha-cols"><div><h3>Mercado</h3>${mercado}${adrHtml}</div><div>${val || `<h3>Datos de la empresa</h3><div class="empty">${adr ? "Sin datos contables." : "No tiene ADR: no hay una fuente gratis confiable de sus balances."}</div>`}</div></div>
      ${bal || ana ? `<div class="ficha-cols"><div>${bal}</div><div>${ana}</div></div>` : ""}
      <h3>Noticias</h3>${noticias}
      <div class="note">Fuente: ${esc(h.fuente || "")}, actualizado ${hhmm(h.updated)}. Precios ajustados por dividendos. Sector: promedio simple de las otras acciones del panel del mismo sector, en dólares.</div>`;
    graficoAccion(h);
  }
  function graficoAccion(h) {
    const g = $("#acc-graf"); if (!g || !h || h.f.length < 2) return;
    const modo = fichaAbierta.modo;
    const botones = `<div class="togs">${[["u", "En dólares (CCL)"], ["p", "En pesos"], ["c", "Contra Merval y sector"]].map(([k, n]) => `<button class="tog" data-modo="${k}" aria-pressed="${modo === k}">${esc(n)}</button>`).join("")}</div>`;
    const b = (arr) => { const k = (arr || []).findIndex((v) => v != null); return (arr || []).map((v) => (v == null || k < 0 ? null : (v / arr[k]) * 100)); };
    if (modo === "c") {
      const extra = [...(h._mvUsd ? [{ ys: b(h._mvUsd), cls: "s2" }] : []), ...(h.sector_idx ? [{ ys: b(h.sector_idx), cls: "s3" }] : [])];
      g.innerHTML = botones + serieTiempo(h.f, b(h._usd), { dec: 0, suf: "", titulo: `${h.ticker} contra Merval y sector`, base: 100, extra,
        leyenda: [["s1", h.ticker], ...(h._mvUsd ? [["s2", "Merval"]] : []), ...(h.sector_idx ? [["s3", h.sector]] : [])] }) + `<div class="note">En dólares CCL, base 100 hace un año.</div>`;
    } else if (modo === "p") g.innerHTML = botones + serieTiempo(h.f, h.p, { dec: dec(h.p[h.p.length - 1]), suf: "", titulo: `${h.ticker} en pesos` });
    else g.innerHTML = botones + serieTiempo(h.f, h._usd, { dec: dec(h._usd[h._usd.length - 1]), suf: "", titulo: `${h.ticker} en dólares CCL` }) + `<div class="note">Precio en pesos dividido por el CCL de cada día.</div>`;
  }

  const VIEWS = { resumen: viewResumen, eeuu: viewEEUU, ar_macro: viewArMacro, ar_usd: viewArUSD, ar_pesos: viewArPesos, ar_acciones: viewArAcciones,
    mercados: viewMercados, empresas: viewEmpresas, calendario: viewCalendario };
  let current = "resumen";

  // horas hábiles (lunes a viernes) transcurridas desde una fecha: el fin de semana no cuenta como atraso
  function horasHabiles(iso) {
    if (!iso) return Infinity;
    let t = new Date(iso).getTime(), h = 0; const fin = Date.now();
    while (t < fin) { const d = new Date(t).getUTCDay(); if (d !== 0 && d !== 6) h += 1; t += 36e5; }
    return h;
  }
  const NOMBRES = { markets: "Mercados (Yahoo)", dolares: "Dólares", ar_market: "Precios Argentina (data912)", fed_probs: "Probabilidades Fed (Kalshi)",
    cauciones: "Cauciones", news: "Noticias", us_macro: "Macro EE.UU.", fed: "Fed", treasuries: "Treasuries", ar_bcra: "BCRA", ipc: "IPC", riesgo_pais: "Riesgo país",
    emae: "EMAE", rem: "REM", bandas: "Bandas cambiarias", calendar_us: "Calendario EE.UU.", calendar_ar: "Calendario INDEC", calendar_intl: "Calendario internacional",
    earnings: "Balances", megacaps_info: "Capitalizaciones", lecaps_auto: "Altas de LECAP", fichas_bonos: "Historia de bonos (fichas)", licitaciones_resultado: "Resultado de licitaciones", tasas_bc: "Tasas de bancos centrales", futuros_dolar: "Dólar futuro", cer_auto: "Altas de bonos CER", feriados: "Feriados" };
  function problemas() {
    const out = [];
    // un bloque que no se actualiza hace más de 2 días hábiles (48 h de lunes a viernes)
    for (const [src, lim] of [[P, 48], [D, 48]]) for (const [k, v] of Object.entries(src)) {
      if (!v || typeof v !== "object" || !("updated" in v) || k === "dolares_hist" || k === "ar_backfill" || k === "avisos") continue;
      const h = horasHabiles(v.updated);
      if (h > lim) out.push(`${NOMBRES[k] || k}: sin actualizar desde ${v.updated ? hhmm(v.updated) : "siempre"}${v.error ? ` (${v.error})` : ""}`);
    }
    if (horasHabiles(P.generated) > 48) out.unshift(`La actualización de precios no corre desde ${hhmm(P.generated)}`);
    if (horasHabiles(D.generated) > 48) out.unshift(`La actualización diaria no corre desde ${hhmm(D.generated)}`);
    for (const a of blk(D, "avisos") || []) out.push(a);
    return out;
  }

  // Datos que no tienen sentido (un precio que salta, una tasa imposible): se muestran en el mismo aviso rojo.
  function sospechosos() {
    const out = [], a = blk(P, "ar_market") || {}, mk = blk(P, "markets") || {};
    const cot = (blk(P, "dolares") || {}).cotizaciones || [], ccl = byId(cot, "contadoconliqui").venta;
    const salto = (r, lim, nombre) => { if (r.d != null && Math.abs(r.d) > lim) out.push(`${nombre || r.ticker}: variación del día de ${fmt(r.d, 1)}%`); };
    for (const r of [...(a.soberanos || []), ...(a.bopreal || [])]) {
      salto(r, 15);
      if (r.tir != null && (r.tir < -5 || r.tir > 40)) out.push(`${r.ticker}: TIR de ${fmt(r.tir, 1)}% fuera de rango`);
    }
    for (const r of a.pesos_fija || []) {
      salto(r, 10);
      if (r.tem != null && (r.tem < 0.3 || r.tem > 8)) out.push(`${r.ticker}: TEM de ${fmt(r.tem, 2)}% fuera de rango`);
    }
    for (const r of (a.cer_tamar || []).filter((x) => x.tipo === "CER")) {
      salto(r, 10);
      if (r.tir != null && (r.tir < -20 || r.tir > 40)) out.push(`${r.ticker}: TIR real de ${fmt(r.tir, 1)}% fuera de rango`);
    }
    for (const r of [...(a.panel_lider || []), ...(a.cedears || [])]) salto(r, 25);
    for (const r of a.cedears || []) if (r.ccl && ccl && Math.abs(r.ccl / ccl - 1) > 0.1) out.push(`${r.ticker}: CCL implícito ${fmt(r.ccl, 0)} lejos del CCL ${fmt(ccl, 0)}`);
    for (const r of cot) if (r.d != null && Math.abs(r.d) > 10) out.push(`Dólar ${r.nombre}: variación del día de ${fmt(r.d, 1)}%`);
    for (const [g, arr] of Object.entries(mk)) for (const r of arr || []) salto(r, g === "cripto" ? 30 : 25, r.nombre);
    const rp = blk(D, "riesgo_pais") || {};
    if (rp.d != null && Math.abs(rp.d) > 25) out.push(`Riesgo país: variación del día de ${fmt(rp.d, 1)}%`);
    return out;
  }

  // Estado de la rueda en BYMA (11 a 17 h): para saber si los precios argentinos son de hoy o del último cierre.
  function estadoRueda() {
    const ahora = new Date(), tz = "America/Argentina/Buenos_Aires";
    const hoy = ahora.toLocaleDateString("en-CA", { timeZone: tz });
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(ahora).map((x) => [x.type, x.value]));
    const fer = new Set(((blk(D, "feriados") || {}).ar || []).map((f) => f.fecha));
    const habil = (iso) => { const d = new Date(iso + "T12:00:00-03:00").getUTCDay(); return d !== 0 && d !== 6 && !fer.has(iso); };
    const ultimoHabil = (iso) => { let d = new Date(iso + "T12:00:00-03:00"); do { d = new Date(d.getTime() - 864e5); } while (!habil(d.toISOString().slice(0, 10))); return d.toISOString().slice(0, 10); };
    const mins = (+p.hour % 24) * 60 + +p.minute;
    if (!habil(hoy)) return `Hoy no hay rueda${fer.has(hoy) ? " (feriado)" : ""} · precios del cierre del ${dmy(ultimoHabil(hoy))}`;
    if (mins < 660) return `Antes de la apertura (11 h) · precios del cierre del ${dmy(ultimoHabil(hoy))}`;
    if (mins < 1020) return `Rueda en curso · precios con demora, actualizados ${hhmm(P.generated)} · "s/op" = no operó hoy`;
    return `Rueda cerrada · precios del cierre de hoy (${dmy(hoy)})`;
  }
  const rueda = () => `<div class="strip rueda"><span><b>BYMA</b> ${esc(estadoRueda())}</span></div>`;

  function render() {
    try { $("#view").innerHTML = VIEWS[current](); }
    catch (e) { $("#view").innerHTML = `<div class="empty">Error al dibujar la pestaña: ${esc(e.message)}</div>`; console.error(e); }
    document.querySelectorAll("nav.tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.v === current));
    const stale = [...Object.entries(P), ...Object.entries(D)].filter(([k, v]) => v && v.stale).map(([k]) => NOMBRES[k] || k);
    const prob = [...problemas(), ...sospechosos()];
    $("#status").innerHTML = `<span>Precios ${hhmm(P.generated)}</span><span>Diario ${hhmm(D.generated)}</span>`
      + (prob.length ? `<button class="alerta" title="${esc(prob.join("\n"))}" aria-label="Datos a revisar">! ${prob.length === 1 ? "1 dato a revisar" : `${prob.length} datos a revisar`}</button>`
        : stale.length ? `<span class="bad" title="${esc(stale.join(", "))}">${stale.length} fuente(s) sin responder en la última corrida</span>` : "");
  }

  async function load() {
    if (window.__SAMPLE__) { P = window.__SAMPLE__.prices; D = window.__SAMPLE__.daily; $("#sample").hidden = false; return render(); }
    // Los datos viven en la rama "datos" del repo (se reescribe en cada corrida). Si no responde, se usa la copia local.
    const owner = location.hostname.split(".")[0], repo = location.pathname.split("/")[1];
    RAW = owner && repo && location.hostname.endsWith("github.io") ? `https://raw.githubusercontent.com/${owner}/${repo}/datos/` : null;
    const bust = `?t=${Date.now()}`;
    const getJ = (u) => fetch(u + bust).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const get = async (f) => (RAW && (await getJ(RAW + f))) || (await getJ("data/" + f)) || {};
    [P, D] = await Promise.all([get("prices.json"), get("daily.json")]);
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
    const box = $("#ficha");
    if (!box.hidden && (e.target.closest(".cerrar") || e.target === box)) { box.hidden = true; return; }
    const tr = e.target.closest("tr[data-tk]"); if (tr) abrirFlujos(tr.dataset.tk);
    const te = e.target.closest("tr[data-emp]"); if (te) abrirEmpresa(te.dataset.emp);
    const ta = e.target.closest("tr[data-acc]"); if (ta) abrirAccion(ta.dataset.acc);
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#ficha").hidden = true; });
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".alerta"); if (!b) return;
    const box = $("#alertas");
    if (box.hidden) {
      const viejos = problemas(), raros = sospechosos();
      box.innerHTML = (viejos.length ? `<b>Desactualizados hace más de 2 días hábiles</b><ul>${viejos.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "")
        + (raros.length ? `<b>Valores que no tienen sentido</b><ul>${raros.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "")
        + `<div class="note">Se siguen mostrando los últimos datos. Los desactualizados desaparecen cuando la fuente vuelve a responder; los valores raros pueden ser un error de la fuente o un movimiento real fuerte: conviene chequearlos antes de usarlos.</div>`;
      box.hidden = false;
    }
    else box.hidden = true;
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
