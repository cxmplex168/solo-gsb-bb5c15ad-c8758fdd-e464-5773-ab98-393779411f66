/* 科研配方量纲校验台 —— 原生前端逻辑 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const exprEl = $("expr");
  const overlayEl = $("expr-overlay");

  let currentCaseId = null;
  let lastResult = null;

  /* ------------------------------------------------------------ 工具 */
  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = data.detail
        ? typeof data.detail === "string"
          ? data.detail
          : data.detail.message || JSON.stringify(data.detail)
        : `请求失败 (${res.status})`;
      throw new Error(msg);
    }
    return data;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtNum(x) {
    if (x === null || x === undefined) return "–";
    if (typeof x === "string") return x;
    if (x === 0) return "0";
    const ax = Math.abs(x);
    if (ax >= 1e-4 && ax < 1e10) {
      return String(parseFloat(x.toPrecision(10)));
    }
    return x.toExponential(5).replace(/\.?0+e/, "e");
  }

  /* ------------------------------------------------------------ 变量表 */
  function addVarRow(name = "", value = "", unit = "") {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input class="name" placeholder="x" value="${escapeHtml(name)}"></td>
      <td><input class="value" type="text" inputmode="decimal" placeholder="0" value="${escapeHtml(value)}"></td>
      <td><input class="unit" placeholder="如 kg、m/s^2、°C（可空）" value="${escapeHtml(unit)}"></td>
      <td><button class="var-del" type="button" title="删除">✕</button></td>`;
    tr.querySelector(".var-del").addEventListener("click", () => tr.remove());
    $("var-body").appendChild(tr);
    tr.querySelector("input").focus();
  }

  function readVars() {
    const vars = {};
    const rows = $("var-body").querySelectorAll("tr");
    for (const tr of rows) {
      const name = tr.querySelector(".name").value.trim();
      const rawVal = tr.querySelector(".value").value.trim();
      const unit = tr.querySelector(".unit").value.trim();
      if (!name) continue;
      const value = Number(rawVal);
      if (rawVal !== "" && !Number.isFinite(value)) {
        throw new Error(`变量 “${name}” 的数值 “${rawVal}” 不是合法数字`);
      }
      vars[name] = { value: rawVal === "" ? 0 : value, unit };
    }
    return vars;
  }

  /* 从表达式 AST 中提取自定义变量（排除函数名 / 常数 / 数字单位） */
  let RESERVED = new Set(["pi", "e", "R", "NA", "N_A", "c0", "k_B"]);
  let FN_SET = new Set();

  function collectVarNames(node, out) {
    if (!node || typeof node !== "object") return;
    if (node.type === "var" && !node.unit) out.add(node.name);
    for (const key of ["left", "right", "operand"]) {
      if (node[key]) collectVarNames(node[key], out);
    }
    if (Array.isArray(node.args)) node.args.forEach(a => collectVarNames(a, out));
  }

  async function extractVars() {
    let data;
    try {
      data = await api("/api/parse-check", {
        method: "POST",
        body: JSON.stringify({ expression: exprEl.value, variables: {} }),
      });
    } catch (e) {
      flashHint(e.message, true);
      return;
    }
    if (!data.ok) {
      flashHint("表达式有语法错误，无法提取变量", true);
      return;
    }
    const names = new Set();
    collectVarNames(data.ast, names);
    const existing = new Set(
      [...$("var-body").querySelectorAll(".name")].map(i => i.value.trim()));
    let added = 0;
    for (const n of names) {
      if (!existing.has(n)) { addVarRow(n); added++; }
    }
    flashHint(added ? `已添加 ${added} 个变量` : "没有发现新的变量名");
  }

  /* ------------------------------------------------------------ 表达式高亮 */
  function clearOverlay() {
    renderOverlay([]);
  }

  function renderOverlay(ranges) {
    const text = exprEl.value;
    const asc = [...ranges].filter(r => r.end > r.start)
                           .sort((a, b) => a.start - b.start);
    const parts = [];
    let cursor = 0;
    for (const r of asc) {
      if (r.start < cursor) continue;
      parts.push(escapeHtml(text.slice(cursor, r.start)));
      const cls = r.cls ? ` class="${r.cls}"` : "";
      parts.push(`<mark${cls}>${escapeHtml(text.slice(r.start, r.end))}</mark>`);
      cursor = r.end;
    }
    parts.push(escapeHtml(text.slice(cursor)));
    // 末尾补一个换行占位，保证与 textarea 滚动高度一致
    overlayEl.innerHTML = parts.join("").replace(/\n/g, "<br>") + "<br>";
  }

  function highlightRanges(ranges, cls) {
    renderOverlay(ranges.map(r => ({ start: r.start, end: r.end, cls })));
  }

  function syncOverlayScroll() {
    overlayEl.scrollTop = exprEl.scrollTop;
    overlayEl.scrollLeft = exprEl.scrollLeft;
  }

  /* ------------------------------------------------------------ 校验 */
  function setBadge(kind, text) {
    const b = $("status-badge");
    b.className = `badge badge-${kind}`;
    b.textContent = text;
  }

  async function runValidate() {
    const expression = exprEl.value;
    if (!expression.trim()) {
      flashHint("请先输入表达式");
      exprEl.focus();
      return;
    }
    let variables;
    try {
      variables = readVars();
    } catch (e) {
      flashHint(e.message, true);
      return;
    }

    setBadge("idle", "校验中…");
    try {
      const data = await api("/api/validate", {
        method: "POST",
        body: JSON.stringify({ expression, variables }),
      });
      lastResult = data;
      renderResult(data);
    } catch (e) {
      setBadge("err", "请求错误");
      $("errors").classList.remove("hidden");
      $("errors").innerHTML =
        `<div class="error-box"><span class="err-msg">${escapeHtml(e.message)}</span></div>`;
      $("result-card").classList.add("hidden");
      $("idle-hint").classList.add("hidden");
    }
  }

  function renderResult(data) {
    const errBox = $("errors");
    const card = $("result-card");
    $("idle-hint").classList.add("hidden");

    if (!data.ok || data.errors.length) {
      setBadge("err", `存在 ${data.errors.length} 个问题`);
      card.classList.add("hidden");
      errBox.classList.remove("hidden");
      errBox.innerHTML = data.errors.map(e => {
        const frag = data.expression.slice(e.start, e.end);
        return `<div class="error-box">
          <div><span class="err-code">${escapeHtml(e.code)}</span>
          <span class="err-msg">${escapeHtml(e.message)}</span></div>
          ${frag ? `<div><span class="err-frag">${escapeHtml(frag)}</span></div>` : ""}
        </div>`;
      }).join("");
      highlightRanges(data.errors.map(e => ({ start: e.start, end: e.end })), "");
      renderSteps(data.steps, true);
      return;
    }

    setBadge("ok", "量纲一致 ✓");
    errBox.classList.add("hidden");
    card.classList.remove("hidden");
    clearOverlay();

    const r = data.result;
    $("r-value").textContent = fmtNum(r.display_value);
    $("r-unit").textContent = r.unit_symbol || "";
    $("r-dim-name").textContent = r.dim_name;
    $("r-dim-symbol").textContent = r.dim_symbol && r.dim_symbol !== "1"
      ? r.dim_symbol : "";
    $("r-si").textContent = r.value_si !== r.display_value
      ? `SI 基准值：${fmtNum(r.value_si)}` : "";

    // 换算
    const conv = $("conversions");
    conv.innerHTML = (r.conversions || []).map(c =>
      `<span class="conv-chip ${c.current ? "current" : ""} ${c.si ? "si" : ""}"
            title="${escapeHtml(c.name)}">
         ${fmtNum(c.value)} ${escapeHtml(c.symbol)}
         <span class="conv-name">${escapeHtml(c.name)}</span>
       </span>`).join("");

    renderSteps(data.steps, false);
  }

  function renderSteps(steps, hasError) {
    const body = $("steps-body");
    body.innerHTML = (steps || []).map((s, idx) => {
      const errRow = hasError && s.kind === "var" && s.value === null
        ? "step-error" : "";
      return `<tr class="${errRow}" data-start="${s.start}" data-end="${s.end}">
        <td class="frag">${escapeHtml(s.expr)}</td>
        <td><span class="tag-kind ${s.kind}">${escapeHtml(s.label)}</span></td>
        <td>${s.value === null ? "—" : fmtNum(s.value)}</td>
        <td>${escapeHtml(s.unit)}</td>
        <td>${escapeHtml(s.dim)}</td>
      </tr>`;
    }).join("");

    body.querySelectorAll("tr").forEach(tr => {
      tr.addEventListener("mouseenter", () => {
        const start = Number(tr.dataset.start);
        const end = Number(tr.dataset.end);
        if (end > start) highlightRanges([{ start, end }], "step");
      });
      tr.addEventListener("mouseleave", () => {
        if (lastResult && lastResult.ok) clearOverlay();
        else if (lastResult) {
          highlightRanges(lastResult.errors.map(e =>
            ({ start: e.start, end: e.end })), "");
        }
      });
    });
  }

  let hintTimer = null;
  function flashHint(msg, isErr) {
    const b = $("status-badge");
    const old = b.textContent;
    b.className = `badge ${isErr ? "badge-err" : "badge-idle"}`;
    b.textContent = msg;
    clearTimeout(hintTimer);
    hintTimer = setTimeout(() => { b.textContent = old; b.className = "badge badge-idle"; }, 2200);
  }

  /* ------------------------------------------------------------ 案例 CRUD */
  function collectPayload() {
    return {
      name: $("case-name").value.trim(),
      description: $("case-desc").value.trim(),
      expression: exprEl.value,
      variables: readVarsQuiet(),
      tags: [],
    };
  }

  function readVarsQuiet() {
    try { return readVars(); } catch { return {}; }
  }

  async function saveCase() {
    const p = collectPayload();
    if (!p.name) { flashHint("请先填写案例名称", true); $("case-name").focus(); return; }
    const data = await api("/api/cases", { method: "POST", body: JSON.stringify(p) });
    currentCaseId = data.id;
    markCurrent(data);
    loadCases();
    flashHint(`已保存 #${data.id}`);
  }

  async function updateCase() {
    if (currentCaseId === null) return;
    const p = collectPayload();
    const data = await api(`/api/cases/${currentCaseId}`, {
      method: "PUT", body: JSON.stringify(p),
    });
    markCurrent(data);
    loadCases();
    flashHint("案例已更新");
  }

  function markCurrent(data) {
    currentCaseId = data.id;
    $("current-case").textContent = `当前：#${data.id} ${data.name}`;
    $("btn-update").disabled = false;
  }

  function resetWorkspace() {
    currentCaseId = null;
    exprEl.value = "";
    $("case-name").value = "";
    $("case-desc").value = "";
    $("var-body").innerHTML = "";
    $("current-case").textContent = "";
    $("btn-update").disabled = true;
    $("errors").classList.add("hidden");
    $("result-card").classList.add("hidden");
    $("idle-hint").classList.remove("hidden");
    setBadge("idle", "待校验");
    clearOverlay();
    lastResult = null;
    addVarRow();
  }

  function loadIntoWorkspace(c) {
    currentCaseId = c.id;
    exprEl.value = c.expression || "";
    $("case-name").value = c.name || "";
    $("case-desc").value = c.description || "";
    $("var-body").innerHTML = "";
    for (const [name, v] of Object.entries(c.variables || {})) {
      addVarRow(name, v.value, v.unit);
    }
    markCurrent(c);
    closeDrawers();
    clearOverlay();
    $("errors").classList.add("hidden");
    $("result-card").classList.add("hidden");
    $("idle-hint").classList.remove("hidden");
    setBadge("idle", "待校验");
  }

  async function loadCases() {
    const q = $("case-search").value.trim();
    const list = await api(`/api/cases${q ? `?q=${encodeURIComponent(q)}` : ""}`);
    const wrap = $("case-list");
    if (!list.length) {
      wrap.innerHTML = `<p class="idle-hint">还没有保存的案例。</p>`;
      return;
    }
    wrap.innerHTML = list.map(c => `
      <div class="case-card">
        <div class="cc-top">
          <span class="cc-name">#${c.id} ${escapeHtml(c.name)}</span>
          <div class="cc-actions">
            <button class="btn btn-small act-load" data-id="${c.id}">加载</button>
            <a class="btn btn-small" href="/api/cases/${c.id}/export" target="_blank">JSON</a>
            <button class="btn btn-small act-del" data-id="${c.id}">删除</button>
          </div>
        </div>
        <div class="cc-expr">${escapeHtml(c.expression || "（无表达式）")}</div>
        ${c.description ? `<div class="cc-desc">${escapeHtml(c.description)}</div>` : ""}
      </div>`).join("");

    const cache = Object.fromEntries(list.map(c => [c.id, c]));
    wrap.querySelectorAll(".act-load").forEach(btn =>
      btn.addEventListener("click", () => loadIntoWorkspace(cache[btn.dataset.id])));
    wrap.querySelectorAll(".act-del").forEach(btn =>
      btn.addEventListener("click", async () => {
        if (!confirm("确认删除该案例？")) return;
        await api(`/api/cases/${btn.dataset.id}`, { method: "DELETE" });
        if (Number(btn.dataset.id) === currentCaseId) resetWorkspace();
        loadCases();
      }));
  }

  async function exportResult() {
    const expression = exprEl.value;
    if (!expression.trim()) { flashHint("请先输入表达式", true); return; }
    let variables;
    try { variables = readVars(); }
    catch (e) { flashHint(e.message, true); return; }
    const data = await api("/api/validate/export", {
      method: "POST",
      body: JSON.stringify({ expression, variables }),
    });
    downloadJson(`dimlab-result-${Date.now()}.json`, data);
  }

  function downloadJson(filename, obj) {
    const blob = new Blob([JSON.stringify(obj, null, 2)],
                          { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    a.remove(); URL.revokeObjectURL(url);
  }

  /* ------------------------------------------------------------ 手册 */
  async function loadUnitsBook() {
    if ($("units-content").dataset.loaded) return;
    const data = await api("/api/units");
    FN_SET = new Set(data.functions);
    const groupsHtml = Object.entries(data.groups).map(([name, items]) => `
      <div class="unit-group">
        <h4>${escapeHtml(name)}</h4>
        <div class="unit-items">
          ${items.map(u =>
            `<span class="unit-pill">${escapeHtml(u.symbol)}<span class="cn">${escapeHtml(u.name)}</span></span>`
          ).join("")}
        </div>
      </div>`).join("");
    $("units-content").innerHTML = `
      <div class="unit-group">
        <h4>函数</h4>
        <div class="fn-list">
          ${data.functions.map(f => `<span class="fn-pill">${escapeHtml(f)}()</span>`).join("")}
        </div>
      </div>
      <div class="unit-group">
        <h4>内置常数</h4>
        <div class="fn-list">
          ${data.constants.map(c =>
            `<span class="fn-pill" title="${escapeHtml(c.desc)}">${escapeHtml(c.name)}${c.unit ? " [" + escapeHtml(c.unit) + "]" : ""}</span>`
          ).join("")}
        </div>
      </div>
      ${groupsHtml}`;
    $("units-content").dataset.loaded = "1";
  }

  /* ------------------------------------------------------------ 抽屉 */
  function openDrawer(id) {
    $(id).classList.remove("hidden");
    if (id === "case-drawer") $("drawer-mask").classList.remove("hidden");
  }
  function closeDrawers() {
    $("case-drawer").classList.add("hidden");
    $("units-drawer").classList.add("hidden");
    $("drawer-mask").classList.add("hidden");
  }

  /* ------------------------------------------------------------ 事件绑定 */
  function bind() {
    $("btn-validate").addEventListener("click", runValidate);
    $("btn-extract").addEventListener("click", extractVars);
    $("btn-add-var").addEventListener("click", () => addVarRow());
    $("btn-save").addEventListener("click", saveCase);
    $("btn-update").addEventListener("click", updateCase);
    $("btn-new").addEventListener("click", resetWorkspace);
    $("btn-export-result").addEventListener("click", exportResult);

    $("btn-cases").addEventListener("click", () => {
      openDrawer("case-drawer"); loadCases();
    });
    $("btn-close-drawer").addEventListener("click", closeDrawers);
    $("drawer-mask").addEventListener("click", closeDrawers);
    $("btn-refresh-cases").addEventListener("click", loadCases);
    $("case-search").addEventListener("input", () => loadCases());

    $("btn-units").addEventListener("click", () => {
      openDrawer("units-drawer"); loadUnitsBook();
    });
    $("btn-close-units").addEventListener("click",
      () => $("units-drawer").classList.add("hidden"));

    exprEl.addEventListener("input", clearOverlay);
    exprEl.addEventListener("scroll", syncOverlayScroll);
    // Ctrl/Cmd + Enter 校验
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") runValidate();
    });
  }

  /* ------------------------------------------------------------ 初始化 */
  function init() {
    clearOverlay();
    addVarRow("m", "", "kg");
    addVarRow("rho", "", "kg/m^3");
    addVarRow("V", "", "m^3");
    exprEl.value = "m/(rho*V)";
    bind();
  }

  init();
})();
