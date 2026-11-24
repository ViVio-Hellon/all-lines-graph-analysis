/* ダッシュボード。数と判断はサーバ(graphapp/dashboard.py・metrics.py)── ここは並べて描くだけ。
 *
 * 構成(保存するもの)= { common: 共通条件, charts: [グラフ] }
 *   グラフ.own に入っている条件だけが「このグラフだけ」。入っていなければ共通条件に従う
 *   (共通条件を変えても、個別に決めたグラフは上書きしない)。
 * 1枚のグラフに複数ラインを重ねない。ラインごとに独立した小さなグラフを並べる。
 */
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const COLS = 12;
const ROW_H = 64;
const GAP = 8;

let META = null;          // 項目の一覧・ライン・直
let DASH = null;          // {id, name, revision, config}
let SAVED = "";           // 保存したときの構成(未保存の変更を見分ける)
let ACTIVE = null;        // 設定を開いているグラフの id
const CACHE = new Map();  // 条件 → 取得結果

/* ------------------------------------------------------------ 色 */
// ラインの色は原則統一(どのグラフでも同じラインは同じ色)
const LINE_COLORS = ["#2f6fd6", "#d9792b", "#2e9a5b", "#b8434c", "#7a55c7", "#1f9aa8", "#b38a1d", "#c2548f", "#4f6b8a", "#6f9d2b", "#995c3c", "#3e8fd6"];
const SHIFT_COLORS = { "1直": "#3f7fe0", "2直": "#2e9a5b", "3直": "#d9792b", "日勤": "#8a5cc9", "4直": "#1f9aa8", "5直": "#b38a1d" };
const KIND_COLORS = { "管理ロス設備停止": "#4f6b8a", "段取り・突発停止": "#d9542b", "ハンドリング停止": "#d9a52b", "その他停止": "#9aa3b1" };
const CAT_COLORS = ["#2f6fd6", "#d9792b", "#2e9a5b", "#b8434c", "#7a55c7", "#1f9aa8", "#b38a1d", "#c2548f", "#9aa3b1"];
const lineColor = (line) => LINE_COLORS[Math.max(0, (META?.lines || []).indexOf(line)) % LINE_COLORS.length];

/* ------------------------------------------------------------ 通信 */
async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  try {
    const res = await fetch(path, opt);
    return await res.json();
  } catch (e) {
    return { ok: false, message: `アプリに届きません(${e.message})。アプリが止まっていないか確かめてください。` };
  }
}
function say(ok, text) {
  const m = $("msg");
  m.hidden = !text;
  m.className = "msg " + (ok ? "msg--ok" : "msg--error");
  m.textContent = text || "";
  if (ok && text) setTimeout(() => { if (m.textContent === text) m.hidden = true; }, 6000);
}

/* ------------------------------------------------------------ 期間 */
const PRESETS = [
  ["this_month", "今月"], ["last_month", "先月"], ["last7", "直近7日"], ["last30", "直近30日"],
  ["last90", "直近90日"], ["this_year", "今年"], ["last_year", "去年"], ["custom", "期間を指定"],
];
const iso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
function resolvePeriod(p) {
  const t = new Date(); t.setHours(0, 0, 0, 0);
  const y = t.getFullYear(), m = t.getMonth();
  const back = (n) => new Date(t.getTime() - (n - 1) * 86400000);
  switch (p.preset) {
    case "last_month": return { start: iso(new Date(y, m - 1, 1)), end: iso(new Date(y, m, 0)) };
    case "last7": return { start: iso(back(7)), end: iso(t) };
    case "last30": return { start: iso(back(30)), end: iso(t) };
    case "last90": return { start: iso(back(90)), end: iso(t) };
    case "this_year": return { start: iso(new Date(y, 0, 1)), end: iso(t) };
    case "last_year": return { start: iso(new Date(y - 1, 0, 1)), end: iso(new Date(y - 1, 11, 31)) };
    case "custom": return { start: p.start || iso(new Date(y, m, 1)), end: p.end || iso(t) };
    default: return { start: iso(new Date(y, m, 1)), end: iso(t) };
  }
}
function periodText(p) {
  const r = resolvePeriod(p);
  const name = (PRESETS.find((x) => x[0] === p.preset) || [, ""])[1];
  return `${p.preset === "custom" ? "" : name + " "}${r.start.replaceAll("-", "/")}〜${r.end.replaceAll("-", "/")}`;
}

