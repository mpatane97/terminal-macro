/* Terminal: lee docs/data/*.json (generados por GitHub Actions) y arma las pestañas. Sin dependencias. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const NF = (d) => new Intl.NumberFormat("es-AR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const fmt = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "—" : NF(d).format(v));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const cls = (v) => (v === null || v === undefined ? "na" : v > 0.0001 ? "up" : v < -0.0001 ? "down" : "flat");
  const chg = (v, d = 2, suf = "%") => (v === null || v === undefined ? `<span class="na">—</span>` : `<span class="${cls(v)}">${v > 0 ? "+" : ""}${fmt(v, d)}${suf}</span>`);
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
  const table = (head, rows) => rows.length
    ? `<div class="scroll"><table><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
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
    g += xt.map((t) => `<text x="${X(t.v ?? t)}" y="${H - B + 16}" text-anchor="middle">${esc(t.l ?? fmt(t, 0))}</text>`).join("");
    g += `<text x="${(L + W - R) / 2}" y="${H - 4}" text-anchor="middle">${esc(o.xlabel || "")}</text>`;
    g += `<text x="12" y="${T + 4}" transform="rotate(-90 12 ${T + 4})" text-anchor="end">${esc(o.ylabel || "")}</text>`;
    series.forEach((s, si) => {
      const ps = s.points.filter((p) => p.x != null && p.y != null).sort((a, b) => a.x - b.x);
      if (s.line && ps.length > 1) g += `<polyline class="${s.cls}" fill="none" stroke-width="${s.ghost ? 1 : 2}" ${s.ghost ? 'stroke-dasharray="4 4"' : ""} points="${ps.map((p) => `${X(p.x)},${Y(p.y)}`).join(" ")}"/>`;
      g += ps.map((p) => `<circle class="${s.cls}" cx="${X(p.x)}" cy="${Y(p.y)}" r="${s.ghost ? 2.5 : 3.5}"><title>${esc(p.label || "")} ${fmt(p.y, 2)}%</title></circle>${p.label && !s.ghost ? `<text class="lbl" x="${X(p.x) + 5}" y="${Y(p.y) + (si % 2 ? 15 : -7)}">${esc(p.label)}</text>` : ""}`).join("");
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

  /* ---------- Fed: probabilidades de la próxima reunión ---------- */
  function fedOutlook() {
    const ev = (blk(P, "fed_probs") || [])[0];
    const fed = blk(D, "fed");
    if (!ev || !fed || !fed.rango) return null;
    const hi = fed.rango[1];
    // Supuesto: los umbrales de Kalshi KXFED se refieren al techo del rango. Tramo "desde s" = techo s+0,25.
    let cut = ev.prob_debajo || 0, hold = 0, hike = 0;
    for (const t of ev.tramos) {
      const techo = +(t.desde + 0.25).toFixed(2);
      if (techo < hi - 0.001) cut += t.prob; else if (Math.abs(techo - hi) < 0.001) hold += t.prob; else hike += t.prob;
    }
    return { ev, cut, hold, hike };
  }

  /* ---------- Vistas ---------- */
  function viewResumen() {
    const mk = blk(P, "markets") || {};
    const all = Object.values(mk).flat();
    const pick = (ids) => ids.map((id) => all.find((x) => x.id === id)).filter(Boolean);
    const cols = ["d", "m"];
    const head = ["", "Último", "Día", "Mes"];
    const tsy = (blk(D, "treasuries") || {}).curva || [];
    const fed = blk(D, "fed") || {};
    const fo = fedOutlook();
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
      .concat([["Riesgo país", fmt(rp.last, 0), chg(rp.d_pb, 0, " pb"), chg(rp.m)]])
      .concat(priceRows(pick(["MERVAL"]), cols)))
      + `<h3>Brechas y banda</h3><dl class="kv"><dt>CCL / A3500</dt><dd>${fmt(br.ccl_a3500, 1)}%</dd><dt>MEP / A3500</dt><dd>${fmt(br.mep_a3500, 1)}%</dd><dt>CCL / MEP</dt><dd>${fmt(br.ccl_mep, 1)}%</dd>
         <dt>Techo de banda</dt><dd>${ban ? fmt(ban.techo, 2) : "—"}</dd><dt>Distancia al techo</dt><dd>${ban && a3500 ? fmt((ban.techo / a3500 - 1) * 100, 1) + "%" : "—"}</dd></dl>`
      + `<h3>Bonos y tasas</h3>` + table(["", "USD", "Día", "TIR"], sob.filter((r) => ["AL30", "GD30"].includes(r.ticker)).map((r) => [r.ticker, fmt(r.usd, 2), chg(r.d), r.tir != null ? fmt(r.tir, 1) + "%" : "—"]))
      + `<dl class="kv"><dt>TAMAR</dt><dd>${fmt(bc.tamar?.valor, 2)}%</dd><dt>IPC ${esc(ip.periodo || "")}</dt><dd>${fmt(ip.mensual, 1)}% m/m · ${fmt(ip.interanual, 1)}% i.a.</dd><dt>REM 12 meses</dt><dd>${fmt(bc.rem_12m?.valor, 1)}%</dd></dl>`;

    const gl = table(head, priceRows(pick(["DXY", "EURUSD", "USDBRL", "SX5E", "N225", "BVSP", "WTI", "BRENT", "ORO", "PLATA", "SOJA", "TRIGO", "MAIZ", "BTC"]), cols));

    return `<div class="cols-3">${panel("EE.UU. y Fed", us, { lead: true, meta: meta(P, "markets") })}${panel("Argentina", ar, { meta: meta(P, "dolares") })}${panel("Global y commodities", gl, { meta: meta(P, "markets") })}</div>
      <div class="cols-2">${panel("Próximos eventos", eventsList(upcoming().slice(0, 5)), { src: "" })}${panel("Titulares", newsList(mergedNews().slice(0, 5)), { meta: meta(P, "news") })}</div>`;
  }

  function viewEEUU() {
    const fed = blk(D, "fed") || {}, fo = fedOutlook(), ts = blk(D, "treasuries") || {}, curva = ts.curva || [];
    const yrs = { "3m": 0.25, "2y": 2, "5y": 5, "10y": 10, "30y": 30 };
    const fedHtml = `<dl class="kv"><dt>Rango objetivo</dt><dd>${fed.rango ? `${fmt(fed.rango[0], 2)}–${fmt(fed.rango[1], 2)}%` : "—"}</dd>
      <dt>EFFR ${fed.effr ? `(${dmy(fed.effr.fecha)})` : ""}</dt><dd>${fmt(fed.effr?.valor, 2)}%</dd>
      <dt>Próximas reuniones</dt><dd>${(fed.fomc || []).map(dmy).join(" · ") || "—"}</dd></dl>`
      + (fo ? `<h3>Próximo FOMC según Kalshi</h3>` + table(["Escenario", "Prob."], [["Recorte", fmt(fo.cut, 0) + "%"], ["Mantener", fmt(fo.hold, 0) + "%"], ["Suba", fmt(fo.hike, 0) + "%"]])
        + `<div class="note">${esc(fo.ev.titulo || "")}. Mercado de predicción: no equivale a CME FedWatch.</div>` : `<div class="empty">Sin probabilidades de Kalshi.</div>`);
    const tsyHtml = table(["Plazo", "Tasa", "Día", "Mes", "Año"], curva.map((r) => [r.plazo, fmt(r.tasa, 2) + "%", chg(r.d_pb, 0, " pb"), chg(r.m_pb, 0, " pb"), chg(r.y_pb, 0, " pb")]))
      + `<dl class="kv"><dt>Spread 10y – 2y</dt><dd>${chg(ts.spread_10_2_pb, 0, " pb")}</dd></dl>`
      + curve([{ name: "Hoy", cls: "s1", line: true, points: curva.map((r) => ({ x: yrs[r.plazo], y: r.tasa, label: r.plazo })) },
               { name: "Hace 1 mes", cls: "ghost", line: true, ghost: true, points: curva.map((r) => ({ x: yrs[r.plazo], y: r.hace_1m })) }],
        { xfn: Math.sqrt, xmin: 0, xticks: [0.25, 2, 5, 10, 30].map((v) => ({ v, l: v < 1 ? "3m" : v + "a" })), xlabel: "Plazo", ylabel: "Rendimiento %", ydec: 2, title: "Curva de Treasuries" });
    const macro = blk(D, "us_macro") || [];
    const macroHtml = table(["Indicador", "Período", "Último", "Anterior", "Próximo"], macro.map((r) => [
      `${esc(r.nombre)}<span class="sub">${esc(r.tema)}</span>`, esc(r.periodo || "—"),
      `${fmt(r.valor, r.unidad === "miles" ? 0 : 1)}<span class="sub">${esc(r.unidad)}</span>`, fmt(r.anterior, r.unidad === "miles" ? 0 : 1), dmy(r.proximo)]));
    return `<div class="cols-2">${panel("Fed", fedHtml, { lead: true, meta: meta(D, "fed") })}${panel("Treasuries", tsyHtml, { meta: meta(D, "treasuries") })}</div>
      ${panel("Macro EE.UU.", macroHtml, { meta: meta(D, "us_macro") })}`;
  }

  function viewArgentina() {
    const dol = blk(P, "dolares") || {}, cot = dol.cotizaciones || [], br = dol.brechas || {};
    const ban = blk(D, "bandas"), arm = blk(P, "ar_market") || {}, bc = blk(D, "ar_bcra") || {};
    const rp = blk(D, "riesgo_pais") || {}, ip = blk(D, "ipc") || {};
    const a3500 = byId(cot, "mayorista").venta;
    const dolHtml = table(["", "Compra", "Venta", "Día", "Sem", "Mes", "Año"], cot.filter((r) => r.id !== "oficial").map((r) => [esc(r.nombre), fmt(r.compra, 2), fmt(r.venta, 2), chg(r.d), chg(r.w), chg(r.m), chg(r.y)]))
      + `<h3>Brechas y banda</h3><dl class="kv"><dt>CCL / A3500</dt><dd>${fmt(br.ccl_a3500, 1)}%</dd><dt>MEP / A3500</dt><dd>${fmt(br.mep_a3500, 1)}%</dd><dt>CCL / MEP</dt><dd>${fmt(br.ccl_mep, 1)}%</dd>
        <dt>Piso / techo ${ban ? `(${dmy(ban.fecha)})` : ""}</dt><dd>${ban ? `${fmt(ban.piso, 2)} / ${fmt(ban.techo, 2)}` : "—"}</dd><dt>Distancia al techo</dt><dd>${ban && a3500 ? fmt((ban.techo / a3500 - 1) * 100, 1) + "%" : "—"}</dd></dl>`;

    const sobRows = (arr) => arr.map((r) => [`${r.ticker}<span class="sub">${r.ley || ""}</span>`, fmt(r.usd, 2), fmt(r.ars, 0), chg(r.d), chg(r.m), r.tir != null ? fmt(r.tir, 2) + "%" : "—", fmt(r.dur_mod, 2), fmt(r.paridad, 1)]);
    const sob = arm.soberanos || [], bop = arm.bopreal || [];
    const sobHtml = table(["Bono", "USD", "ARS", "Día", "Mes", "TIR", "Dur. mod.", "Paridad"], sobRows(sob))
      + `<h3>BOPREAL</h3>` + table(["Bono", "USD", "ARS", "Día", "Mes", "TIR", "Dur. mod.", "Paridad"], sobRows(bop))
      + curve([{ name: "Ley NY (GD)", cls: "s1", line: true, points: sob.filter((r) => r.ley === "NY" && r.tir != null).map((r) => ({ x: r.dur_mod, y: r.tir, label: r.ticker })) },
               { name: "Ley local (AL/AE)", cls: "s2", line: true, points: sob.filter((r) => r.ley === "Local" && r.tir != null).map((r) => ({ x: r.dur_mod, y: r.tir, label: r.ticker })) }],
        { xlabel: "Duration modificada (años)", ylabel: "TIR %", title: "Curva de soberanos en USD" })
      + `<div class="note">TIR calculada con precio en MEP y liquidación ${dmy(arm.liquidacion)}. Flujos cargados de las condiciones de emisión: validar contra otra fuente.</div>`;

    const pf = arm.pesos_fija || [];
    const pesosHtml = table(["Letra/bono", "Tipo", "Vto.", "Días", "Precio", "Día", "TEM", "TIREA"], pf.map((r) => [r.ticker, r.tipo, dmy(r.vto), r.dias, fmt(r.precio, 2), chg(r.d), r.tem != null ? fmt(r.tem, 2) + "%" : "—", r.tirea != null ? fmt(r.tirea, 1) + "%" : "—"]))
      + (pf.some((r) => r.tem != null)
        ? curve([{ name: "Tasa fija", cls: "s1", line: true, points: pf.filter((r) => r.tem != null).map((r) => ({ x: r.dias, y: r.tem, label: r.ticker })) }], { xlabel: "Días al vencimiento", ylabel: "TEM %", ydec: 2, title: "Curva de tasa fija" })
        : `<div class="note">La TEM y la curva aparecen cuando se carga el pago final de cada letra en config/bonos.json.</div>`)
      + `<h3>CER y TAMAR</h3>` + table(["Bono", "Precio", "Día"], (arm.cer_tamar || []).map((r) => [r.ticker, fmt(r.precio, 2), chg(r.d)]));

    const tasas = [["TAMAR", bc.tamar], ["BADLAR", bc.badlar], ["Plazo fijo 30 d", bc.plazo_fijo]];
    const tasasHtml = table(["", "TNA", "Fecha"], tasas.map(([n, v]) => [n, v ? fmt(v.valor, 2) + "%" : "—", dmy(v?.fecha)]))
      + `<dl class="kv"><dt>CER ${bc.cer ? `(${dmy(bc.cer.fecha)})` : ""}</dt><dd>${fmt(bc.cer?.valor, 4)}</dd><dt>UVA ${bc.uva ? `(${dmy(bc.uva.fecha)})` : ""}</dt><dd>${fmt(bc.uva?.valor, 2)}</dd></dl>`;

    const accHtml = table(["", "Precio", "Día", "Sem", "Mes"], [["Merval", ...(() => { const m = ((blk(P, "markets") || {}).argentina || [])[0] || {}; return [fmt(m.last, 0), chg(m.d), chg(m.w), chg(m.m)]; })()]]
      .concat((arm.acciones || []).map((r) => [r.ticker, fmt(r.precio, 2), chg(r.d), chg(r.w), chg(r.m)])))
      + `<h3>CEDEARs</h3>` + table(["", "Precio", "Día", "Mes", "MEP impl.", "CCL impl."], (arm.cedears || []).map((r) => [r.ticker, fmt(r.precio, 2), chg(r.d), chg(r.m), fmt(r.mep, 2), fmt(r.ccl, 2)]));

    const macroHtml = `<dl class="kv"><dt>Riesgo país (${dmy(rp.date)})</dt><dd>${fmt(rp.last, 0)} pb ${chg(rp.d_pb, 0, " pb")}</dd>
      <dt>IPC ${esc(ip.periodo || "")} mensual</dt><dd>${fmt(ip.mensual, 1)}%</dd><dt>IPC interanual</dt><dd>${fmt(ip.interanual, 1)}%</dd>
      <dt>REM inflación 12 meses</dt><dd>${fmt(bc.rem_12m?.valor, 1)}%</dd>
      <dt>Reservas brutas (${dmy(bc.reservas?.fecha)})</dt><dd>US$ ${fmt(bc.reservas?.valor, 0)} M ${chg(bc.reservas?.m)}</dd>
      <dt>Compras BCRA (${dmy(bc.compras?.fecha)})</dt><dd>US$ ${fmt(bc.compras?.valor, 0)} M · mes ${fmt(bc.compras?.mes_acum, 0)} M</dd></dl>`;

    return `<div class="cols-2">${panel("Dólares", dolHtml, { lead: true, meta: meta(P, "dolares") })}${panel("Macro y BCRA", macroHtml + `<h3>Tasas</h3>` + tasasHtml, { meta: meta(D, "ar_bcra") })}</div>
      ${panel("Soberanos en USD", sobHtml, { meta: meta(P, "ar_market") })}
      <div class="cols-2">${panel("Bonos en pesos", pesosHtml, { meta: meta(P, "ar_market") })}${panel("Acciones y CEDEARs", accHtml, { meta: meta(P, "ar_market") })}</div>`;
  }

  function viewMercados() {
    const mk = blk(P, "markets") || {};
    const head = ["", "Último", ...Object.values(VARS)];
    const g = (k) => table(head, priceRows(mk[k], Object.keys(VARS)));
    const m = meta(P, "markets");
    return `<div class="cols-2">${panel("EE.UU.", g("indices_eeuu") + `<h3>Futuros</h3>` + g("futuros") + `<h3>Volatilidad</h3>` + g("volatilidad"), { lead: true, meta: m })}
      ${panel("Resto del mundo", g("indices_mundo"), { meta: m })}</div>
      <div class="cols-2">${panel("Monedas", g("monedas"), { meta: m })}${panel("Commodities y cripto", g("commodities") + `<h3>Cripto</h3>` + g("cripto"), { meta: m })}</div>`;
  }

  function upcoming() {
    const now = new Date().toISOString();
    const ev = [];
    for (const r of blk(D, "calendar_us") || []) if ((r.fecha || "") >= now.slice(0, 10)) ev.push({ t: r.fecha, txt: `EE.UU. · ${r.evento}${r.esperado ? ` · esp. ${r.esperado}` : ""}${r.previo ? ` · prev. ${r.previo}` : ""}`, imp: r.impacto });
    for (const r of blk(D, "calendar_ar") || []) ev.push({ t: `${r.fecha}T${r.hora || "00:00"}:00-03:00`, txt: `Argentina · ${r.evento}`, imp: "High" });
    for (const f of (blk(D, "fed") || {}).fomc || []) ev.push({ t: `${f}T15:00:00-03:00`, txt: "Fed · Decisión FOMC", imp: "High" });
    return ev.filter((e) => e.t >= now.slice(0, 10)).sort((a, b) => (a.t < b.t ? -1 : 1));
  }
  function eventsList(ev) {
    return ev.length ? `<ul class="events">${ev.map((e) => `<li><span class="t">${hhmm(e.t)}</span><span class="imp-${esc(e.imp)}">${esc(e.txt)}</span></li>`).join("")}</ul>` : `<div class="empty">Sin eventos cargados.</div>`;
  }
  function mergedNews() { const n = blk(P, "news") || {}; return [...(n.eeuu || []), ...(n.argentina || [])].sort((a, b) => ((a.hora || "") < (b.hora || "") ? 1 : -1)); }
  function newsList(items) {
    return items.length ? `<ul class="news">${items.map((n) => `<li><span class="t">${hhmm(n.hora)}</span><span><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.titulo)}</a> <span class="f">${esc(n.fuente)}</span></span></li>`).join("")}</ul>` : `<div class="empty">Sin titulares.</div>`;
  }

  function viewCalendario() {
    const us = blk(D, "calendar_us") || [];
    const usHtml = table(["Fecha", "Dato", "Impacto", "Esperado", "Previo"], us.map((r) => [hhmm(r.fecha), esc(r.evento), r.impacto === "High" ? "Alto" : "Medio", esc(r.esperado || "—"), esc(r.previo || "—")]));
    const arHtml = table(["Fecha", "Evento"], (blk(D, "calendar_ar") || []).map((r) => [dmy(r.fecha) + (r.hora ? ` ${r.hora}` : ""), esc(r.evento)]));
    const fedHtml = table(["Fecha", "Reunión"], ((blk(D, "fed") || {}).fomc || []).map((f) => [dmy(f), "Decisión FOMC"]));
    const earnHtml = table(["Fecha", "Empresa", "Momento", "EPS est."], (blk(D, "earnings") || []).map((r) => [dmy(r.fecha), r.ticker, esc(r.hora || "—"), fmt(r.eps_estimado, 2)]));
    const n = blk(P, "news") || {};
    return `<div class="cols-2">${panel("Datos de EE.UU. · esta semana", usHtml, { lead: true, meta: meta(D, "calendar_us") })}${panel("Earnings · próximas 2 semanas", earnHtml, { meta: meta(D, "earnings") })}</div>
      <div class="cols-2">${panel("Argentina", arHtml, { meta: meta(D, "calendar_ar") })}${panel("Fed", fedHtml, { meta: meta(D, "fed") })}</div>
      <div class="cols-2">${panel("Noticias EE.UU.", newsList(n.eeuu || []), { meta: meta(P, "news") })}${panel("Noticias Argentina", newsList(n.argentina || []), { meta: meta(P, "news") })}</div>`;
  }

  const VIEWS = { resumen: viewResumen, eeuu: viewEEUU, argentina: viewArgentina, mercados: viewMercados, calendario: viewCalendario };
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

  document.addEventListener("click", (e) => {
    const b = e.target.closest("nav.tabs button"); if (!b) return;
    current = b.dataset.v; try { history.replaceState(null, "", "#" + current); } catch {}
    render();
  });
  const h = location.hash.slice(1); if (VIEWS[h]) current = h;
  load();
  setInterval(load, 5 * 60 * 1000);
})();
