/* グラフを SVG で描く(外部のライブラリを使わない ── ラインPCはネットに出られないことがあるため)。
 *
 *   ALGChart.render(el, opts)
 *     opts.type     bar / hbar / line / stacked / pie
 *     opts.labels   横軸(期間の区切り、または内訳の項目)
 *     opts.series   [{name, values}]   values の null は「データなし」(0 と描き分ける)
 *     opts.colors   系列(円は項目)ごとの色
 *     opts.unit, opts.digits, opts.legend, opts.showValues, opts.yMin, opts.yMax
 *
 * 色・字は属性で直に入れる(CSS のクラスに頼らない) ── 画像で保存するとき、SVG を
 * そのまま画像にするので、外のスタイルが効かないため。
 */
"use strict";
(function (global) {
  const NS = "http://www.w3.org/2000/svg";
  const FONT = '"Yu Gothic UI","Meiryo UI","Hiragino Sans",system-ui,sans-serif';

  function css(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }
  function el(tag, attrs, parent) {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v !== undefined && v !== null) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  }
  function text(parent, x, y, s, attrs) {
    const t = el("text", Object.assign({ x, y, "font-family": FONT, "font-size": 11, fill: css("--chart-ink", "#3b4454") }, attrs || {}), parent);
    t.textContent = s;
    return t;
  }
  function tip(node, s) { const t = el("title", {}, node); t.textContent = s; }

  function fmt(v, digits) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    return Number(v).toLocaleString("ja-JP", { minimumFractionDigits: digits || 0, maximumFractionDigits: digits || 0 });
  }

  /* 目盛り: 1・2・5 × 10^n の切りのよい刻み */
  function niceScale(lo, hi, ticks) {
    if (lo === hi) { hi = lo + 1; }
    const span = hi - lo;
    const raw = span / Math.max(1, ticks);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || 10 * mag;
    const min = Math.floor(lo / step) * step;
    const max = Math.ceil(hi / step) * step;
    const out = [];
    for (let v = min; v <= max + step / 2; v += step) out.push(Math.round(v / step) * step);
    return { min, max, ticks: out, step };
  }

  function extent(opts) {
    const stacked = opts.type === "stacked";
    let lo = 0, hi = 0, any = false;
    const n = opts.labels.length;
    for (let i = 0; i < n; i++) {
      if (stacked) {
        let pos = 0, neg = 0, seen = false;
        for (const s of opts.series) { const v = s.values[i]; if (v === null || v === undefined) continue; seen = true; if (v >= 0) pos += v; else neg += v; }
        if (seen) { any = true; hi = Math.max(hi, pos); lo = Math.min(lo, neg); }
      } else {
        for (const s of opts.series) { const v = s.values[i]; if (v === null || v === undefined) continue; any = true; hi = Math.max(hi, v); lo = Math.min(lo, v); }
      }
    }
    return { lo, hi, any };
  }

  function legend(svg, items, x, y, maxW) {
    let cx = x, cy = y;
    for (const it of items) {
      const w = 16 + it.name.length * 11 + 12;
      if (cx + w > x + maxW && cx > x) { cx = x; cy += 16; }
      el("rect", { x: cx, y: cy - 9, width: 10, height: 10, rx: 2, fill: it.color }, svg);
      text(svg, cx + 14, cy, it.name, { "font-size": 11 });
      cx += w;
    }
    return cy - y + 16;
  }

  function emptyNote(svg, W, H, msg) {
    text(svg, W / 2, H / 2, msg, { "text-anchor": "middle", "font-size": 13, fill: css("--chart-muted", "#7a8496") });
  }

  function axes(opts, plotH) {
    const ex = extent(opts);
    let lo = Math.min(0, ex.lo), hi = ex.hi;
    if (typeof opts.yMin === "number") lo = opts.yMin;
    if (typeof opts.yMax === "number") hi = opts.yMax;
    if (typeof opts.scaleMax === "number" && typeof opts.yMax !== "number") hi = Math.max(hi, opts.scaleMax);
    if (hi <= lo) hi = lo + 1;
    const sc = niceScale(lo, hi, Math.max(2, Math.min(6, Math.floor(plotH / 26))));
    if (typeof opts.yMin === "number") sc.min = opts.yMin;
    if (typeof opts.yMax === "number") sc.max = opts.yMax;
    return { sc, any: ex.any };
  }

  function render(container, opts) {
    const W = Math.max(120, Math.floor(container.clientWidth || 300));
    const H = Math.max(90, Math.floor(container.clientHeight || 200));
    container.innerHTML = "";
    const svg = el("svg", { xmlns: NS, width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.title || "グラフ" }, container);
    el("rect", { x: 0, y: 0, width: W, height: H, fill: css("--surface", "#fff") }, svg);
    const colors = opts.colors || [];
    const digits = opts.digits || 0;
    if (!opts.labels.length || !opts.series.length) { emptyNote(svg, W, H, "データがありません"); return svg; }

    if (opts.type === "pie") return pie(svg, opts, W, H, colors, digits);

    const showLegend = opts.legend && opts.series.length > 1;
    let legendH = 0;
    if (showLegend) legendH = legend(svg, opts.series.map((s, i) => ({ name: s.name, color: colors[i % colors.length] })), 8, 14, W - 16) + 4;

    const horizontal = opts.type === "hbar";
    const { sc, any } = axes(opts, horizontal ? W - 60 : H - legendH - (opts.unit ? 20 : 10) - 34);
    if (!any) { emptyNote(svg, W, H, "この期間のデータはありません"); return svg; }
    const n = opts.labels.length;
    const longest = Math.max(...opts.labels.map((l) => String(l).length));
    const unitW = 14;

    if (horizontal) {
      const left = Math.min(W * 0.4, 12 + longest * 11), right = 14, top = 8 + legendH, bottom = 26;
      const pw = W - left - right, ph = H - top - bottom;
      if (ph < 20 || pw < 40) { svg.innerHTML = ""; emptyNote(svg, W, H, "小さすぎて描けません(カードを広げてください)"); return svg; }
      const x = (v) => left + (v - sc.min) / (sc.max - sc.min) * pw;
      for (const t of sc.ticks) {
        if (t < sc.min || t > sc.max) continue;
        el("line", { x1: x(t), x2: x(t), y1: top, y2: top + ph, stroke: css("--chart-grid", "#e5e8ee") }, svg);
        text(svg, x(t), H - 10, fmt(t, sc.step < 1 ? 1 : 0), { "text-anchor": "middle", "font-size": 10, fill: css("--chart-muted", "#7a8496") });
      }
      text(svg, W - 4, H - 10, opts.unit || "", { "text-anchor": "end", "font-size": 10, fill: css("--chart-muted", "#7a8496") });
      const band = ph / n, bh = Math.max(3, Math.min(28, band * 0.7));
      opts.labels.forEach((lab, i) => {
        const cy = top + band * i + band / 2;
        text(svg, left - 6, cy + 4, String(lab), { "text-anchor": "end", "font-size": 11 });
        const v = opts.series[0].values[i];
        if (v === null || v === undefined) { text(svg, left + 4, cy + 4, "データなし", { "font-size": 10, fill: css("--chart-muted", "#7a8496") }); return; }
        const x0 = x(Math.max(sc.min, 0)), x1 = x(v);
        const r = el("rect", { x: Math.min(x0, x1), y: cy - bh / 2, width: Math.max(1, Math.abs(x1 - x0)), height: bh, rx: 2, fill: colors[0] }, svg);
        tip(r, `${lab}: ${fmt(v, digits)} ${opts.unit || ""}`);
        if (opts.showValues) text(svg, x1 + 4, cy + 4, fmt(v, digits), { "font-size": 10 });
      });
      return svg;
    }

    // 縦(棒・積み上げ・折れ線)
    const left = 10 + Math.max(...sc.ticks.map((t) => fmt(t, sc.step < 1 ? 1 : 0).length)) * 7 + 4;
    const right = 10, top = 10 + legendH + (opts.unit ? 10 : 0), bottom = 34;
    const pw = W - left - right, ph = H - top - bottom;
    if (ph < 24 || pw < 40) { svg.innerHTML = ""; emptyNote(svg, W, H, "小さすぎて描けません(カードを広げてください)"); return svg; }
    const y = (v) => top + ph - (v - sc.min) / (sc.max - sc.min) * ph;
    if (opts.unit) text(svg, 4, top - 6, `(${opts.unit})`, { "font-size": 10, fill: css("--chart-muted", "#7a8496") });
    for (const t of sc.ticks) {
      if (t < sc.min || t > sc.max) continue;
      el("line", { x1: left, x2: left + pw, y1: y(t), y2: y(t), stroke: t === 0 ? css("--chart-axis", "#b9c0cc") : css("--chart-grid", "#e5e8ee") }, svg);
      text(svg, left - 5, y(t) + 4, fmt(t, sc.step < 1 ? 1 : 0), { "text-anchor": "end", "font-size": 10, fill: css("--chart-muted", "#7a8496") });
    }
    const band = pw / n;
    // 横軸の名前は重ならないぶんだけ
    const every = Math.max(1, Math.ceil((longest * 7 + 8) / band));
    const lastShown = Math.floor((n - 1) / every) * every;
    opts.labels.forEach((lab, i) => {
      // 最後の区切りは、前に出した名前と重ならないときだけ足す
      if (i % every !== 0 && !(i === n - 1 && i - lastShown >= every)) return;
      text(svg, left + band * i + band / 2, H - bottom + 16, String(lab), { "text-anchor": "middle", "font-size": 10, fill: css("--chart-muted", "#7a8496") });
    });
    // データの無い区切りは薄い帯で(0 と描き分ける)
    opts.labels.forEach((lab, i) => {
      const none = opts.series.every((s) => s.values[i] === null || s.values[i] === undefined);
      if (none && n <= 120) {
        const r = el("rect", { x: left + band * i + 1, y: top, width: Math.max(1, band - 2), height: ph, fill: css("--chart-missing", "#f1f2f5") }, svg);
        tip(r, `${lab}: データなし`);
      }
    });

    if (opts.type === "line") {
      opts.series.forEach((s, si) => {
        const color = colors[si % colors.length];
        let d = "", open = false;
        s.values.forEach((v, i) => {
          if (v === null || v === undefined) { open = false; return; }
          const px = left + band * i + band / 2, py = y(v);
          d += `${open ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`;
          open = true;
        });
        if (d) el("path", { d, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round" }, svg);
        s.values.forEach((v, i) => {
          if (v === null || v === undefined) return;
          const px = left + band * i + band / 2, py = y(v);
          const c = el("circle", { cx: px, cy: py, r: n > 60 ? 1.8 : 3, fill: color }, svg);
          tip(c, `${opts.labels[i]} ${s.name}: ${fmt(v, digits)} ${opts.unit || ""}`);
          if (opts.showValues && n <= 40) text(svg, px, py - 6, fmt(v, digits), { "text-anchor": "middle", "font-size": 9.5 });
        });
      });
      return svg;
    }

    const groups = opts.type === "stacked" ? 1 : opts.series.length;
    const bw = Math.max(1, Math.min(40, band * 0.72 / groups));
    opts.labels.forEach((lab, i) => {
      let base = 0;
      const x0 = left + band * i + band / 2 - bw * groups / 2;
      opts.series.forEach((s, si) => {
        const v = s.values[i];
        if (v === null || v === undefined) return;
        const color = colors[si % colors.length];
        let y1, y2, x = x0;
        if (opts.type === "stacked") { y1 = y(base + v); y2 = y(base); base += v; }
        else { x = x0 + si * bw; y1 = y(Math.max(v, 0)); y2 = y(Math.min(v, 0)); }
        const r = el("rect", { x, y: Math.min(y1, y2), width: bw, height: Math.max(v === 0 ? 0 : 1, Math.abs(y2 - y1)), fill: color }, svg);
        tip(r, `${lab} ${s.name}: ${fmt(v, digits)} ${opts.unit || ""}`);
        if (opts.showValues && opts.type !== "stacked" && n <= 40) text(svg, x + bw / 2, Math.min(y1, y2) - 3, fmt(v, digits), { "text-anchor": "middle", "font-size": 9.5 });
      });
      if (opts.showValues && opts.type === "stacked" && n <= 40 && base) text(svg, left + band * i + band / 2, y(base) - 3, fmt(base, digits), { "text-anchor": "middle", "font-size": 9.5 });
    });
    return svg;
  }

  function pie(svg, opts, W, H, colors, digits) {
    const vals = opts.series[0].values.map((v) => (v && v > 0 ? v : 0));
    const total = vals.reduce((a, b) => a + b, 0);
    if (!total) { emptyNote(svg, W, H, "この期間のデータはありません"); return svg; }
    const legendW = opts.legend ? Math.min(W * 0.48, 200) : 0;
    const cx = (W - legendW) / 2, cy = H / 2, r = Math.max(20, Math.min(cx, cy) - 10), inner = r * 0.55;
    let a = -Math.PI / 2;
    vals.forEach((v, i) => {
      if (!v) return;
      const a2 = a + v / total * Math.PI * 2;
      const large = a2 - a > Math.PI ? 1 : 0;
      const p = (rad, ang) => `${(cx + rad * Math.cos(ang)).toFixed(2)},${(cy + rad * Math.sin(ang)).toFixed(2)}`;
      const d = v === total
        ? `M${cx - r},${cy}A${r},${r} 0 1 1 ${cx + r},${cy}A${r},${r} 0 1 1 ${cx - r},${cy}M${cx - inner},${cy}A${inner},${inner} 0 1 0 ${cx + inner},${cy}A${inner},${inner} 0 1 0 ${cx - inner},${cy}Z`
        : `M${p(r, a)}A${r},${r} 0 ${large} 1 ${p(r, a2)}L${p(inner, a2)}A${inner},${inner} 0 ${large} 0 ${p(inner, a)}Z`;
      const path = el("path", { d, fill: colors[i % colors.length], stroke: css("--surface", "#fff"), "stroke-width": 1.5, "fill-rule": "evenodd" }, svg);
      const pct = v / total * 100;
      tip(path, `${opts.labels[i]}: ${fmt(v, digits)} ${opts.unit || ""}(${pct.toFixed(1)}%)`);
      if (opts.showValues && pct >= 5) {
        const mid = (a + a2) / 2, lr = (r + inner) / 2;
        text(svg, cx + lr * Math.cos(mid), cy + lr * Math.sin(mid) + 4, `${pct.toFixed(0)}%`, { "text-anchor": "middle", "font-size": 10, fill: "#ffffff", "font-weight": 700 });
      }
      a = a2;
    });
    text(svg, cx, cy - 2, fmt(total, digits), { "text-anchor": "middle", "font-size": 13, "font-weight": 700 });
    text(svg, cx, cy + 13, opts.unit || "", { "text-anchor": "middle", "font-size": 10, fill: css("--chart-muted", "#7a8496") });
    if (opts.legend) {
      const lx = W - legendW + 4;
      const rows = Math.min(vals.length, Math.floor((H - 10) / 16));
      opts.labels.slice(0, rows).forEach((lab, i) => {
        const yy = (H - rows * 16) / 2 + i * 16 + 12;
        el("rect", { x: lx, y: yy - 9, width: 10, height: 10, rx: 2, fill: colors[i % colors.length] }, svg);
        const pct = total ? (vals[i] / total * 100).toFixed(1) : "0";
        const room = Math.max(3, Math.floor((legendW - 14 - 46) / 11));   // 「 34.7%」の分を残す
        const name = String(lab).length > room ? String(lab).slice(0, room - 1) + "…" : String(lab);
        const t = text(svg, lx + 14, yy, `${name} ${pct}%`, { "font-size": 10.5 });
        tip(t, `${lab}: ${fmt(vals[i], digits)} ${opts.unit || ""}`);
      });
    }
    return svg;
  }

  global.ALGChart = { render, fmt, niceScale };
})(window);