/* ------------------------------------------------------------ 構成 */
function defaultConfig() {
  // 要件の概念図(L-1 生産重量 / L-2 稼働率 / L-3 停止理由の内訳 / L-1 生産枚数)と同じ並べ方で始める
  const L = META.lines;
  const pin = (g, i) => { if (L.length) g.own.lines = [L[Math.min(i, L.length - 1)]]; return g; };
  return {
    version: 1,
    common: { all_lines: true, lines: [], period: { preset: "this_month", start: "", end: "" }, grain: "day", shift: "",
              switch: false, current: "" },
    charts: [
      pin(newChart("weight", "bar", 0, 0, 4, 5), 0),
      pin(newChart("rate", "line", 4, 0, 4, 5), 1),
      pin(newChart("stop_reason_min", "pie", 8, 0, 4, 5), 2),
      pin(newChart("sheets", "stacked", 0, 5, 4, 5), 0),
    ],
  };
}
function newChart(metric, chart, x, y, w, h) {
  return { id: "g" + Math.random().toString(36).slice(2, 9), title: "", metric, chart, x, y, w, h, own: {},
           style: { color: "", legend: true, labels: false, same_scale: true, y_min: null, y_max: null } };
}
const C = () => DASH.config;
const metricOf = (key) => META.metrics.find((m) => m.key === key);
/* 共通条件で選んだライン(切り替え表示なら、いま選んでいる1本だけ) */
function commonLines() {
  const c = C().common;
  const picked = c.all_lines ? META.lines : c.lines;
  if (!c.switch) return picked;
  return picked.includes(c.current) ? [c.current] : picked.slice(0, 1);
}
/* グラフの名前。ラインを指定したカードは「L-1 生産重量」のようにラインを頭に付ける */
function titleOf(g) {
  if (g.title) return g.title;
  const label = metricOf(g.metric).label;
  return g.own.lines && g.own.lines.length === 1 ? `${g.own.lines[0]} ${label}` : label;
}
function conditions(g) {
  const c = C().common;
  const lines = g.own.lines || commonLines();
  return {
    lines,
    period: g.own.period || c.period,
    grain: g.own.grain || c.grain,
    shift: "shift" in g.own ? g.own.shift : c.shift,
  };
}
function specOf(g) {
  const k = conditions(g);
  const r = resolvePeriod(k.period);
  return { metric: g.metric, chart: g.chart, lines: k.lines, start: r.start, end: r.end, grain: k.grain, shift: k.shift, title: titleOf(g) };
}
function markDirty() {
  const dirty = JSON.stringify(C()) !== SAVED;
  $("dirty").hidden = !dirty;
  document.title = `${dirty ? "● " : ""}${DASH.name} | 全ライン グラフ分析`;
}
window.addEventListener("beforeunload", (e) => { if (DASH && JSON.stringify(C()) !== SAVED) { e.preventDefault(); e.returnValue = ""; } });

/* ------------------------------------------------------------ 共通条件 */
function linePicker(host, selected, allOn, onChange, withAll) {
  const set = new Set(selected);
  host.innerHTML = (withAll ? `<label class="chip chip--all ${allOn ? "chip--on" : ""}"><input type="checkbox" data-all ${allOn ? "checked" : ""}> 全ライン</label>` : "")
    + META.lines.map((l) => `<label class="chip ${allOn || set.has(l) ? "chip--on" : ""}"><input type="checkbox" value="${esc(l)}" ${allOn || set.has(l) ? "checked" : ""}>`
      + `<span class="chip__dot" style="background:${lineColor(l)}"></span>${esc(l)}</label>`).join("")
    + `<button class="btn btn--sm" type="button" data-none>全解除</button>`
    + (META.lines.length ? "" : `<span class="lead">ラインが見つかりません(設定の「集計データの大本」を確かめてください)</span>`);
  host.onchange = (e) => {
    if (e.target.matches("[data-all]")) return onChange(e.target.checked, e.target.checked ? [] : []);
    const picked = [...host.querySelectorAll("input[value]:checked")].map((i) => i.value);
    onChange(withAll && picked.length === META.lines.length, picked);
  };
  host.querySelector("[data-none]").onclick = () => onChange(false, []);
}
function fillSelect(sel, pairs, value) {
  sel.innerHTML = pairs.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("");
  sel.value = value;
}
function renderCommon() {
  const c = C().common;
  linePicker($("c-lines"), c.lines, c.all_lines, (all, picked) => { c.all_lines = all; c.lines = all ? [] : picked; changed(true); }, true);
  document.querySelectorAll("#c-view [data-view]").forEach((b) => b.setAttribute("aria-pressed", String((b.dataset.view === "switch") === !!c.switch)));
  const picked = c.all_lines ? META.lines : c.lines;
  const now = commonLines()[0];
  $("c-switch").hidden = !c.switch;
  $("c-switch").innerHTML = picked.map((l) => `<button class="ltab" type="button" role="tab" data-line="${esc(l)}" aria-selected="${l === now}">`
      + `<span class="chip__dot" style="background:${lineColor(l)}"></span>${esc(l)}</button>`).join("")
    + (picked.length ? `<span class="lead">← → キーでも切り替えられます。ラインを指定したカードは切り替わりません</span>` : `<span class="lead">ラインを選んでください</span>`);
  fillSelect($("c-preset"), PRESETS, c.period.preset);
  const r = resolvePeriod(c.period);
  $("c-start").value = r.start; $("c-end").value = r.end;
  fillSelect($("c-grain"), Object.entries(META.grains), c.grain);
  fillSelect($("c-shift"), [["", "全直"], ...META.shifts.map((s) => [s, s])], c.shift);
}
$("c-preset").onchange = () => { const p = C().common.period; p.preset = $("c-preset").value; if (p.preset === "custom") Object.assign(p, resolvePeriod({ preset: "this_month" }), { preset: "custom" }); changed(true); };
["c-start", "c-end"].forEach((id) => { $(id).onchange = () => { const p = C().common.period; p.preset = "custom"; p.start = $("c-start").value; p.end = $("c-end").value; changed(true); }; });
$("c-view").onclick = (e) => {
  const b = e.target.closest("[data-view]"); if (!b) return;
  const c = C().common; c.switch = b.dataset.view === "switch";
  if (c.switch && !c.current) c.current = commonLines()[0] || "";
  changed(true);
};
$("c-switch").onclick = (e) => { const b = e.target.closest("[data-line]"); if (b) { C().common.current = b.dataset.line; changed(true); } };
document.addEventListener("keydown", (e) => {
  const c = DASH && C().common;
  if (!c || !c.switch || !["ArrowLeft", "ArrowRight"].includes(e.key) || e.target.closest("input, select, textarea, .gcard, .drawer, .modal")) return;
  const picked = c.all_lines ? META.lines : c.lines;
  const i = picked.indexOf(commonLines()[0]);
  if (i < 0) return;
  c.current = picked[(i + (e.key === "ArrowRight" ? 1 : picked.length - 1)) % picked.length];
  changed(true);
});
$("c-grain").onchange = () => { C().common.grain = $("c-grain").value; changed(true); };
$("c-shift").onchange = () => { C().common.shift = $("c-shift").value; changed(true); };

