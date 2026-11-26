/* 設定タブ。判断はサーバ(graphapp/settings_view.py)── ここは並べて送るだけ。 */
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let STATE = null;

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opt);
  const data = await res.json().catch(() => ({ ok: false, message: `応答を読めません(${res.status})` }));
  return data;
}

function showMsg(el, ok, text) {
  el.hidden = !text;
  el.className = "msg " + (ok ? "msg--ok" : "msg--error");
  el.textContent = text || "";
}

/* ---------------- タブ ---------------- */
const LOCKED_TABS = { paths: "読みに行く先(集計データの大本・共有の日報データ)を変えること",
                      dist: "配布設定の書き出し・読み込み直し・消すこと" };
function selectTab(key) {
  document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === key)));
  document.querySelectorAll(".panel").forEach((p) => { p.hidden = p.dataset.panel !== key; });
  $("lockbar").hidden = !(key in LOCKED_TABS);
  $("lock-what").innerHTML = key in LOCKED_TABS ? `この面の<strong>${LOCKED_TABS[key]}</strong>に管理者パスワードが要ります。ほかは鍵なしで使えます。` : "";
  try { localStorage.setItem("alg.settings.tab", key); } catch (e) { /* 使えなくてよい */ }
  if (key === "logs") { loadEvents(); loadTail(); }
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => selectTab(t.dataset.tab)));
document.querySelectorAll("[data-goto]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); selectTab(a.dataset.goto); }));

/* ---------------- 鍵 ---------------- */
function renderLock() {
  const open = STATE.admin;
  $("lockbar").classList.toggle("lockbar--open", open);
  $("lock-badge").className = "badge " + (open ? "badge--done" : "badge--todo");
  $("lock-badge").textContent = open ? "鍵が開いています" : "鍵がかかっています";
  $("lock-form").hidden = open;
  $("lock-off").hidden = !open;
  document.querySelectorAll("[data-protected] input").forEach((i) => {
    i.readOnly = !open;
    i.title = open ? "" : "上の鍵を開けると直せます";
  });
  document.querySelectorAll("[data-protected] [data-browse], [data-protected] [data-save]").forEach((b) => { b.disabled = !open; });
}
$("lock-on").addEventListener("click", async () => {
  const r = await api("/api/admin/unlock", { password: $("lock-pw").value });
  $("lock-msg").textContent = r.message || "";
  $("lock-pw").value = "";
  if (r.ok) await load();
});
$("lock-pw").addEventListener("keydown", (e) => { if (e.key === "Enter") $("lock-on").click(); });
$("lock-off").addEventListener("click", async () => { const r = await api("/api/admin/lock", {}); $("lock-msg").textContent = r.message; await load(); });

/* ---------------- 参照設定 ---------------- */
function targetHtml(row) {
  const t = row.extra && row.extra.targets;
  if (!t) return "";
  const vals = Object.entries(t.values).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)} 枚/日</td></tr>`).join("");
  const probs = t.problems.map((p) => `<li>${p.line_no}行目「${esc(p.text)}」: ${esc(p.reason)}</li>`).join("");
  return `<div class="scan">${t.error ? `<div class="path__err">${esc(t.error)}</div>` : ""}
    ${vals ? `<table><thead><tr><th>ライン</th><th>目標(1日あたり)</th></tr></thead><tbody>${vals}</tbody></table>` : ""}
    ${probs ? `<div class="path__err">読めなかった行(この行は線になりません):<ul>${probs}</ul></div>` : ""}
    ${t.unmatched.length ? `<div class="lead">集計データに見つからないライン名: ${esc(t.unmatched.join("・"))}(書き方を確かめてください)</div>` : ""}</div>`;
}
function flashHtml(row) {
  const f = row.extra.flash;
  return `<div class="scan"><div class="lead">速報のファイル ${f.count}件${f.lines.length ? ": " + esc(f.lines.join("・")) : ""}</div>
    ${f.errors.length ? `<div class="path__err">読めないファイル: ${esc(f.errors.join(" / "))}</div>` : ""}</div>`;
}
function scanHtml(row) {
  if (row.extra && row.extra.targets) return targetHtml(row);
  if (row.extra && row.extra.flash) return flashHtml(row);
  const scan = row.extra && row.extra.scan;
  if (!scan) return "";
  if (scan.error) return `<div class="path__err">${esc(scan.error)}</div>`;
  const lvl = scan.level === "大本" ? "" : `<span class="badge badge--todo">指しているのは「${esc(scan.level)}」の段です(そのままで読めます)</span>`;
  const body = scan.lines.map((l) => `<tr><td>${esc(l.line)}</td><td>${esc(l.first_month)}〜${esc(l.last_month)}(${l.months}か月)</td><td>${esc(l.latest_day || "-")}</td></tr>`).join("");
  return `<div class="scan">${lvl}
    <table><thead><tr><th>見つかったライン</th><th>年月のフォルダ</th><th>いちばん新しい日</th></tr></thead><tbody>${body}</tbody></table>
    <div class="lead">例: <code>${esc(row.extra.example)}</code></div></div>`;
}

function rowHtml(p) {
  let badges = "";
  if (p.off) badges += `<span class="badge">使っていません</span>`;
  else {
    if (p.from_dist) badges += `<span class="badge">配布設定の値</span>`;
    else if (p.is_default) badges += `<span class="badge">既定</span>`;
    if (p.is_relative) badges += `<span class="badge badge--todo">相対(アプリのフォルダから)</span>`;
    if (p.error) badges += `<span class="badge badge--alert" title="${esc(p.error)}">いま確かめられません(${esc(p.checked_at)})</span>`;
    else badges += `<span class="badge ${p.exists ? "badge--done" : "badge--alert"}">${esc(p.exists ? p.found_text : p.missing_text)}</span>`;
  }
  const browse = p.is_file ? "" : `<button class="btn btn--sm" type="button" data-browse>フォルダを選ぶ…</button>`;
  return `<div class="path" data-key="${esc(p.key)}" ${p.protected ? "data-protected" : ""}>
    <label for="path-${esc(p.key)}">${esc(p.label)}
      ${p.protected ? `<span class="badge badge--todo" title="変えるには管理者パスワードが要ります">要パスワード</span>` : ""}
      <span class="path__state" data-state></span></label>
    <div class="path__edit">
      <input id="path-${esc(p.key)}" type="text" spellcheck="false" value="${esc(p.value)}" placeholder="${esc(p.empty_text)}" data-saved="${esc(p.value)}">
      <button class="btn btn--primary" type="button" data-save>保存</button>
    </div>
    <div class="lead">${esc(p.note)}</div>
    <div class="path__now"><span class="lead">実際に見る道:</span><code>${esc(p.resolved)}</code>${badges}${browse}</div>
    ${scanHtml(p)}
    <div class="path__err" data-err hidden></div>
  </div>`;
}

function renderPaths(paths) {
  $("paths-groups").innerHTML = paths.groups.map((g) => `<h3>${esc(g.label)}</h3>${g.rows.map(rowHtml).join("")}`).join("");
  const problems = paths.groups.flatMap((g) => g.rows).filter((r) => !r.off && !r.exists && !r.is_file && r.key !== "log_dir").length;
  $("badge-paths").hidden = !problems;
  $("badge-paths").textContent = problems ? `${problems}件` : "";
  document.querySelectorAll(".path").forEach(bindRow);
  renderLock();
  fillLines();
}

function setRowState(row, kind, text) {
  const st = row.querySelector("[data-state]");
  const input = row.querySelector("input");
  st.className = "path__state " + (kind ? "is-" + kind : "");
  st.textContent = text || "";
  input.classList.toggle("is-editing", kind === "editing");
  input.classList.toggle("is-saved", kind === "saved");
}

function bindRow(row) {
  const input = row.querySelector("input");
  input.addEventListener("input", () => setRowState(row, input.value !== input.dataset.saved ? "editing" : "", input.value !== input.dataset.saved ? "未保存" : ""));
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") row.querySelector("[data-save]").click(); });
  row.querySelector("[data-save]").addEventListener("click", async () => {
    const key = row.dataset.key;
    const r = await api("/api/settings/paths", { values: { [key]: input.value } });
    if (!r.ok) {
      setRowState(row, "error", "保存できませんでした");
      const err = row.querySelector("[data-err]"); err.hidden = false; err.textContent = r.message;
      return;
    }
    STATE.paths = r.paths;
    renderPaths(r.paths);
    const again = document.querySelector(`.path[data-key="${CSS.escape(key)}"]`);
    if (again) setRowState(again, "saved", r.message);
    if (key === "log_dir") load();
  });
  const b = row.querySelector("[data-browse]");
  if (b) b.addEventListener("click", () => openBrowser(row));
}

$("paths-recheck").addEventListener("click", async () => {
  const r = await api("/api/settings/paths/recheck", {});
  STATE.paths = r.paths; renderPaths(r.paths);
});

/* ---------------- フォルダを選ぶ窓 ---------------- */
let browsingRow = null;
async function openBrowser(row) {
  browsingRow = row;
  const box = $("browser");
  const rect = row.querySelector(".path__now").getBoundingClientRect();
  box.style.top = `${window.scrollY + rect.bottom + 6}px`;
  box.style.left = `${Math.max(16, rect.left)}px`;
  box.hidden = false;
  const now = row.querySelector("input").value || row.querySelector("code").textContent;
  await browseTo(now.startsWith("(") ? "" : now);
}
async function browseTo(path) {
  const v = await api("/api/fs/browse?path=" + encodeURIComponent(path || ""));
  $("br-here").textContent = v.path;
  $("br-here").dataset.path = v.exists ? v.path : "";
  $("br-pick").disabled = !v.exists;
  $("br-drives").innerHTML = v.drives.map((d) => `<a href="#" data-go="${esc(d.path)}">${esc(d.name)}</a>`).join("");
  $("br-crumbs").innerHTML = v.crumbs.map((c) => `<a href="#" data-go="${esc(c.path)}">${esc(c.name)}</a>`).join(" › ");
  const key = browsingRow && browsingRow.dataset.key;
  const aggRow = key === "report_output_dir" || key === "report_output_dir_2";
  $("br-hint").textContent = v.error ? v.error
    : aggRow && v.agg_lines && v.agg_lines.length ? `ここは「${v.agg_level}」の段です。見つかるライン: ${v.agg_lines.join("・")}` : "";
  const up = v.parent ? `<li class="dir" data-go="${esc(v.parent)}">↑ 1つ上へ</li>` : "";
  $("br-list").innerHTML = up + v.dirs.map((d) => `<li class="dir" data-go="${esc(v.path.replace(/[\\/]$/, "") + (v.path.includes("\\") ? "\\" : "/") + d)}">📁 ${esc(d)}</li>`).join("")
    + v.files.map((f) => `<li class="file">${esc(f)}</li>`).join("") + (v.truncated ? `<li class="file">…(多いので途中まで)</li>` : "");
}
$("browser").addEventListener("click", (e) => {
  const go = e.target.closest("[data-go]");
  if (go) { e.preventDefault(); browseTo(go.dataset.go); }
});
$("br-close").addEventListener("click", () => { $("browser").hidden = true; });
$("br-pick").addEventListener("click", () => {
  if (!browsingRow) return;
  const input = browsingRow.querySelector("input");
  input.value = $("br-here").dataset.path;
  input.dispatchEvent(new Event("input"));
  $("browser").hidden = true;
  input.focus();
});

/* ---------------- 集計データを確かめる ---------------- */
function fillLines() {
  const lines = new Set();
  STATE.paths.groups.flatMap((g) => g.rows).forEach((r) => (r.extra && r.extra.scan ? r.extra.scan.lines : []).forEach((l) => lines.add(l.line)));
  const sel = $("chk-line"); const before = sel.value;
  sel.innerHTML = [...lines].map((l) => `<option>${esc(l)}</option>`).join("") || `<option value="">(ラインが見つかりません)</option>`;
  if ([...lines].includes(before)) sel.value = before;
}
$("chk-run").addEventListener("click", async () => {
  const q = new URLSearchParams({ line: $("chk-line").value, start: $("chk-start").value, end: $("chk-end").value });
  const r = await api("/api/agg/days?" + q);
  $("chk-summary").textContent = r.line ? `${r.line} の ${r.start}〜${r.end}: ${r.days.length}日ぶん見つかりました(大本: ${r.roots.join(" / ")})` : "ラインを選んでください";
  $("chk-table").hidden = !r.days.length;
  const cell = (d, k) => d.files[k] ? `<span class="badge badge--done">あり</span>` : `<span class="badge">なし</span>`;
  $("chk-rows").innerHTML = r.days.map((d) => `<tr><td>${esc(d.day)}</td><td>${cell(d, "summary")}</td><td>${cell(d, "detail")}</td><td>${cell(d, "stop")}</td><td><code>${esc(d.folder)}</code></td></tr>`).join("");
});

/* ---------------- 配布設定 ---------------- */
function renderDist(d) {
  $("dist-exists").className = "badge " + (d.error ? "badge--alert" : d.exists ? "badge--done" : "badge--todo");
  $("dist-exists").textContent = d.error ? "読めません" : d.exists ? "あり" : "なし";
  $("badge-dist").hidden = !d.error; $("badge-dist").textContent = d.error ? "1件" : "";
  $("dist-meta").textContent = d.exists ? `${d.created_at} に ${d.created_on} で作成(版 ${d.version})`
    : "まだありません。下で書き出すと、起動用の Start.vbs と同じフォルダに「配布設定」フォルダができます。";
  $("dist-error").hidden = !d.error; $("dist-error").textContent = d.error ? d.error + " ── このままでは配布設定は効きません。書き出し直すと直ります。" : "";
  $("dist-table").hidden = !d.contents.length;
  $("dist-rows").innerHTML = d.contents.map((c) => `<tr><td>${esc(c.label)}</td><td><code>${esc(c.value)}</code></td></tr>`).join("");
  $("dist-path").textContent = d.path;
  $("dist-launchers").textContent = d.launchers.join(" / ");
  $("dist-reading").innerHTML = d.exists ? `<h3>この端末での読み込み</h3>
    <p class="lead">起動したときに読み込みます(この端末でまだ決めていない項目だけ)。${d.applied_at ? "最後に読み込んだとき: " + esc(d.applied_at) : ""}</p>
    <p class="lead">配布設定の値で動いている: ${esc(d.reading.applied.join("・") || "(なし)")}</p>
    ${d.reading.kept.length ? `<p class="lead"><span class="badge badge--todo">既存が優先</span> ${esc(d.reading.kept.join("・"))} ── この端末で決めてあった値を使っています。揃えたいときは「配布設定を読み込み直す」。</p>` : ""}` : "";
  $("dist-reapply").disabled = !d.exists; $("dist-remove").disabled = !d.exists;
  $("dist-items").innerHTML = `<legend>設定(右は、書き出すと入る この端末の値)</legend>` + d.items.map((it) => `<label>
    <input type="checkbox" data-item="${esc(it.key)}" ${it.default ? "checked" : ""}> ${esc(it.label)}
    ${it.value ? `<code>${esc(it.value)}</code>` : `<span class="lead">(この端末は既定のまま ── 入りません)</span>`}</label>`).join("");
  const lv = { alert: ["badge--alert", "このままでは困る"], warn: ["badge--todo", "端末で違う"], info: ["", "知っておく"] };
  $("dist-warnings").innerHTML = d.warnings.map((w) => `<li><span class="badge ${lv[w.level][0]}">${lv[w.level][1]}</span> ${esc(w.text)}</li>`).join("") || `<li class="lead">気になるところはありません。</li>`;
}
async function distAction(path, body, msgEl) {
  if (!STATE.admin) {
    const pw = await UI.prompt("管理者パスワード", "", true);
    if (pw === null) return;
    body.password = pw;
  }
  const r = await api(path, body);
  showMsg(msgEl, r.ok, r.message || r.error);
  if (r.distribution) { STATE.distribution = r.distribution; renderDist(r.distribution); }
  if (r.paths) { STATE.paths = r.paths; renderPaths(r.paths); }
}
$("dist-export").addEventListener("click", () => distAction("/api/dist/export",
  { items: [...document.querySelectorAll("[data-item]:checked")].map((c) => c.dataset.item) }, $("dist-msg")));
$("dist-reapply").addEventListener("click", async () => { if (await UI.confirm("この端末で決めた値も、配布設定の値で上書きします。よろしいですか？")) distAction("/api/dist/reapply", {}, $("dist-msg2")); });
$("dist-remove").addEventListener("click", async () => { if (await UI.confirm("配布設定フォルダを消します(この端末の設定はそのまま)。よろしいですか？")) distAction("/api/dist/remove", {}, $("dist-msg2")); });

/* ---------------- ログ ---------------- */
function renderLog(l) {
  $("log-path").textContent = l.path;
  $("log-fallback").hidden = !l.problem;
  $("log-fallback").textContent = l.problem ? `ログの出力パスに書けないので、この端末へ書いています: ${l.problem}` : "";
  $("badge-logs").hidden = !l.problem; $("badge-logs").textContent = l.problem ? "1件" : "";
}
async function loadEvents() {
  const q = new URLSearchParams({ start: $("log-start").value, end: $("log-end").value, level: $("log-level").value,
                                  terminal: $("log-terminal").value, q: $("log-q").value });
  const r = await api("/api/log/events?" + q);
  const cur = $("log-terminal").value;
  $("log-terminal").innerHTML = `<option value="">全部</option>` + r.terminals.map((t) => `<option ${t === cur ? "selected" : ""}>${esc(t)}</option>`).join("");
  $("log-counts").textContent = `${r.total}件${r.truncated ? "(新しいほうから500件を表示)" : ""}`;
  const kind = { ERROR: "badge--alert", CRITICAL: "badge--alert", WARNING: "badge--todo" };
  $("log-rows").innerHTML = r.rows.map((x) => `<tr><td>${esc(x.at)}</td><td><span class="badge ${kind[x.level] || ""}">${esc(x.level === "ERROR" ? "エラー" : x.level === "WARNING" ? "注意" : x.level)}</span></td>
    <td>${esc(x.terminal)}</td><td>${esc(x.label || x.where)}</td><td>${esc(x.message)}${x.detail ? `<details><summary>詳しく</summary><pre>${esc(x.detail)}</pre></details>` : ""}</td></tr>`).join("")
    || `<tr><td colspan="5" class="lead">この期間の記録はありません</td></tr>`;
}
async function loadTail() {
  const r = await api("/api/log/tail?lines=200");
  $("log-tail").textContent = r.lines.join("\n") || "(まだありません)";
  $("log-tail").scrollTop = $("log-tail").scrollHeight;
}
["log-reload", "log-level", "log-terminal", "log-start", "log-end"].forEach((id) => $(id).addEventListener(id === "log-reload" ? "click" : "change", loadEvents));
$("log-q").addEventListener("keydown", (e) => { if (e.key === "Enter") loadEvents(); });
$("tail-reload").addEventListener("click", loadTail);

/* ---------------- 管理者 ---------------- */
$("pw-save").addEventListener("click", async () => {
  const r = await api("/api/admin/password", { current: $("pw-cur").value, new: $("pw-new").value, confirm: $("pw-conf").value });
  showMsg($("pw-msg"), r.ok, r.message);
  if (r.ok) ["pw-cur", "pw-new", "pw-conf"].forEach((id) => { $(id).value = ""; });
});
function renderLocal(app) {
  $("local-rows").innerHTML = [
    ["この端末の名前", app.terminal, "ログのファイル名に入ります"],
    ["この端末の設定", app.settings_file, "参照設定・管理者パスワード・配布設定から読んだ値の控え"],
    ["ローカル領域", app.local, "ログ(既定)・アプリ専用DB・共有の日報データの写し"],
    ["アプリのフォルダ", app.root, "配布設定フォルダはこの直下にできます"],
  ].map(([a, b, c]) => `<tr><td>${esc(a)}</td><td><code>${esc(b)}</code></td><td class="lead">${esc(c)}</td></tr>`).join("");
}

/* ---------------- 読み込み ---------------- */
async function load() {
  STATE = await api("/api/settings/state");
  $("app-ver").textContent = "v" + STATE.app.version;
  $("app-who").textContent = "端末: " + STATE.app.terminal;
  renderPaths(STATE.paths);
  renderDist(STATE.distribution);
  renderLog(STATE.log);
  renderLocal(STATE.app);
}

(function init() {
  const today = new Date();
  const iso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  $("chk-end").value = iso(today);
  $("chk-start").value = iso(new Date(today.getFullYear(), today.getMonth(), 1));
  $("log-end").value = iso(today);
  $("log-start").value = iso(new Date(today.getTime() - 7 * 86400000));
  let tab = "paths";
  try { tab = localStorage.getItem("alg.settings.tab") || "paths"; } catch (e) { /* 使えなくてよい */ }
  load().then(() => selectTab(document.querySelector(`.tab[data-tab="${tab}"]`) ? tab : "paths"));
})();
