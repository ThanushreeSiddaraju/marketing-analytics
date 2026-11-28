// Draws every chart on the page from data/site.json. Plain SVG, no libraries.
(() => {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const $ = (id) => document.getElementById(id);

  // ---------------------------------------------------------------- formatting
  const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
  const fmt = {
    int: (v) => nf0.format(v),
    money: (v) => "$" + nf0.format(v),
    moneyK: (v) => (Math.abs(v) >= 1e6 ? "$" + (v / 1e6).toFixed(2) + "M" : Math.abs(v) >= 1e4 ? "$" + (v / 1e3).toFixed(1) + "k" : "$" + nf0.format(v)),
    pct: (v, d = 1) => (v * 100).toFixed(d) + "%",
    x: (v) => v.toFixed(2) + "x",
    num: (v, d = 2) => Number(v).toFixed(d),
  };
  const trim = (v) => String(+v.toFixed(2));
  const tickFmt = (v, kind) => {
    if (kind === "money") return v >= 1e3 ? "$" + trim(v / 1e3) + "k" : "$" + trim(v);
    if (kind === "pct") return trim(v * 100) + "%";
    if (kind === "x") return trim(v) + "x";
    return v >= 1e4 ? trim(v / 1e3) + "k" : trim(v);
  };
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const SERIES = ["--s1", "--s2", "--s3"];

  // ---------------------------------------------------------------- svg helpers
  function el(tag, attrs = {}, parent) {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }
  function text(parent, x, y, str, attrs = {}) {
    const t = el("text", { x, y, ...attrs }, parent);
    t.textContent = str;
    return t;
  }
  function makeSvg(container, height, label) {
    container.innerHTML = "";
    const w = Math.max(160, container.clientWidth);
    const s = el("svg", { viewBox: `0 0 ${w} ${height}`, role: "img", "aria-label": label }, container);
    return { s, w };
  }
  // A bar with a 4px rounded data end and a square end at the baseline.
  function hBarPath(x, y, w, h, r = 4) {
    r = Math.min(r, w, h / 2);
    if (w <= 0) return "";
    return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
  }
  function vBarPath(x, y0, w, h, r = 4) {
    r = Math.min(r, h, w / 2);
    if (h <= 0) return "";
    const y = y0 - h;
    return `M${x},${y0}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y0}Z`;
  }
  // Round tick steps (1, 2, 2.5 or 5 times a power of ten) and a top that's a whole number of steps.
  function niceStep(max, n) {
    const raw = max / n, p = Math.pow(10, Math.floor(Math.log10(raw)));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= raw - 1e-12) return m * p;
    return 10 * p;
  }
  function niceMax(v, n = 4) { const st = niceStep(v, n); return Math.ceil(v / st - 1e-9) * st; }
  function ticks(max, n = 4) {
    const st = niceStep(max, n), out = [];
    for (let t = 0; t <= max + st * 1e-6; t += st) out.push(+t.toFixed(10));
    return out;
  }
  function measure(svg, strs) {
    const t = text(svg, 0, -100, "");
    let m = 0;
    for (const s of strs) { t.textContent = s; m = Math.max(m, t.getComputedTextLength()); }
    t.remove();
    return m;
  }

  // ---------------------------------------------------------------- tooltip
  const tip = $("tip");
  function showTip(evt, html) {
    tip.innerHTML = html;
    tip.hidden = false;
    const pad = 14, r = tip.getBoundingClientRect();
    let x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + r.width > innerWidth - 8) x = evt.clientX - r.width - pad;
    if (y + r.height > innerHeight - 8) y = evt.clientY - r.height - pad;
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = Math.max(8, y) + "px";
  }
  const hideTip = () => { tip.hidden = true; };
  const swatch = (color, shape = "square") => {
    const inner = shape === "line" ? `<rect x="0" y="4" width="12" height="2" rx="1" fill="${color}"/>`
      : shape === "circle" ? `<circle cx="5" cy="5" r="4.5" fill="${color}"/>`
      : shape === "diamond" ? `<rect x="2" y="2" width="6" height="6" transform="rotate(45 5 5)" fill="${color}"/>`
      : `<rect x="1" y="1" width="8" height="8" rx="2" fill="${color}"/>`;
    return `<svg width="${shape === "line" ? 12 : 10}" height="10" aria-hidden="true">${inner}</svg>`;
  };
  const tipRow = (color, label, value, shape) => `<div class="row">${color ? swatch(color, shape) : ""}<span>${label}</span><span>${value}</span></div>`;
  function hover(node, html) {
    node.addEventListener("pointermove", (e) => showTip(e, html()));
    node.addEventListener("pointerdown", (e) => showTip(e, html()));
    node.addEventListener("pointerleave", hideTip);
  }
  function legend(container, items) {
    container.innerHTML = items.map((i) => `<span>${swatch(css(i.color), i.shape)}${i.label}</span>`).join("");
  }

  // ---------------------------------------------------------------- tables
  function table(container, cols, rows) {
    // Text columns line up on the left, numbers on the right.
    const isText = cols.map((c) => rows.every((r) => r[c.key] == null || typeof r[c.key] === "string"));
    const cls = (i) => (isText[i] ? ' class="t"' : "");
    const head = cols.map((c, i) => `<th scope="col"${cls(i)}>${c.label}</th>`).join("");
    const body = rows.map((r) => "<tr>" + cols.map((c, i) => {
      const v = r[c.key];
      return `<td${cls(i)}>${v === null || v === undefined ? "–" : c.fmt ? c.fmt(v) : v}</td>`;
    }).join("") + "</tr>").join("");
    container.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  }

  // ---------------------------------------------------------------- chart: horizontal bars
  function hbar(container, rows, o) {
    const barH = 18, gap = 14, top = 6, bottom = 26;
    const h = top + rows.length * (barH + gap) - gap + bottom;
    const { s, w } = makeSvg(container, h, o.title);
    const labelW = Math.ceil(measure(s, rows.map((r) => r[o.label]))) + 12;
    const valueW = Math.ceil(measure(s, rows.map((r) => o.fmt(r[o.value])))) + 10;
    const x0 = labelW, plotW = w - labelW - valueW;
    const max = niceMax(o.max || Math.max(...rows.map((r) => r[o.value])));
    const sx = (v) => (v / max) * plotW;
    for (const t of ticks(max)) {
      el("line", { x1: x0 + sx(t), x2: x0 + sx(t), y1: top - 4, y2: h - bottom + 4, class: t === 0 ? "axis" : "grid" }, s);
      text(s, x0 + sx(t), h - 8, tickFmt(t, o.tick), { class: "tick", "text-anchor": t === 0 ? "start" : "middle" });
    }
    if (o.ref !== undefined) {
      el("line", { x1: x0 + sx(o.ref), x2: x0 + sx(o.ref), y1: top - 4, y2: h - bottom + 4, class: "axis", "stroke-width": 1.5 }, s);
    }
    rows.forEach((r, i) => {
      const y = top + i * (barH + gap);
      text(s, 0, y + barH / 2 + 4, r[o.label]);
      const g = el("g", {}, s);
      el("rect", { x: 0, y: y - gap / 2, width: w, height: barH + gap, class: "hit" }, g);
      el("path", { d: hBarPath(x0, y, sx(r[o.value]), barH), fill: css(o.color || "--s1"), class: "mark" }, g);
      text(s, x0 + sx(r[o.value]) + 6, y + barH / 2 + 4, o.fmt(r[o.value]), { class: "value" });
      hover(g, () => `<b>${r[o.label]}</b>` + (o.tip ? o.tip(r) : tipRow(null, o.valueLabel || "", o.fmt(r[o.value]))));
    });
  }

  // ---------------------------------------------------------------- chart: paired horizontal bars
  function pairedBars(container, rows, o) {
    const barH = 14, inner = 2, gap = 16, top = 6, bottom = 26;
    const groupH = barH * 2 + inner;
    const h = top + rows.length * (groupH + gap) - gap + bottom;
    const { s, w } = makeSvg(container, h, o.title);
    const labelW = Math.ceil(measure(s, rows.map((r) => r[o.label]))) + 12;
    const valueW = Math.ceil(measure(s, rows.flatMap((r) => o.keys.map((k) => o.fmt(r[k.key]))))) + 10;
    const x0 = labelW, plotW = w - labelW - valueW;
    const max = niceMax(Math.max(...rows.flatMap((r) => o.keys.map((k) => r[k.key]))));
    const sx = (v) => (v / max) * plotW;
    for (const t of ticks(max)) {
      el("line", { x1: x0 + sx(t), x2: x0 + sx(t), y1: top - 4, y2: h - bottom + 4, class: t === 0 ? "axis" : "grid" }, s);
      text(s, x0 + sx(t), h - 8, tickFmt(t, o.tick), { class: "tick", "text-anchor": t === 0 ? "start" : "middle" });
    }
    rows.forEach((r, i) => {
      const y = top + i * (groupH + gap);
      text(s, 0, y + groupH / 2 + 4, r[o.label]);
      const g = el("g", {}, s);
      el("rect", { x: 0, y: y - gap / 2, width: w, height: groupH + gap, class: "hit" }, g);
      o.keys.forEach((k, j) => {
        const yy = y + j * (barH + inner);
        el("path", { d: hBarPath(x0, yy, sx(r[k.key]), barH), fill: css(k.color), class: "mark" }, g);
        text(s, x0 + sx(r[k.key]) + 6, yy + barH / 2 + 4, o.fmt(r[k.key]), { class: "value" });
      });
      hover(g, () => `<b>${r[o.label]}</b>` + o.keys.map((k) => tipRow(css(k.color), k.label, o.fmt(r[k.key]))).join("") + (o.tipExtra ? o.tipExtra(r) : ""));
    });
  }

  // ---------------------------------------------------------------- chart: columns
  function columns(container, rows, o) {
    const h = 220, top = 18, bottom = 40, left = 40;
    const { s, w } = makeSvg(container, h, o.title);
    const plotW = w - left - 4, plotH = h - top - bottom;
    const max = niceMax(Math.max(...rows.map((r) => r[o.value])));
    const sy = (v) => (v / max) * plotH;
    const y0 = top + plotH;
    for (const t of ticks(max)) {
      el("line", { x1: left, x2: w, y1: y0 - sy(t), y2: y0 - sy(t), class: t === 0 ? "axis" : "grid" }, s);
      text(s, left - 6, y0 - sy(t) + 4, tickFmt(t, o.tick), { class: "tick", "text-anchor": "end" });
    }
    const band = plotW / rows.length, bw = Math.min(24, band - 6);
    if (o.ref !== undefined) {
      el("line", { x1: left, x2: w, y1: y0 - sy(o.ref), y2: y0 - sy(o.ref), class: "axis", "stroke-width": 1.5 }, s);
      text(s, w, y0 - sy(o.ref) - 5, o.refLabel, { class: "tick", "text-anchor": "end" });
    }
    rows.forEach((r, i) => {
      const cx = left + band * i + band / 2;
      const g = el("g", {}, s);
      el("rect", { x: cx - band / 2, y: top, width: band, height: plotH, class: "hit" }, g);
      el("path", { d: vBarPath(cx - bw / 2, y0, bw, sy(r[o.value])), fill: css("--s1"), class: "mark" }, g);
      text(s, cx, h - bottom + 16, r[o.label], { class: "tick", "text-anchor": "middle" });
      hover(g, () => o.tip(r));
    });
    text(s, left + plotW / 2, h - 4, o.xTitle, { class: "tick", "text-anchor": "middle" });
  }

  // ---------------------------------------------------------------- chart: lines with crosshair
  function lines(container, xs, series, o) {
    const h = o.height || 260, top = 12, bottom = 28, left = o.left || 48, right = 12;
    const { s, w } = makeSvg(container, h, o.title);
    const plotW = w - left - right, plotH = h - top - bottom, y0 = top + plotH;
    const max = niceMax(o.max || Math.max(...series.flatMap((se) => se.values)), o.ticks || 4);
    const sx = (i) => left + (xs.length === 1 ? plotW / 2 : (i / (xs.length - 1)) * plotW);
    const sy = (v) => y0 - (v / max) * plotH;
    for (const t of ticks(max, o.ticks || 4)) {
      el("line", { x1: left, x2: w - right, y1: sy(t), y2: sy(t), class: t === 0 ? "axis" : "grid" }, s);
      text(s, left - 6, sy(t) + 4, tickFmt(t, o.tick), { class: "tick", "text-anchor": "end" });
    }
    const every = Math.ceil(xs.length / Math.max(2, Math.floor(plotW / 60)));
    const show = o.xTicks ? new Set(o.xTicks) : null;
    xs.forEach((x, i) => {
      if (show ? show.has(i) : i % every === 0 || i === xs.length - 1) text(s, sx(i), h - 8, o.xFmt ? o.xFmt(x) : x, { class: "tick", "text-anchor": i === 0 ? "start" : i === xs.length - 1 ? "end" : "middle" });
    });
    for (const se of series) {
      const d = se.values.map((v, i) => `${i ? "L" : "M"}${sx(i).toFixed(1)},${sy(v).toFixed(1)}`).join("");
      if (se.area) el("path", { d: `${d}L${sx(se.values.length - 1)},${y0}L${sx(0)},${y0}Z`, fill: css(se.color), "fill-opacity": 0.1 }, s);
      el("path", { d, fill: "none", stroke: css(se.color), "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, s);
      if (se.endLabel) {
        const i = se.values.length - 1;
        el("circle", { cx: sx(i), cy: sy(se.values[i]), r: 4, fill: css(se.color), stroke: css("--surface"), "stroke-width": 2 }, s);
      }
    }
    for (const m of o.markers || []) {
      el("circle", { cx: left + (m.x / o.xMax) * plotW, cy: sy(m.y), r: 4.5, fill: css(m.color), stroke: css("--surface"), "stroke-width": 2 }, s);
    }
    const cross = el("line", { y1: top, y2: y0, class: "crosshair", visibility: "hidden" }, s);
    const dots = series.map((se) => el("circle", { r: 4, fill: css(se.color), stroke: css("--surface"), "stroke-width": 2, visibility: "hidden" }, s));
    const hit = el("rect", { x: left, y: top, width: plotW, height: plotH, class: "hit" }, s);
    const pick = (e) => {
      const r = s.getBoundingClientRect();
      const px = ((e.clientX - r.left) / r.width) * w;
      return Math.max(0, Math.min(xs.length - 1, Math.round(((px - left) / plotW) * (xs.length - 1))));
    };
    const move = (e) => {
      const i = pick(e);
      cross.setAttribute("x1", sx(i)); cross.setAttribute("x2", sx(i)); cross.setAttribute("visibility", "visible");
      dots.forEach((d, j) => { d.setAttribute("cx", sx(i)); d.setAttribute("cy", sy(series[j].values[i])); d.setAttribute("visibility", "visible"); });
      showTip(e, `<b>${o.tipX ? o.tipX(xs[i]) : xs[i]}</b>` + series.map((se) => tipRow(css(se.color), se.name, o.fmt(se.values[i]), "line")).join(""));
    };
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", () => { hideTip(); cross.setAttribute("visibility", "hidden"); dots.forEach((d) => d.setAttribute("visibility", "hidden")); });
  }

  // ---------------------------------------------------------------- chart: dot plot
  const SHAPES = ["circle", "square", "diamond"];
  function marker(parent, shape, x, y, color) {
    const ring = { stroke: css("--surface"), "stroke-width": 2, fill: color };
    if (shape === "circle") return el("circle", { cx: x, cy: y, r: 5, ...ring }, parent);
    if (shape === "square") return el("rect", { x: x - 5, y: y - 5, width: 10, height: 10, rx: 2, ...ring }, parent);
    return el("rect", { x: x - 4.5, y: y - 4.5, width: 9, height: 9, transform: `rotate(45 ${x} ${y})`, ...ring }, parent);
  }
  function dotPlot(container, rows, o) {
    const rowH = 30, top = 8, bottom = 26;
    const h = top + rows.length * rowH + bottom;
    const { s, w } = makeSvg(container, h, o.title);
    const labelW = Math.ceil(measure(s, rows.map((r) => r[o.label]))) + 14;
    const x0 = labelW, plotW = w - labelW - 12;
    const max = niceMax(Math.max(...rows.flatMap((r) => o.keys.map((k) => r[k.key]))));
    const sx = (v) => x0 + (v / max) * plotW;
    for (const t of ticks(max)) {
      el("line", { x1: sx(t), x2: sx(t), y1: top, y2: h - bottom + 4, class: t === 0 ? "axis" : "grid" }, s);
      text(s, sx(t), h - 8, tickFmt(t, o.tick), { class: "tick", "text-anchor": t === 0 ? "start" : "middle" });
    }
    rows.forEach((r, i) => {
      const y = top + i * rowH + rowH / 2;
      text(s, 0, y + 4, r[o.label]);
      const vals = o.keys.map((k) => r[k.key]);
      const g = el("g", {}, s);
      el("rect", { x: 0, y: y - rowH / 2, width: w, height: rowH, class: "hit" }, g);
      el("line", { x1: sx(Math.min(...vals)), x2: sx(Math.max(...vals)), y1: y, y2: y, class: "axis", "stroke-width": 2 }, g);
      o.keys.forEach((k, j) => marker(g, SHAPES[j], sx(r[k.key]), y, css(k.color)));
      hover(g, () => `<b>${r[o.label]}</b>` + o.keys.map((k, j) => tipRow(css(k.color), k.label, o.fmt(r[k.key]), SHAPES[j])).join(""));
    });
  }

  // ---------------------------------------------------------------- chart: estimates with intervals
  function intervalPlot(container, rows, o) {
    // On narrow screens long labels go above each row instead of beside it.
    const stacked = !o.noLabels && container.clientWidth < 560;
    const rowH = o.rowH || (stacked ? 48 : 34), top = 8, bottom = 26;
    const h = top + rows.length * rowH + bottom;
    const { s, w } = makeSvg(container, h, o.title);
    const labelW = o.noLabels || stacked ? 0 : Math.ceil(measure(s, rows.map((r) => r.label))) + 14;
    const valueW = Math.ceil(measure(s, rows.map((r) => o.fmt(r.est)))) + 10;
    const x0 = labelW, plotW = w - labelW - valueW;
    let lo = Math.min(0, ...rows.map((r) => r.lo)), hi = Math.max(0, ...rows.map((r) => r.hi));
    const st = niceStep(hi - lo, 4);
    lo = Math.floor(lo / st + 1e-9) * st; hi = Math.ceil(hi / st - 1e-9) * st;
    const sx = (v) => x0 + ((v - lo) / (hi - lo)) * plotW;
    for (let t = lo; t <= hi + st * 1e-6; t += st) {
      const tv = +t.toFixed(10);
      el("line", { x1: sx(tv), x2: sx(tv), y1: top, y2: h - bottom + 4, class: Math.abs(tv) < 1e-12 ? "axis" : "grid", "stroke-width": Math.abs(tv) < 1e-12 ? 1.5 : 1 }, s);
      text(s, sx(tv), h - 8, o.tickFmt(tv), { class: "tick", "text-anchor": "middle" });
    }
    rows.forEach((r, i) => {
      const y = top + i * rowH + (stacked ? rowH - 14 : rowH / 2);
      if (stacked) text(s, 0, y - 14, r.label);
      else if (!o.noLabels) text(s, 0, y + 4, r.label);
      const g = el("g", {}, s);
      el("rect", { x: 0, y: stacked ? y - rowH + 14 : y - rowH / 2, width: w, height: rowH, class: "hit" }, g);
      const col = css(r.color || "--s1");
      el("line", { x1: sx(r.lo), x2: sx(r.hi), y1: y, y2: y, stroke: col, "stroke-width": 2, "stroke-linecap": "round" }, g);
      for (const v of [r.lo, r.hi]) el("line", { x1: sx(v), x2: sx(v), y1: y - 5, y2: y + 5, stroke: col, "stroke-width": 2, "stroke-linecap": "round" }, g);
      marker(g, r.shape || "circle", sx(r.est), y, col);
      text(s, Math.max(sx(r.hi), sx(r.est)) + 8, y + 4, o.fmt(r.est), { class: "value" });
      hover(g, () => `<b>${r.tipTitle || r.label}</b>` + tipRow(null, o.estLabel || "Estimate", o.fmt(r.est)) +
        tipRow(null, "95% interval", `${o.fmt(r.lo)} to ${o.fmt(r.hi)}`) + (r.tipExtra || ""));
    });
  }

  // ---------------------------------------------------------------- chart: history then forecast with a range
  function forecastChart(container, rows, o) {
    const h = 240, top = 12, bottom = 28, left = 44, right = 12;
    const { s, w } = makeSvg(container, h, o.title);
    const plotW = w - left - right, plotH = h - top - bottom, y0 = top + plotH;
    const max = niceMax(Math.max(...rows.map((r) => Math.max(r.actual ?? 0, r.high_80 ?? 0))));
    const n = rows.length;
    const sx = (i) => left + (i / (n - 1)) * plotW;
    const sy = (v) => y0 - (v / max) * plotH;
    for (const t of ticks(max)) {
      el("line", { x1: left, x2: w - right, y1: sy(t), y2: sy(t), class: t === 0 ? "axis" : "grid" }, s);
      text(s, left - 6, sy(t) + 4, tickFmt(t), { class: "tick", "text-anchor": "end" });
    }
    const label = (d) => new Date(d + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
    const every = Math.ceil(n / Math.max(2, Math.floor(plotW / 70)));
    rows.forEach((r, i) => { if (i % every === 0) text(s, sx(i), h - 8, label(r.week_ending), { class: "tick", "text-anchor": i === 0 ? "start" : "middle" }); });
    const first = rows.findIndex((r) => r.forecast != null);
    const last = first - 1;
    el("line", { x1: sx(last), x2: sx(last), y1: top, y2: y0, class: "grid", "stroke-dasharray": "3 3" }, s);
    text(s, sx(last) + 6, top + 10, "forecast", { class: "tick" });
    const fIdx = [last, ...rows.map((_, i) => i).filter((i) => i >= first)];
    const fVal = (i, k) => (i === last ? rows[i].actual : rows[i][k]);
    const band = fIdx.map((i) => `${sx(i)},${sy(fVal(i, "high_80"))}`).join(" ") + " " +
      [...fIdx].reverse().map((i) => `${sx(i)},${sy(fVal(i, "low_80"))}`).join(" ");
    el("polygon", { points: band, fill: css("--s2"), "fill-opacity": 0.14 }, s);
    const path = (idx, key) => idx.map((i, k) => `${k ? "L" : "M"}${sx(i).toFixed(1)},${sy(key(i)).toFixed(1)}`).join("");
    const hist = rows.map((_, i) => i).filter((i) => rows[i].actual != null);
    el("path", { d: path(hist, (i) => rows[i].actual), fill: "none", stroke: css("--s1"), "stroke-width": 2, "stroke-linejoin": "round" }, s);
    el("path", { d: path(fIdx, (i) => fVal(i, "forecast")), fill: "none", stroke: css("--s2"), "stroke-width": 2, "stroke-linejoin": "round" }, s);
    const cross = el("line", { y1: top, y2: y0, class: "crosshair", visibility: "hidden" }, s);
    const dot = el("circle", { r: 4, stroke: css("--surface"), "stroke-width": 2, visibility: "hidden" }, s);
    const hit = el("rect", { x: left, y: top, width: plotW, height: plotH, class: "hit" }, s);
    const move = (e) => {
      const r0 = s.getBoundingClientRect();
      const i = Math.max(0, Math.min(n - 1, Math.round((((e.clientX - r0.left) / r0.width) * w - left) / plotW * (n - 1))));
      const r = rows[i], isF = r.forecast != null, v = isF ? r.forecast : r.actual;
      cross.setAttribute("x1", sx(i)); cross.setAttribute("x2", sx(i)); cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", sx(i)); dot.setAttribute("cy", sy(v)); dot.setAttribute("fill", css(isF ? "--s2" : "--s1")); dot.setAttribute("visibility", "visible");
      showTip(e, `<b>Week ending ${label(r.week_ending)}</b>` + (isF
        ? tipRow(css("--s2"), "Forecast", fmt.int(r.forecast), "line") + tipRow(null, "80% range", `${fmt.int(r.low_80)} to ${fmt.int(r.high_80)}`)
        : tipRow(css("--s1"), "Leads", fmt.int(r.actual), "line")));
    };
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", () => { hideTip(); cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); });
  }

  // ---------------------------------------------------------------- page
  let D;
  function kpis() {
    const k = D.kpi;
    const tiles = [
      ["Ad spend", fmt.moneyK(k.total_spend), "all channels"],
      ["Leads", fmt.int(k.leads), fmt.pct(k.visit_to_lead) + " of visits"],
      ["Paying customers", fmt.int(k.customers), fmt.pct(k.lead_to_customer) + " of leads"],
      ["Revenue collected", fmt.moneyK(k.revenue), "in 2025"],
      ["Return on ad spend", fmt.x(k.paid_roas), "first-year revenue / spend"],
      ["Cost per customer", fmt.money(k.paid_cac), "channels with spend"],
    ];
    $("kpis").innerHTML = tiles.map(([l, v, n]) => `<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div><div class="note">${n}</div></div>`).join("");
  }

  function render() {
    const paid = D.channels.filter((c) => c.spend > 0).sort((a, b) => a.cac - b.cac);
    hbar($("chart-cac"), paid, {
      title: "Cost per customer by channel", label: "channel", value: "cac", fmt: fmt.money, tick: "money",
      tip: (r) => tipRow(null, "Cost per customer", fmt.money(r.cac)) + tipRow(null, "Spend", fmt.moneyK(r.spend)) +
        tipRow(null, "Customers", fmt.int(r.customers)) + tipRow(null, "Return in year 1", fmt.x(r.roas)) +
        tipRow(null, "Lifetime value / cost", r.ltv_to_cac == null ? "–" : r.ltv_to_cac.toFixed(1)),
    });

    const f = D.funnel.filter((r) => r.step_conversion !== null).map((r, i) => ({
      ...r, step: `${D.funnel[i].stage} → ${r.stage}`, from: D.funnel[i].volume,
    }));
    hbar($("chart-funnel"), f, {
      title: "Funnel step conversion", label: "step", value: "step_conversion", fmt: (v) => fmt.pct(v), tick: "pct", max: 1,
      tip: (r) => tipRow(null, "Made it through", fmt.pct(r.step_conversion)) + tipRow(null, "Started", fmt.int(r.from)) + tipRow(null, "Ended", fmt.int(r.volume)),
    });

    const months = D.monthly.map((m) => m.year_month);
    const monthName = (ym) => new Date(ym + "-01T00:00:00").toLocaleString("en-US", { month: "short" });
    legend($("legend-trend"), [{ color: "--s1", label: "Ad spend", shape: "line" }, { color: "--s2", label: "Revenue collected", shape: "line" }]);
    lines($("chart-trend"), months, [
      { name: "Ad spend", color: "--s1", values: D.monthly.map((m) => m.spend), endLabel: true },
      { name: "Revenue collected", color: "--s2", values: D.monthly.map((m) => m.revenue), endLabel: true },
    ], { title: "Monthly spend and revenue", tick: "money", fmt: fmt.money, xFmt: monthName, tipX: (ym) => monthName(ym) + " 2025" });

    hbar($("chart-offers"), D.offers, { title: "CTR by offer", label: "offer_type", value: "ctr", fmt: (v) => fmt.pct(v, 2), tick: "pct",
      tip: (r) => tipRow(null, "Click-through rate", fmt.pct(r.ctr, 2)) + tipRow(null, "Visit to lead", fmt.pct(r.visit_to_lead)) });
    const devices = [...D.devices].sort((a, b) => a.cac - b.cac);
    hbar($("chart-devices"), devices, { title: "Cost per customer by device", label: "device", value: "cac", fmt: fmt.money, tick: "money",
      tip: (r) => tipRow(null, "Cost per customer", fmt.money(r.cac)) + tipRow(null, "Visit to lead", fmt.pct(r.visit_to_lead)) + tipRow(null, "Return in year 1", fmt.x(r.roas)) });

    const attKeys = [
      { key: "last_touch", label: "Last touch", color: "--s1" },
      { key: "markov", label: "Markov chain", color: "--s2" },
      { key: "shapley", label: "Shapley", color: "--s3" },
    ];
    legend($("legend-att"), attKeys.map((k, j) => ({ color: k.color, label: k.label, shape: SHAPES[j] })));
    dotPlot($("chart-att"), D.attribution, { title: "Revenue credit by attribution model", label: "channel", keys: attKeys, fmt: (v) => fmt.pct(v), tick: "pct" });

    const dec = D.lead_scoring.deciles;
    columns($("chart-deciles"), dec, {
      title: "Lift by score decile", label: "decile", value: "lift", tick: "x", ref: 1, refLabel: "average", xTitle: "score decile (1 = highest scores)",
      tip: (r) => `<b>Decile ${r.decile}</b>` + tipRow(null, "Conversion rate", fmt.pct(r.conversion_rate)) + tipRow(null, "Lift vs average", fmt.x(r.lift)) +
        tipRow(null, "Customers", `${r.customers} of ${r.leads}`) + tipRow(null, "Running share of customers", fmt.pct(r.cumulative_share_of_customers, 0)),
    });
    const drv = D.lead_scoring.drivers.map((d) => ({ ...d, feature: d.feature.replaceAll("_", " ") }));
    hbar($("chart-drivers"), drv, { title: "Lead score drivers", label: "feature", value: "share", fmt: (v) => fmt.pct(v, 0), tick: "pct", valueLabel: "Share of importance" });

    // mix model small multiples
    const curves = D.mmm.curves, chs = [...new Set(curves.map((c) => c.channel))];
    legend($("legend-curves"), [{ color: "--s1", label: "Model", shape: "line" }, { color: "--s2", label: "True effect", shape: "line" }, { color: "--s1", label: "Current spend", shape: "circle" }]);
    const box = $("chart-curves");
    box.innerHTML = chs.map((ch) => `<div><h3>${ch}</h3><div class="chart"></div></div>`).join("");
    chs.forEach((ch, k) => {
      const pts = curves.filter((c) => c.channel === ch);
      const cell = box.children[k];
      const cur = D.mmm.budget.find((b) => b.channel === ch);
      lines(cell.querySelector(".chart"), pts.map((p) => p.weekly_spend), [
        { name: "Model", color: "--s1", values: pts.map((p) => p.signups) },
        { name: "True effect", color: "--s2", values: pts.map((p) => p.true_signups) },
      ], {
        title: `${ch} response curve`, height: 170, left: 34, ticks: 3, tick: "num", fmt: (v) => v.toFixed(1) + " a week",
        xFmt: (v) => (v >= 1e3 ? "$" + (v / 1e3).toFixed(1) + "k" : "$" + Math.round(v)), tipX: (v) => fmt.money(v) + " a week",
        markers: [{ x: cur.current_weekly_spend, y: cur.signups_now_model, color: "--s1" }], xMax: pts[pts.length - 1].weekly_spend,
        xTicks: [0, Math.floor(pts.length / 2), pts.length - 1],
      });
    });

    if (D.forecast) {
      legend($("legend-forecast"), [{ color: "--s1", label: "Actual", shape: "line" }, { color: "--s2", label: "Forecast", shape: "line" }]);
      forecastChart($("chart-forecast"), D.forecast.weekly, { title: "Weekly leads with forecast" });
    }
    const budget = D.mmm.budget.filter((b) => b.channel !== "Total");
    legend($("legend-budget"), [{ color: "--s1", label: "Now" }, { color: "--s2", label: "Recommended" }]);
    pairedBars($("chart-budget"), budget, {
      title: "Weekly budget now and recommended", label: "channel", fmt: fmt.money, tick: "money",
      keys: [{ key: "current_weekly_spend", label: "Now", color: "--s1" }, { key: "recommended_weekly_spend", label: "Recommended", color: "--s2" }],
      tipExtra: (r) => tipRow(null, "Change", (r.change_pct > 0 ? "+" : "") + r.change_pct.toFixed(0) + "%"),
    });
  }

  function tables() {
    table($("table-channels"), [
      { key: "channel", label: "Channel" }, { key: "spend", label: "Spend", fmt: fmt.money }, { key: "leads", label: "Leads", fmt: fmt.int },
      { key: "customers", label: "Customers", fmt: fmt.int }, { key: "cac", label: "Cost / customer", fmt: fmt.money },
      { key: "roas", label: "Return yr 1", fmt: fmt.x }, { key: "ltv_to_cac", label: "LTV / CAC", fmt: (v) => v.toFixed(1) },
      { key: "monthly_churn", label: "Monthly churn", fmt: (v) => fmt.pct(v) },
    ], [...D.channels].sort((a, b) => b.revenue - a.revenue));
    table($("table-funnel"), [{ key: "stage", label: "Stage" }, { key: "volume", label: "Volume", fmt: fmt.int },
      { key: "step_conversion", label: "From previous", fmt: (v) => fmt.pct(v, 2) }], D.funnel);
    table($("table-trend"), [{ key: "year_month", label: "Month" }, { key: "spend", label: "Spend", fmt: fmt.money },
      { key: "leads", label: "Leads", fmt: fmt.int }, { key: "new_customers", label: "New customers", fmt: fmt.int },
      { key: "revenue", label: "Revenue", fmt: fmt.money }], D.monthly);
    table($("table-offers"), [{ key: "offer_type", label: "Offer" }, { key: "ctr", label: "CTR", fmt: (v) => fmt.pct(v, 2) },
      { key: "visit_to_lead", label: "Visit to lead", fmt: (v) => fmt.pct(v) }], D.offers);
    table($("table-devices"), [{ key: "device", label: "Device" }, { key: "spend", label: "Spend", fmt: fmt.money },
      { key: "visit_to_lead", label: "Visit to lead", fmt: (v) => fmt.pct(v) }, { key: "cac", label: "Cost / customer", fmt: fmt.money },
      { key: "roas", label: "Return yr 1", fmt: fmt.x }], D.devices);
    const p = (v) => fmt.pct(v);
    table($("table-att"), [{ key: "channel", label: "Channel" }, { key: "last_touch", label: "Last touch", fmt: p },
      { key: "first_touch", label: "First touch", fmt: p }, { key: "linear", label: "Linear", fmt: p },
      { key: "markov", label: "Markov", fmt: p }, { key: "shapley", label: "Shapley", fmt: p }], D.attribution);
    table($("table-deciles"), [{ key: "decile", label: "Decile" }, { key: "leads", label: "Leads", fmt: fmt.int },
      { key: "customers", label: "Customers", fmt: fmt.int }, { key: "conversion_rate", label: "Conversion", fmt: p },
      { key: "lift", label: "Lift", fmt: fmt.x }, { key: "cumulative_share_of_customers", label: "Running share", fmt: (v) => fmt.pct(v, 0) }],
      D.lead_scoring.deciles);
    table($("table-drivers"), [{ key: "feature", label: "Feature" }, { key: "share", label: "Share", fmt: (v) => fmt.pct(v, 1) }], D.lead_scoring.drivers);
    table($("table-recovery"), [{ key: "channel", label: "Channel" }, { key: "parameter", label: "Parameter" },
      { key: "true", label: "True", fmt: (v) => fmt.num(v, 2) }, { key: "estimate", label: "Estimate", fmt: (v) => fmt.num(v, 2) },
      { key: "ci90_low", label: "90% low", fmt: (v) => fmt.num(v, 2) }, { key: "ci90_high", label: "90% high", fmt: (v) => fmt.num(v, 2) },
      { key: "inside_interval", label: "Inside", fmt: (v) => (v ? "yes" : "no") }], D.mmm.recovery);
    table($("table-budget"), [{ key: "channel", label: "Channel" }, { key: "current_weekly_spend", label: "Now", fmt: fmt.money },
      { key: "recommended_weekly_spend", label: "Recommended", fmt: fmt.money },
      { key: "change_pct", label: "Change", fmt: (v) => (v > 0 ? "+" : "") + v.toFixed(0) + "%" },
      { key: "signups_now_model", label: "Sign-ups now (model)", fmt: (v) => v.toFixed(1) },
      { key: "signups_after_model", label: "After (model)", fmt: (v) => v.toFixed(1) },
      { key: "signups_now_true", label: "Now (true)", fmt: (v) => v.toFixed(1) },
      { key: "signups_after_true", label: "After (true)", fmt: (v) => v.toFixed(1) }], D.mmm.budget);
    table($("table-quality"), [{ key: "check", label: "Problem" }, { key: "table", label: "Table" },
      { key: "rows_affected", label: "Rows", fmt: fmt.int }, { key: "action", label: "What the SQL does" }], D.quality);
    if (D.forecast) {
      table($("table-forecast"), [{ key: "method", label: "Method" }, { key: "mae", label: "Average error (leads a day)", fmt: (v) => v.toFixed(1) },
        { key: "mape", label: "Average % error", fmt: (v) => fmt.pct(v, 0) },
        { key: "inside_80pct_range", label: "Actuals inside the 80% range", fmt: (v) => fmt.pct(v, 0) }], D.forecast.backtest);
      const bt = D.forecast.backtest, best = bt[0], second = bt[1];
      const fw = D.forecast.weekly.filter((r) => r.forecast != null);
      const hist = D.forecast.weekly.filter((r) => r.actual != null);
      const avg = hist.slice(-4).reduce((a, r) => a + r.actual, 0) / 4;  // last four weeks, after the Black Friday spike
      $("forecast-text").textContent =
        `I tried three ways of forecasting daily leads and back-tested each one from ${best.forecasts / 14} starting points over the second half of the year, forecasting two weeks ahead using only what was known at the time. ` +
        `${best.method} did best, off by ${best.mae.toFixed(1)} leads a day on average, but only just: the ${second.method.toLowerCase()} was ${second.mae.toFixed(1)}. ` +
        `For January it expects about ${fmt.int(fw[0].forecast)} leads a week, in line with the last four weeks (${fmt.int(avg)} a week) once the Black Friday spike had passed. ` +
        `The shaded range comes from how wrong the back-tests actually were, and it held ${fmt.pct(best.inside_80pct_range, 0)} of real values against a target of 80%. ` +
        `It knows nothing about campaigns, so a launch or a Black Friday push would land outside it.`;
    }
    if (D.anomalies) {
      const metricName = { ctr: "Click-through rate", cpm: "CPM", impr_per_dollar: "Impressions per dollar" };
      const day = (d) => new Date(d + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
      table($("table-anomalies"), [
        { key: "when", label: "When" }, { key: "channel", label: "Channel" }, { key: "what", label: "What" },
        { key: "days", label: "Days", fmt: fmt.int }, { key: "note", label: "Cause" },
      ], D.anomalies.map((e) => ({
        ...e,
        when: e.start === e.end ? day(e.start) : `${day(e.start)} to ${day(e.end)}`,
        what: `${metricName[e.metric] || e.metric} ${e.direction === "high" ? "too high" : "too low"}`,
      })));
    }
  }

  function prose() {
    const ls = D.lead_scoring, dec = ls.deciles;
    const xgb = ls.pooled.find((m) => m.model === "xgboost"), lr = ls.pooled.find((m) => m.model === "logistic_regression");
    const top3 = ls.drivers.slice(0, 3).reduce((a, d) => a + d.share, 0);
    $("scoring-text").textContent =
      `The model only uses what's known when someone fills in the form, and it's tested month by month on leads it hasn't seen. ` +
      `It's modest: AUC is ${xgb.roc_auc.toFixed(2)}, and plain logistic regression does about as well (${lr.roc_auc.toFixed(2)}). ` +
      `Channel, company size and pages viewed carry ${fmt.pct(top3, 0)} of the weight, which matches what actually drives conversion in this data. ` +
      `It's still useful: the top tenth of leads convert at ${fmt.pct(dec[0].conversion_rate, 0)} against ${fmt.pct(xgb.base_rate, 0)} overall, ` +
      `and the top fifth hold ${fmt.pct(dec[1].cumulative_share_of_customers, 0)} of the people who went on to buy.`;

    const m = D.mmm, fit = m.fit, rec = m.recovery;
    const inside = rec.filter((r) => r.inside_interval).length;
    const mc = [...m.channels].sort((a, b) => a.marginal_cost_per_signup - b.marginal_cost_per_signup);
    $("mmm-text").textContent =
      `One year isn't enough data for a marketing mix model, so I simulated ${Math.round(fit.weeks / 52)} years of weekly spend and sign-ups with effects I set in advance, ` +
      `then checked how much of the truth the model gets back. It's off by ${fmt.pct(fit.holdout_mape)} on a ${fit.holdout_weeks}-week holdout, ` +
      `and ${inside} of ${rec.length} true parameters land inside its 90% intervals. Google Search comes back almost exactly. ` +
      `Display and TikTok add so few sign-ups next to the noise that the model under-credits them. The next sign-up is cheapest on ${mc[0].channel} ` +
      `(${fmt.money(mc[0].marginal_cost_per_signup)}) and dearest on ${mc[mc.length - 1].channel}.`;

    const t = m.budget.find((b) => b.channel === "Total");
    const up = (a, b) => fmt.pct(b / a - 1);
    $("budget-text").textContent =
      `Keeping total spend the same and moving no channel more than half from where it is, the optimiser shifts money out of Meta, Display and TikTok and into Search and LinkedIn. ` +
      `The model expects ${up(t.signups_now_model, t.signups_after_model)} more sign-ups a week. Scored against the true curves it's ${up(t.signups_now_true, t.signups_after_true)}, ` +
      `so the direction holds and the size is a bit optimistic.`;
    $("built").textContent = `Last built ${D.built}.`;
  }


  // ---------------------------------------------------------------- real experiment
  const ARM_LABEL = { mens_email: "Men's email", womens_email: "Women's email" };
  const ARM_COLOR = { mens_email: "--s1", womens_email: "--s2" };
  const ARM_SHAPE = { mens_email: "circle", womens_email: "square" };
  const pts = (v) => (v >= 0 ? "+" : "") + (v * 100).toFixed(1);
  const pts2 = (v) => (v >= 0 ? "+" : "") + (v * 100).toFixed(2);
  const dollars = (v) => (v >= 0 ? "+$" : "-$") + Math.abs(v).toFixed(2);

  function renderReal() {
    const R = D.real;
    legend($("legend-real"), Object.keys(ARM_LABEL).map((a) => ({ color: ARM_COLOR[a], label: ARM_LABEL[a], shape: ARM_SHAPE[a] })));
    const panels = [
      ["visited", "Extra visits per 100 customers", pts, (v) => trim(v * 100)],
      ["converted", "Extra purchases per 100 customers", pts2, (v) => trim(v * 100)],
      ["spend", "Extra spend per customer", dollars, (v) => (v < 0 ? "-$" : "$") + trim(Math.abs(v))],
    ];
    const box = $("chart-real");
    box.innerHTML = panels.map(([, t]) => `<div><h3>${t}</h3><div class="chart"></div></div>`).join("");
    panels.forEach(([m, , f, tf], k) => {
      const rows = R.effects.filter((e) => e.metric === m).map((e) => ({
        label: ARM_LABEL[e.arm], est: e.lift, lo: e.ci_low, hi: e.ci_high, color: ARM_COLOR[e.arm], shape: ARM_SHAPE[e.arm],
        tipExtra: tipRow(null, "No email", m === "spend" ? "$" + e.control.toFixed(2) : fmt.pct(e.control, 2)) +
          tipRow(null, "With email", m === "spend" ? "$" + e.treated.toFixed(2) : fmt.pct(e.treated, 2)),
      }));
      intervalPlot(box.children[k].querySelector(".chart"), rows, { title: panels[k][1], fmt: f, tickFmt: tf, noLabels: true, estLabel: "Lift" });
    });

    const order = ["mens only", "womens only", "both"];
    const nice = { "mens only": "Bought men's only", "womens only": "Bought women's only", both: "Bought both" };
    const segRows = [];
    for (const b of order) for (const a of Object.keys(ARM_LABEL)) {
      const r = R.segments.find((x) => x.segment === b && x.arm === a);
      segRows.push({ label: `${nice[b]} · ${ARM_LABEL[a].toLowerCase()}`, tipTitle: `${nice[b]}, ${ARM_LABEL[a].toLowerCase()}`,
        est: r.visit_lift, lo: r.visit_ci_low, hi: r.visit_ci_high, color: ARM_COLOR[a], shape: ARM_SHAPE[a] });
    }
    legend($("legend-real-seg"), Object.keys(ARM_LABEL).map((a) => ({ color: ARM_COLOR[a], label: ARM_LABEL[a], shape: ARM_SHAPE[a] })));
    intervalPlot($("chart-real-seg"), segRows, { title: "Visit lift by purchase history", fmt: pts, tickFmt: (v) => trim(v * 100), estLabel: "Extra visits per 100" });
  }

  function realTables() {
    const R = D.real;
    const arm = (v) => ARM_LABEL[v] || v;
    table($("table-real-effects"), [{ key: "arm", label: "Email", fmt: arm }, { key: "label", label: "Metric" },
      { key: "control", label: "No email", fmt: (v) => (v < 0.5 ? fmt.pct(v, 2) : "$" + v.toFixed(2)) },
      { key: "treated", label: "Email", fmt: (v) => (v < 0.5 ? fmt.pct(v, 2) : "$" + v.toFixed(2)) },
      { key: "relative_lift", label: "Relative lift", fmt: (v) => "+" + fmt.pct(v, 0) },
      { key: "p_holm", label: "p (Holm)", fmt: (v) => (v < 0.0001 ? "<0.0001" : v.toFixed(4)) }], R.effects);
    table($("table-real-balance"), [{ key: "check", label: "Check" }, { key: "group", label: "Group", fmt: arm },
      { key: "value", label: "Value", fmt: (v) => (Math.abs(v) >= 100 ? fmt.int(v) : v.toFixed(4)) }], R.balance);
    table($("table-real-cuped"), [{ key: "arm", label: "Email", fmt: arm }, { key: "lift_raw", label: "Spend lift", fmt: dollars },
      { key: "ci_width_raw", label: "Interval width", fmt: (v) => "$" + v.toFixed(3) }, { key: "lift_cuped", label: "With CUPED", fmt: dollars },
      { key: "ci_width_cuped", label: "Interval width", fmt: (v) => "$" + v.toFixed(3) },
      { key: "variance_reduction", label: "Variance removed", fmt: (v) => fmt.pct(v, 2) }], R.cuped);
    table($("table-real-targeting"), [{ key: "policy", label: "Rule" },
      { key: "incremental_spend_per_1000", label: "Extra spend per 1,000 customers", fmt: fmt.money }], R.targeting);
    table($("table-real-power"), [{ key: "metric", label: "Metric" }, { key: "customers_per_group", label: "Customers per group", fmt: fmt.int },
      { key: "min_detectable_lift", label: "Lift", fmt: (v) => (v < 0.1 ? pts2(v) + " pts" : dollars(v)) },
      { key: "min_detectable_relative", label: "Relative", fmt: (v) => fmt.pct(v, 0) }], R.power);
    const segT = R.segments.map((r) => ({ ...r, arm: arm(r.arm) }));
    table($("table-real-seg"), [{ key: "segment", label: "Bought before" }, { key: "arm", label: "Email" },
      { key: "customers", label: "Customers", fmt: fmt.int }, { key: "visit_lift", label: "Visit lift", fmt: (v) => pts(v) + " pts" },
      { key: "visit_ci_low", label: "Low", fmt: pts }, { key: "visit_ci_high", label: "High", fmt: pts },
      { key: "spend_lift", label: "Spend lift", fmt: dollars }], segT);
  }

  function realProse() {
    const R = D.real;
    const srm = R.balance.find((b) => b.check.startsWith("sample ratio"));
    const maxSmd = Math.max(...R.balance.filter((b) => b.check.startsWith("balance")).map((b) => Math.abs(b.value)));
    const n = R.balance.filter((b) => b.check === "customers").map((b) => fmt.int(b.value));
    $("real-checks").textContent =
      `Before looking at results I checked the split. The groups have ${n.join(", ")} customers, which is what a fair three-way split looks like (sample ratio test p = ${srm.value.toFixed(2)}). ` +
      `Months since last purchase, spend last year, new customers and what people had bought before all line up across the groups, with the biggest gap at ${maxSmd.toFixed(3)} standard deviations.`;
    const e = (a, m) => R.effects.find((x) => x.arm === a && x.metric === m);
    const mv = e("mens_email", "visited"), wv = e("womens_email", "visited"), mc = e("mens_email", "converted"), ms = e("mens_email", "spend"), ws = e("womens_email", "spend");
    $("real-effects").textContent =
      `Both emails worked. The men's email lifted visits from ${fmt.pct(mv.control)} to ${fmt.pct(mv.treated)}, more than doubled the purchase rate (${fmt.pct(mc.control, 2)} to ${fmt.pct(mc.treated, 2)}) ` +
      `and added about ${dollars(ms.lift).replace("+", "")} of spend per customer emailed. The women's email did roughly half as well: visits up to ${fmt.pct(wv.treated)}, spend up ${dollars(ws.lift).replace("+", "")} per customer. ` +
      `All six differences hold up after a Holm correction for testing six things at once.`;
    const seg = (b, a) => R.segments.find((x) => x.segment === b && x.arm === a);
    const t = R.targeting, mensAll = t.find((x) => x.policy.startsWith("men's")), pick = t.find((x) => x.policy.startsWith("pick"));
    $("real-segments").textContent =
      `The interesting part is who each email works for. The women's email barely moved people who had only bought men's items (${pts(seg("mens only", "womens_email").visit_lift)} visits per 100), ` +
      `but the men's email worked on everyone, including people who had only bought women's items (${pts(seg("womens only", "mens_email").visit_lift)}, about the same as the women's email got from them). ` +
      `So sending different emails by purchase history doesn't help much here. A rule fitted on half the customers and scored on the other half brought in ${fmt.money(pick.incremental_spend_per_1000)} extra per 1,000 customers, ` +
      `against ${fmt.money(mensAll.incremental_spend_per_1000)} for just sending everyone the men's email.`;
    const c = R.cuped[0], pw = R.power;
    const conv = pw.find((x) => x.metric === "purchase rate"), wneed = pw.find((x) => x.metric.startsWith("purchase rate (womens"));
    $("real-power").textContent =
      `Two things that didn't pan out, which are worth knowing. CUPED, which uses spend from before the test to cut noise, removed only ${fmt.pct(c.variance_reduction, 2)} of the variance, because last year's spend barely predicts spend in a two-week window (correlation ${c.corr_with_covariate.toFixed(2)}). ` +
      `And purchases are rare enough that with about ${fmt.int(conv.customers_per_group)} customers per group, the smallest purchase-rate change this test could reliably catch was ${fmt.pct(conv.min_detectable_relative, 0)} in relative terms. ` +
      `The women's email effect would have needed about ${fmt.int(wneed.customers_per_group)} per group for 80% power, so this test was big enough, but not by a huge margin.`;
  }

  let lastW = 0;
  addEventListener("resize", () => {
    if (!D || Math.abs(innerWidth - lastW) < 20) return;
    lastW = innerWidth;
    render();
    if (D.real) renderReal();
  });
  const redraw = () => { if (D) { render(); if (D.real) renderReal(); } };
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { redraw(); syncThemeButton(); });

  // Theme toggle: follows the system setting until someone picks one, then remembers it.
  const themeBtn = $("theme");
  const isDark = () => {
    const t = document.documentElement.dataset.theme;
    return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  };
  function syncThemeButton() { themeBtn.textContent = isDark() ? "Light mode" : "Dark mode"; }
  themeBtn.addEventListener("click", () => {
    const next = isDark() ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) { /* private mode: just don't remember */ }
    syncThemeButton();
    redraw();
  });
  syncThemeButton();

  fetch("data/site.json")
    .then((r) => r.json())
    .then((data) => {
      D = data;
      lastW = innerWidth;
      kpis(); render(); tables(); prose();
      if (D.real) { $("real").hidden = false; renderReal(); realTables(); realProse(); }
    })
    .catch((e) => {
      document.querySelector("main").insertAdjacentHTML("afterbegin", `<p>Couldn't load the data (${e.message}). Run python src/build_site.py first.</p>`);
    });
})();