function changed(common) {
  markDirty();
  if (common) renderCommon();
  renderBoard();
  if (ACTIVE) openDrawer(ACTIVE);
}

/* ------------------------------------------------------------ 盤(自由配置) */
function overlap(a, b) { return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h; }
function pushOthers(moved, depth = 0) {
  if (depth > 60) return;
  for (const o of C().charts) {
    if (o === moved || !overlap(moved, o)) continue;
    o.y = moved.y + moved.h;
    pushOthers(o, depth + 1);
  }
}
function findSpot(w, h) {
  const charts = C().charts;
  for (let y = 0; y < 400; y++) for (let x = 0; x + w <= COLS; x++) {
    const box = { x, y, w, h };
    if (!charts.some((c) => overlap(box, c))) return { x, y };
  }
  return { x: 0, y: Math.max(0, ...charts.map((c) => c.y + c.h)) };
}
const narrow = () => $("board").clientWidth < 700;
function place(card, g) {
  card.style.setProperty("--w", g.w); card.style.setProperty("--h", g.h);
  if (narrow()) { Object.assign(card.style, { position: "relative", left: "", top: "", width: "100%", height: `${g.h * ROW_H}px`, marginBottom: `${GAP}px` }); return; }
  const colW = $("board").clientWidth / COLS;
  Object.assign(card.style, { position: "absolute", marginBottom: "", left: `${g.x * colW}px`, top: `${g.y * ROW_H}px`,
    width: `${g.w * colW - GAP}px`, height: `${g.h * ROW_H - GAP}px` });
}
function boardHeight() {
  $("board").style.height = narrow() ? "auto" : `${Math.max(1, ...C().charts.map((g) => g.y + g.h)) * ROW_H + 20}px`;
}

function tagText(g) {
  const own = Object.keys(g.own).filter((k) => k !== "lines").map((k) => ({ period: "期間", grain: "単位", shift: "直" }[k]));
  const pinned = g.own.lines ? `<span class="badge badge--pin" title="このカードはラインを指定しています(共通条件や切り替えでは変わりません)">ライン指定</span>`
    : C().common.switch ? `<span class="badge badge--todo" title="上のライン切り替えに付いてきます">切り替え表示</span>` : "";
  return pinned + (own.length ? `<span class="badge badge--todo" title="共通条件ではなく、このグラフだけの条件です">個別: ${own.join("・")}</span>` : "");
}
function headDot(g) {
  return g.own.lines && g.own.lines.length === 1 ? `<span class="chip__dot" style="background:${lineColor(g.own.lines[0])}"></span>` : "";
}
function renderBoard() {
  const board = $("board");
  board.innerHTML = "";
  $("empty").hidden = C().charts.length > 0;
  for (const g of C().charts) {
    const m = metricOf(g.metric);
    const k = conditions(g);
    const card = document.createElement("section");
    card.className = "gcard" + (ACTIVE === g.id ? " is-active" : "");
    card.dataset.id = g.id;
    card.innerHTML = `<div class="gcard__head" tabindex="0" title="つかんで動かす(矢印キーでも動きます。Shift+矢印で大きさ)">
        ${headDot(g)}<span class="gcard__title">${esc(titleOf(g))}</span>
        <span class="gcard__tags"><span class="badge">${esc(META.charts[g.chart])}</span>${tagText(g)}</span>
        <span class="gcard__tools">
          <button class="icon" type="button" data-act="edit" aria-label="グラフの設定">設定</button>
          <button class="icon" type="button" data-act="png" aria-label="画像で保存">画像</button>
          <button class="icon" type="button" data-act="del" aria-label="グラフを消す">✕</button>
        </span></div>
      <div class="gcard__body"><div class="loading">読み込み中…</div></div>
      <div class="gcard__foot">${esc(periodText(k.period))} · ${esc(META.grains[k.grain])} · ${esc(k.shift || "全直")} · ${esc(m.unit)}</div>
      <div class="gcard__resize" title="大きさを変える"></div>`;
    board.appendChild(card);
    place(card, g);
    bindCard(card, g);
    loadCard(card, g);
  }
  boardHeight();
}

function bindCard(card, g) {
  const head = card.querySelector(".gcard__head");
  card.querySelector(".gcard__tools").addEventListener("click", (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "edit") openDrawer(g.id);
    if (act === "png") savePng(card, g);
    if (act === "del" && confirm(`「${titleOf(g)}」のグラフを消します。よろしいですか？`)) {
      C().charts = C().charts.filter((x) => x !== g);
      if (ACTIVE === g.id) closeDrawer();
      changed(false);
    }
  });
  head.addEventListener("dblclick", () => openDrawer(g.id));
  drag(card, head, g, "move");
  drag(card, card.querySelector(".gcard__resize"), g, "resize");
  head.addEventListener("keydown", (e) => {
    const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (!d) return;
    e.preventDefault();
    if (e.shiftKey) { g.w = Math.max(2, Math.min(COLS - g.x, g.w + d[0])); g.h = Math.max(2, g.h + d[1]); }
    else { g.x = Math.max(0, Math.min(COLS - g.w, g.x + d[0])); g.y = Math.max(0, g.y + d[1]); }
    pushOthers(g);
    changed(false);
    document.querySelector(`.gcard[data-id="${g.id}"] .gcard__head`)?.focus();
  });
}

function drag(card, handle, g, mode) {
  handle.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest(".gcard__tools") || narrow()) return;
    e.preventDefault();
    const board = $("board");
    const colW = board.clientWidth / COLS;
    const sx = e.clientX, sy = e.clientY, start = { x: g.x, y: g.y, w: g.w, h: g.h };
    card.classList.add("is-moving"); board.classList.add("is-dragging");
    handle.setPointerCapture(e.pointerId);
    const move = (ev) => {
      const dx = Math.round((ev.clientX - sx) / colW), dy = Math.round((ev.clientY - sy) / ROW_H);
      if (mode === "move") { g.x = Math.max(0, Math.min(COLS - g.w, start.x + dx)); g.y = Math.max(0, start.y + dy); }
      else { g.w = Math.max(2, Math.min(COLS - g.x, start.w + dx)); g.h = Math.max(2, Math.min(20, start.h + dy)); }
      place(card, g);
      board.style.height = `${Math.max(parseInt(board.style.height) || 0, (g.y + g.h) * ROW_H + 20)}px`;
    };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      card.classList.remove("is-moving"); board.classList.remove("is-dragging");
      if (start.x !== g.x || start.y !== g.y || start.w !== g.w || start.h !== g.h) { pushOthers(g); changed(false); }
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
  });
}

/* ------------------------------------------------------------ グラフを描く */
async function fetchData(spec) {
  const key = JSON.stringify(spec);
  if (!CACHE.has(key)) CACHE.set(key, api("/api/dash/data", spec));
  const res = await CACHE.get(key);
  if (!res.ok) CACHE.delete(key);
  return res;
}
function colorsFor(g, line, result) {
  const m = metricOf(g.metric);
  const names = result.mode === "category" && g.chart === "pie" ? result.labels : result.series.map((s) => s.name);
  if (g.chart === "pie" || g.chart === "stacked") {
    return names.map((n, i) => SHIFT_COLORS[n] || KIND_COLORS[n] || CAT_COLORS[i % CAT_COLORS.length]);
  }
  if (m.kind === "breakdown" || result.series.length > 1) return names.map((n, i) => CAT_COLORS[i % CAT_COLORS.length]);
  return [g.style.color || lineColor(line)];
}
function maxOf(result, chart) {
  let hi = 0;
  result.labels.forEach((_, i) => {
    if (chart === "stacked") hi = Math.max(hi, result.series.reduce((a, s) => a + (s.values[i] || 0), 0));
    else result.series.forEach((s) => { if (s.values[i] !== null) hi = Math.max(hi, s.values[i]); });
  });
  return hi;
}
async function loadCard(card, g) {
  const spec = specOf(g);
  if (!spec.lines.length) {
    card.querySelector(".gcard__body").innerHTML = `<div class="sub__err">対象ラインが選ばれていません。共通条件かグラフの設定でラインを選んでください。</div>`;
    return;
  }
  const res = await fetchData(spec);
  if (!document.body.contains(card)) return;
  const body = card.querySelector(".gcard__body");
  if (!res.ok) { body.innerHTML = `<div class="sub__err">${esc(res.message)}</div>`; return; }
  card._data = res;
  const m = res.metric;
  const items = res.lines;
  // ラインの数とカードの形から、1つずつのグラフがいちばん大きく見える並べ方を選ぶ
  const width = body.clientWidth - 16, height = body.clientHeight - 12;
  let cols = 1, best = -1;
  for (let c = 1; c <= items.length; c++) {
    const rows = Math.ceil(items.length / c);
    const score = Math.min((width / c) * 0.62, height / rows - 40) - (rows * c - items.length) * 4;
    if (score > best) { best = score; cols = c; }
  }
  const rows = Math.ceil(items.length / cols);
  body.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
  // 小さすぎて読めないときだけ、カードの中で縦に送る
  body.style.gridAutoRows = height / rows < 130 ? "130px" : "minmax(0, 1fr)";
  const scaleMax = g.style.same_scale && g.chart !== "pie" ? Math.max(0, ...items.filter((i) => i.result).map((i) => maxOf(i.result, g.chart))) : undefined;
  body.innerHTML = items.map((it, i) => {
    const r = it.result;
    const total = r && r.total !== null && r.total !== undefined ? `${m.kind === "ratio" ? "期間" : "計"} ${ALGChart.fmt(r.total, m.digits)} ${m.unit}` : "";
    const missing = r && r.mode === "time" ? r.days.filter((d) => d === 0).length : 0;
    const note = r ? `データのある日 ${r.data_days}日${missing ? ` · データなし ${missing}区切り` : ""}${m.source !== "summary" && r.source_days < r.data_days ? ` · ${m.source === "stop" ? "停止内訳" : "集計明細"}CSVのある日 ${r.source_days}日` : ""}` : "";
    return `<div class="sub" data-i="${i}"><div class="sub__head"><span class="chip__dot" style="background:${lineColor(it.line)}"></span>${esc(it.line)}<span class="sub__total">${esc(total)}</span></div>
      ${it.error ? `<div class="sub__err">${esc(it.error)}</div>` : `<div class="sub__chart"></div><div class="sub__note">${esc(note)}</div>`}</div>`;
  }).join("");
  items.forEach((it, i) => {
    if (!it.result) return;
    const host = body.querySelector(`.sub[data-i="${i}"] .sub__chart`);
    ALGChart.render(host, {
      type: g.chart, labels: it.result.labels, series: it.result.series, unit: m.unit, digits: m.digits,
      colors: colorsFor(g, it.line, it.result), legend: g.style.legend, showValues: g.style.labels,
      yMin: typeof g.style.y_min === "number" ? g.style.y_min : undefined,
      yMax: typeof g.style.y_max === "number" ? g.style.y_max : undefined, scaleMax,
      title: `${it.line} ${titleOf(g)}`,
    });
  });
  const foot = card.querySelector(".gcard__foot");
  foot.textContent = foot.textContent.split(" · 取得")[0] + ` · 取得 ${res.fetched_at.slice(11)}`;
}
let resizeTimer = null;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => DASH && renderBoard(), 200); });
window.addEventListener("beforeprint", () => {
  const c = C().common;
  $("print-head").innerHTML = `<strong>${esc(DASH.name)}</strong> ── 共通条件: ${esc(c.all_lines ? "全ライン" : c.lines.join("・"))} / ${esc(periodText(c.period))} / ${esc(META.grains[c.grain])} / ${esc(c.shift || "全直")} · 印刷 ${new Date().toLocaleString("ja-JP")}`;
  // 紙には画面の並び(上から・左から)で流す
  const board = $("board");
  [...board.querySelectorAll(".gcard")].map((card) => [card, C().charts.find((x) => x.id === card.dataset.id)])
    .sort((a, b) => a[1].y - b[1].y || a[1].x - b[1].x).forEach(([card]) => board.appendChild(card));
  document.querySelectorAll(".gcard").forEach((card) => {
    const g = C().charts.find((x) => x.id === card.dataset.id);
    Object.assign(card.style, { width: `calc(${g.w} / 12 * 100% - 6px)`, height: `${g.h * 46}px` });
    loadCard(card, g);
  });
});
window.addEventListener("afterprint", () => renderBoard());

/* ------------------------------------------------------------ グラフ追加
 * メインの使い方: 「指定したラインの、指定したグラフ」を同じページに並べる。
 *   ラインを指定して項目を選ぶ → ライン × 項目 の数だけカードができる(L-1 生産重量 / L-2 稼働率 …)。
 *   「共通条件に従う」を選ぶと、共通条件(と切り替え表示)に付いてくるカードになる。
 */
const ADD = { picks: [], type: "auto", tag: "", mode: "pin", lines: [], split: true };
function suggest(m) { return m.kind === "ratio" ? "line" : m.kind === "breakdown" ? "pie" : "bar"; }
function typeButtons(host, m, current, onPick) {
  host.innerHTML = Object.entries(META.charts).map(([k, label]) => {
    const why = m ? m.charts[k] : "項目を先に選んでください";
    return `<button class="ctype" type="button" data-type="${k}" aria-pressed="${k === current}" ${why ? "disabled" : ""} title="${esc(why || label)}">${esc(label)}</button>`;
  }).join("");
  host.onclick = (e) => { const b = e.target.closest("[data-type]"); if (b && !b.disabled) onPick(b.dataset.type); };
}
/* 追加するカード(ライン, 項目, 種類)の一覧 */
function addPlan() {
  const metricsPicked = ADD.picks.map(metricOf);
  const typeFor = (m) => (ADD.type === "auto" || m.charts[ADD.type] ? suggest(m) : ADD.type);
  if (ADD.mode === "common") return metricsPicked.map((m) => ({ lines: null, m, chart: typeFor(m) }));
  if (!ADD.lines.length) return [];
  if (!ADD.split) return metricsPicked.map((m) => ({ lines: ADD.lines.slice(), m, chart: typeFor(m) }));
  return ADD.lines.flatMap((l) => metricsPicked.map((m) => ({ lines: [l], m, chart: typeFor(m) })));
}
function renderAdd() {
  document.querySelectorAll('input[name="add-mode"]').forEach((r) => { r.checked = r.value === ADD.mode; });
  $("add-linebox").classList.toggle("is-common", ADD.mode === "common");
  linePicker($("add-lines"), ADD.lines, false, (all, picked) => { ADD.lines = picked; renderAdd(); }, false);
  $("add-split").checked = ADD.split;
  $("add-tags").innerHTML = [["", "すべて"], ...META.categories.map((c) => [c, c])].map(([v, t]) =>
    `<button class="tag" type="button" role="tab" data-tag="${esc(v)}" aria-selected="${v === ADD.tag}">${esc(t)}</button>`).join("");
  const q = $("add-q").value.trim();
  const list = META.metrics.filter((m) => (!ADD.tag || m.category === ADD.tag) && (!q || `${m.label}${m.category}${m.note}${m.unit}`.includes(q)));
  $("add-cards").innerHTML = list.map((m) => `<button class="mcard" type="button" data-key="${m.key}" aria-pressed="${ADD.picks.includes(m.key)}" ${m.available ? "" : "disabled"}>
      <span class="mcard__cat">${esc(m.category)}</span><span class="mcard__name">${esc(m.label)}</span>
      <span class="mcard__unit">${esc(m.unit)} · ${esc({ sum: "量", ratio: "率", breakdown: "内訳" }[m.kind])}</span>
      ${m.available ? "" : `<span class="mcard__why">${esc(m.reason)}</span>`}</button>`).join("") || `<p class="lead">見つかりません。</p>`;
  // 種類: 「おすすめ」は項目ごとに合うもの。決めた種類が合わない項目は、その項目のおすすめにする
  const types = [["auto", "項目ごとのおすすめ"], ...Object.entries(META.charts)];
  $("add-types").innerHTML = types.map(([k, label]) => `<button class="ctype" type="button" data-type="${k}" aria-pressed="${k === ADD.type}">${esc(label)}</button>`).join("");
  const plan = addPlan();
  const names = plan.map((p) => `${p.lines && p.lines.length === 1 ? p.lines[0] + " " : ""}${p.m.label}(${META.charts[p.chart]})`);
  $("add-why").textContent = !ADD.picks.length ? "グラフにする項目を選んでください(いくつでも選べます)。"
    : ADD.mode === "pin" && !ADD.lines.length ? "ラインを選んでください。"
    : `${plan.length}枚のカードを追加します: ${names.slice(0, 6).join(" / ")}${names.length > 6 ? ` ほか${names.length - 6}枚` : ""}`;
  $("add-ok").disabled = !plan.length;
  $("add-ok").textContent = plan.length ? `${plan.length}枚追加` : "追加";
}
$("add-types").onclick = (e) => { const b = e.target.closest("[data-type]"); if (b) { ADD.type = b.dataset.type; renderAdd(); } };
document.querySelectorAll('input[name="add-mode"]').forEach((r) => { r.onchange = () => { ADD.mode = r.value; renderAdd(); }; });
$("add-split").onchange = () => { ADD.split = $("add-split").checked; renderAdd(); };
$("add-tags").onclick = (e) => { const t = e.target.closest("[data-tag]"); if (t) { ADD.tag = t.dataset.tag; renderAdd(); } };
$("add-q").oninput = renderAdd;
$("add-cards").onclick = (e) => {
  const c = e.target.closest("[data-key]"); if (!c || c.disabled) return;
  const k = c.dataset.key;
  ADD.picks = ADD.picks.includes(k) ? ADD.picks.filter((x) => x !== k) : [...ADD.picks, k];
  renderAdd();
};
$("add-graph").onclick = () => {
  ADD.picks = []; ADD.type = "auto"; $("add-q").value = "";
  if (!ADD.lines.length) ADD.lines = commonLines().slice(0, 1);
  renderAdd(); $("add-modal").hidden = false; $("add-q").focus();
};
document.querySelectorAll("[data-close]").forEach((b) => { b.onclick = () => { $("add-modal").hidden = true; }; });
$("add-modal").addEventListener("click", (e) => { if (e.target === $("add-modal")) $("add-modal").hidden = true; });
$("add-ok").onclick = () => {
  let first = null;
  for (const p of addPlan()) {
    const single = p.lines && p.lines.length === 1;
    const w = single ? 4 : 6, h = 5;
    const spot = findSpot(w, h);
    const g = newChart(p.m.key, p.chart, spot.x, spot.y, w, h);
    if (p.lines) g.own.lines = p.lines;
    C().charts.push(g);
    first = first || g;
  }
  $("add-modal").hidden = true;
  changed(false);
  if (first) document.querySelector(`.gcard[data-id="${first.id}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
};

/* ------------------------------------------------------------ グラフの設定 */
function openDrawer(id) {
  const g = C().charts.find((x) => x.id === id);
  if (!g) return closeDrawer();
  ACTIVE = id;
  document.querySelectorAll(".gcard").forEach((c) => c.classList.toggle("is-active", c.dataset.id === id));
  $("drawer").hidden = false;
  const m = metricOf(g.metric);
  $("dr-name").value = g.title;
  $("dr-name").placeholder = titleOf({ ...g, title: "" });
  $("dr-metric").innerHTML = META.categories.map((cat) => `<optgroup label="${esc(cat)}">${META.metrics.filter((x) => x.category === cat)
    .map((x) => `<option value="${x.key}" ${x.available ? "" : "disabled"}>${esc(x.label)}(${esc(x.unit)})</option>`).join("")}</optgroup>`).join("");
  $("dr-metric").value = g.metric;
  $("dr-metric-note").textContent = m.note;
  typeButtons($("dr-types"), m, g.chart, (t) => { g.chart = t; changed(false); });
  const reasons = {};
  Object.entries(m.charts).filter(([, w]) => w).forEach(([k, w]) => { (reasons[w] = reasons[w] || []).push(META.charts[k]); });
  $("dr-why").textContent = Object.entries(reasons).map(([w, ks]) => `${ks.join("・")}: ${w}`).join(" / ");
  const k = conditions(g);
  for (const key of ["lines", "period", "grain", "shift"]) {
    const own = key in g.own;
    document.querySelector(`.own[data-own="${key}"]`).classList.toggle("is-common", !own);
    document.querySelectorAll(`input[name="own-${key}"]`).forEach((r) => { r.checked = r.value === (own ? "own" : "common"); });
  }
  linePicker($("dr-lines"), k.lines, false, (all, picked) => { g.own.lines = picked.length ? picked : META.lines.slice(); changed(false); }, false);
  fillSelect($("dr-preset"), PRESETS, k.period.preset);
  const r = resolvePeriod(k.period);
  $("dr-start").value = r.start; $("dr-end").value = r.end;
  fillSelect($("dr-grain"), Object.entries(META.grains), k.grain);
  fillSelect($("dr-shift"), [["", "全直"], ...META.shifts.map((s) => [s, s])], k.shift);
  $("dr-color").value = g.style.color || lineColor(k.lines[0] || META.lines[0]);
  $("dr-color-line").checked = !g.style.color;
  $("dr-legend").checked = g.style.legend;
  $("dr-labels").checked = g.style.labels;
  $("dr-same").checked = g.style.same_scale;
  $("dr-ymin").value = g.style.y_min ?? "";
  $("dr-ymax").value = g.style.y_max ?? "";
}
function closeDrawer() {
  ACTIVE = null;
  $("drawer").hidden = true;
  document.querySelectorAll(".gcard.is-active").forEach((c) => c.classList.remove("is-active"));
}
const activeChart = () => C().charts.find((x) => x.id === ACTIVE);
$("dr-close").onclick = closeDrawer;
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeDrawer(); $("add-modal").hidden = true; $("dash-pop").hidden = true; } });
$("dr-name").oninput = () => { const g = activeChart(); g.title = $("dr-name").value; markDirty(); const t = document.querySelector(`.gcard[data-id="${g.id}"] .gcard__title`); if (t) t.textContent = titleOf(g); };
$("dr-metric").onchange = () => {
  const g = activeChart(); g.metric = $("dr-metric").value;
  const m = metricOf(g.metric);
  if (m.charts[g.chart]) g.chart = suggest(m);   // 合わない種類なら、合うものへ(条件はそのまま)
  changed(false);
};
document.querySelectorAll(".own input[type=radio]").forEach((r) => r.addEventListener("change", () => {
  const g = activeChart(); const key = r.name.replace("own-", "");
  if (r.value === "common") delete g.own[key];
  else {
    const k = conditions(g);
    g.own[key] = key === "lines" ? k.lines.slice() : key === "period" ? { ...k.period } : k[key];
  }
  changed(false);
}));
$("dr-preset").onchange = () => { const g = activeChart(); const p = { ...g.own.period, preset: $("dr-preset").value }; if (p.preset === "custom") Object.assign(p, resolvePeriod({ preset: "this_month" }), { preset: "custom" }); g.own.period = p; changed(false); };
["dr-start", "dr-end"].forEach((id) => { $(id).onchange = () => { activeChart().own.period = { preset: "custom", start: $("dr-start").value, end: $("dr-end").value }; changed(false); }; });
$("dr-grain").onchange = () => { activeChart().own.grain = $("dr-grain").value; changed(false); };
$("dr-shift").onchange = () => { activeChart().own.shift = $("dr-shift").value; changed(false); };
$("dr-color").oninput = () => { activeChart().style.color = $("dr-color").value; $("dr-color-line").checked = false; changed(false); };
$("dr-color-line").onchange = () => { if ($("dr-color-line").checked) activeChart().style.color = ""; changed(false); };
[["dr-legend", "legend"], ["dr-labels", "labels"], ["dr-same", "same_scale"]].forEach(([id, key]) => { $(id).onchange = () => { activeChart().style[key] = $(id).checked; changed(false); }; });
[["dr-ymin", "y_min"], ["dr-ymax", "y_max"]].forEach(([id, key]) => { $(id).onchange = () => { const v = $(id).value.trim(); activeChart().style[key] = v === "" ? null : Number(v); changed(false); }; });

/* ------------------------------------------------------------ 保存・呼び出し */
function use(item) {
  DASH = { id: item.id ?? null, name: item.name, revision: item.revision ?? null, config: item.config };
  SAVED = item.id ? JSON.stringify(item.config) : "";
  $("dash-name").textContent = DASH.name;
  ACTIVE = null; $("drawer").hidden = true;
  ["dash-dup", "dash-del"].forEach((id) => { $(id).disabled = !DASH.id; });
  renderCommon(); renderBoard(); markDirty();
}
function discardOk() { return JSON.stringify(C()) === SAVED || confirm("保存していない変更があります。捨ててよいですか？"); }
async function openDash(id) {
  const r = await api(`/api/dash/get?id=${id}`);
  if (!r.ok) return say(false, r.message);
  use(r.item);
}
async function refreshList() {
  const r = await api(`/api/dash/list?q=${encodeURIComponent($("dash-q").value)}`);
  $("dash-list").innerHTML = (r.items || []).map((d) => `<li role="option" data-id="${d.id}" aria-selected="${d.id === DASH.id}">
      <span>${esc(d.name)}</span><small>${d.charts}枚 · ${esc(d.updated_at.slice(0, 16))}</small></li>`).join("")
    || `<li class="lead">保存したダッシュボードはまだありません</li>`;
  return r;
}
$("dash-open").onclick = async () => {
  const pop = $("dash-pop");
  pop.hidden = !pop.hidden;
  $("dash-open").setAttribute("aria-expanded", String(!pop.hidden));
  if (!pop.hidden) { await refreshList(); $("dash-q").focus(); }
};
$("dash-q").oninput = refreshList;
$("dash-list").onclick = (e) => { const li = e.target.closest("[data-id]"); if (li && discardOk()) { $("dash-pop").hidden = true; openDash(li.dataset.id); } };
document.addEventListener("click", (e) => { if (!e.target.closest(".dsel")) $("dash-pop").hidden = true; });
$("dash-new").onclick = () => { if (!discardOk()) return; $("dash-pop").hidden = true; use({ name: "新しいダッシュボード", config: defaultConfig() }); };
async function saveAs(defaultName) {
  const name = prompt("ダッシュボードの名前", defaultName);
  if (name === null) return;
  const r = await api("/api/dash/create", { name, config: C() });
  if (!r.ok) return say(false, r.message);
  use(r.item); say(true, r.message);
}
$("dash-save").onclick = async () => {
  if (!DASH.id) return saveAs(DASH.name === "新しいダッシュボード" ? "" : DASH.name);
  const r = await api("/api/dash/save", { id: DASH.id, revision: DASH.revision, config: C() });
  if (!r.ok) return say(false, r.message);
  DASH.revision = r.item.revision; DASH.config = r.item.config; SAVED = JSON.stringify(r.item.config);
  renderCommon(); renderBoard(); if (ACTIVE) openDrawer(ACTIVE);
  markDirty(); say(true, r.message);
};
$("dash-saveas").onclick = () => saveAs(DASH.id ? `${DASH.name} のコピー` : "");
$("dash-dup").onclick = async () => {
  if (!DASH.id || !discardOk()) return;
  const r = await api("/api/dash/duplicate", { id: DASH.id });
  if (!r.ok) return say(false, r.message);
  use(r.item); say(true, r.message);
};
$("dash-del").onclick = async () => {
  if (!DASH.id || !confirm(`「${DASH.name}」を消します。元に戻せません。よろしいですか？`)) return;
  const r = await api("/api/dash/delete", { id: DASH.id });
  if (!r.ok) return say(false, r.message);
  use({ name: "新しいダッシュボード", config: defaultConfig() }); say(true, r.message);
};

/* ------------------------------------------------------------ 出力 */
$("reload").onclick = () => { CACHE.clear(); renderBoard(); say(true, "データを読み直しました。"); };
$("print").onclick = () => window.print();
$("export-csv").onclick = async () => {
  if (!C().charts.length) return say(false, "書き出すグラフがありません。");
  const r = await api("/api/dash/export/csv", { name: DASH.name, graphs: C().charts.map(specOf) });
  say(r.ok, r.message);
};
async function svgImage(svg) {
  const src = new XMLSerializer().serializeToString(svg);
  const url = URL.createObjectURL(new Blob([src], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const img = new Image();
    await new Promise((ok, ng) => { img.onload = ok; img.onerror = ng; img.src = url; });
    return img;
  } finally { setTimeout(() => URL.revokeObjectURL(url), 1000); }
}
async function savePng(card, g) {
  const scale = 2, box = card.getBoundingClientRect(), titleH = 30;
  const canvas = document.createElement("canvas");
  canvas.width = box.width * scale; canvas.height = (box.height + titleH) * scale;
  const ctx = canvas.getContext("2d");
  ctx.scale(scale, scale);
  ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, box.width, box.height + titleH);
  ctx.fillStyle = "#18212f"; ctx.font = 'bold 15px "Yu Gothic UI","Meiryo UI",sans-serif';
  const title = titleOf(g);
  ctx.fillText(title, 10, 20);
  ctx.font = '11px "Yu Gothic UI","Meiryo UI",sans-serif'; ctx.fillStyle = "#5d6675";
  ctx.fillText(card.querySelector(".gcard__foot").textContent, 10, box.height + titleH - 8);
  for (const sub of card.querySelectorAll(".sub")) {
    const sb = sub.getBoundingClientRect();
    ctx.fillStyle = "#18212f"; ctx.font = 'bold 12.5px "Yu Gothic UI","Meiryo UI",sans-serif';
    ctx.fillText(sub.querySelector(".sub__head").textContent.trim().replace(/\s+/g, " "), sb.left - box.left + 6, sb.top - box.top + titleH - 14);
    const svg = sub.querySelector("svg");
    if (!svg) continue;
    const r = svg.getBoundingClientRect();
    ctx.drawImage(await svgImage(svg), r.left - box.left, r.top - box.top + titleH - 20, r.width, r.height);
  }
  const res = await api("/api/dash/export/png", { name: DASH.name, title, png: canvas.toDataURL("image/png") });
  say(res.ok, res.message);
}

/* ------------------------------------------------------------ はじめ */
async function rootsNote() {
  $("roots").innerHTML = META.roots.map((r) => `<span class="badge ${r.exists && !r.error ? "badge--done" : "badge--alert"}">${r.exists && !r.error ? "読めます" : "読めません"}</span>`
    + `集計データの大本: <code>${esc(r.root)}</code>${r.error ? ` ── ${esc(r.error)}(<a href="/settings">設定</a>)` : ""}`).join("<br>");
}
(async function init() {
  META = await api("/api/dash/meta");
  if (!META.metrics) { say(false, META.message || "読み込めませんでした。"); return; }
  const state = await api("/api/settings/state");
  if (state.app) { $("app-ver").textContent = "v" + state.app.version; $("app-who").textContent = "端末: " + state.app.terminal; }
  rootsNote();
  const list = await api("/api/dash/list");
  const last = list.last_opened && (list.items || []).find((d) => d.id === list.last_opened);
  if (last) await openDash(last.id);
  else if ((list.items || []).length) await openDash(list.items[0].id);
  else use({ name: "新しいダッシュボード", config: defaultConfig() });
})();
