const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
const el = (id) => document.getElementById(id);
const statusEl = el("status");

const state = { config: {}, models: [], files: [], notes: {}, usage: {}, paths: {}, originalKeys: new Set() };

function setStatus(text, tone = "") {
  statusEl.textContent = text || "";
  statusEl.dataset.tone = tone;
}

/* ---------------- 通用 ---------------- */

async function copyText(text) {
  if (!text) return false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (err) {
    /* iframe 权限策略会拦截，走下面的兜底 */
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "-1000px";
    document.body.appendChild(area);
    area.select();
    area.setSelectionRange(0, text.length);
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  } catch (err) {
    return false;
  }
}

function viewUrl(name) {
  const match = location.pathname.match(/\/views\/([^/]+)\//);
  if (!match) return "#";
  return location.pathname.replace(`/views/${match[1]}/`, `/views/${name}/`);
}

function getPath(obj, path) {
  return path.split(".").reduce((acc, key) => (acc && acc[key] !== undefined ? acc[key] : undefined), obj);
}

function setPath(obj, path, value) {
  const keys = path.split(".");
  let cur = obj;
  for (let i = 0; i < keys.length - 1; i += 1) {
    if (typeof cur[keys[i]] !== "object" || cur[keys[i]] === null) cur[keys[i]] = {};
    cur = cur[keys[i]];
  }
  cur[keys[keys.length - 1]] = value;
}

/* ---------------- 渲染 ---------------- */

function fillWorkflowSelect(select, current) {
  select.innerHTML = "";
  for (const name of state.files) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  }
  if (current && !state.files.includes(current)) {
    const option = document.createElement("option");
    option.value = current;
    option.textContent = `${current}（缺失）`;
    select.appendChild(option);
  }
  if (current) select.value = current;
}

function applyConfig(data) {
  state.config = data.config || {};
  for (const input of document.querySelectorAll("[data-cfg]")) {
    const value = getPath(state.config, input.dataset.cfg);
    if (input.type === "checkbox") input.checked = Boolean(value);
    else if (value !== undefined && value !== null) input.value = value;
    if (input.dataset.wf !== undefined) input.dataset.current = input.value;
  }
  for (const select of document.querySelectorAll("select[data-wf]")) {
    fillWorkflowSelect(select, select.dataset.current || select.value);
  }
}

function collectConfig() {
  const config = {};
  for (const input of document.querySelectorAll("[data-cfg]")) {
    let value;
    if (input.type === "checkbox") value = input.checked;
    else if (input.type === "number") value = input.value === "" ? 0 : Number(input.value);
    else value = input.value;
    setPath(config, input.dataset.cfg, value);
  }
  return config;
}

function modelRow(model, index) {
  const tr = document.createElement("tr");
  const params = model.author_params || {};

  const enabled = document.createElement("input");
  enabled.type = "checkbox";
  enabled.checked = model.enabled !== false;
  enabled.addEventListener("change", () => {
    state.models[index].enabled = enabled.checked;
  });
  const tdEnabled = document.createElement("td");
  tdEnabled.appendChild(enabled);

  const radio = document.createElement("input");
  radio.type = "radio";
  radio.name = "default-model";
  radio.checked = Boolean(model.is_default);
  radio.addEventListener("change", () => {
    state.models.forEach((item, i) => {
      item.is_default = i === index;
    });
  });
  const tdDefault = document.createElement("td");
  tdDefault.appendChild(radio);

  const key = document.createElement("input");
  key.value = model.key || "";
  key.placeholder = "miao";
  key.readOnly = Boolean(model.key);
  key.className = "cell-key";
  key.addEventListener("input", () => {
    state.models[index].key = key.value.trim();
  });
  const tdKey = document.createElement("td");
  tdKey.appendChild(key);

  const label = document.createElement("input");
  label.value = model.label || "";
  label.placeholder = "miao 柔光";
  label.addEventListener("input", () => {
    state.models[index].label = label.value;
  });
  const tdLabel = document.createElement("td");
  tdLabel.appendChild(label);

  const wf = document.createElement("select");
  fillWorkflowSelect(wf, model.workflow);
  wf.addEventListener("change", () => {
    state.models[index].workflow = wf.value;
  });
  const tdWf = document.createElement("td");
  tdWf.appendChild(wf);

  const numericCells = [];
  for (const [field, step] of [["steps", 1], ["cfg", 0.1], ["width", 64], ["height", 64]]) {
    const td = document.createElement("td");
    const input = document.createElement("input");
    input.type = "number";
    input.step = String(step);
    input.value = params[field] === undefined || params[field] === null ? "" : params[field];
    input.className = "cell-num";
    input.addEventListener("input", () => {
      const target = state.models[index];
      target.author_params = { ...(target.author_params || {}) };
      target.author_params[field] = input.value === "" ? "" : Number(input.value);
    });
    td.appendChild(input);
    numericCells.push(td);
  }

  const paramCells = [];
  for (const field of ["sampler_name", "scheduler"]) {
    const td = document.createElement("td");
    const input = document.createElement("input");
    input.value = params[field] || "";
    input.placeholder = field === "sampler_name" ? "euler_ancestral" : "normal";
    input.className = "cell-text";
    input.addEventListener("input", () => {
      const target = state.models[index];
      target.author_params = { ...(target.author_params || {}) };
      target.author_params[field] = input.value;
    });
    td.appendChild(input);
    paramCells.push(td);
  }

  const listCells = [];
  for (const field of ["aliases", "tags"]) {
    const td = document.createElement("td");
    const input = document.createElement("input");
    input.value = (model[field] || []).join(", ");
    input.placeholder = "逗号分隔";
    input.className = "cell-text";
    input.addEventListener("input", () => {
      state.models[index][field] = input.value;
    });
    td.appendChild(input);
    listCells.push(td);
  }

  const del = document.createElement("button");
  del.className = "ghost danger";
  del.textContent = "删除";
  del.addEventListener("click", () => {
    if (!confirm(`删除模型 ${model.key || "(新)"}？保存后生效`)) return;
    state.models.splice(index, 1);
    renderModels();
  });
  const tdAction = document.createElement("td");
  tdAction.appendChild(del);

  tr.append(tdEnabled, tdDefault, tdKey, tdLabel, tdWf, ...numericCells, ...paramCells, ...listCells, tdAction);
  return tr;
}

function renderModels() {
  const body = el("models-body");
  body.innerHTML = "";
  state.models.forEach((model, index) => body.appendChild(modelRow(model, index)));
  if (!state.models.length) {
    body.innerHTML = '<tr><td colspan="14" class="muted">还没有模型，点右上角「新增模型」</td></tr>';
  }
}

function renderWorkflows() {
  const body = el("wf-body");
  body.innerHTML = "";
  const kindMap = {};
  for (const [kind, label] of [["selfie", "自拍"], ["reference", "参考图"], ["edit", "编辑"]]) {
    const workflow = (state.config[kind] || {}).workflow;
    if (workflow) {
      kindMap[workflow] = kindMap[workflow] ? `${kindMap[workflow]} / ${label}` : label;
    }
  }
  for (const name of state.files) {
    const tr = document.createElement("tr");

    const tdName = document.createElement("td");
    const code = document.createElement("code");
    code.textContent = name;
    tdName.appendChild(code);

    const tdNote = document.createElement("td");
    const note = document.createElement("input");
    note.value = state.notes[name] || "";
    note.placeholder = "比如：obsession 华丽 · 30 步 CFG 4.5";
    note.addEventListener("input", () => {
      state.notes[name] = note.value;
    });
    tdNote.appendChild(note);

    const tdUse = document.createElement("td");
    const owners = state.usage[name] || [];
    tdUse.textContent = owners.length ? owners.join(", ") : "未被引用";
    if (!owners.length) tdUse.className = "muted";

    const tdKind = document.createElement("td");
    tdKind.textContent = kindMap[name] || "";
    if (!kindMap[name]) tdKind.className = "muted";

    tr.append(tdName, tdNote, tdUse, tdKind);
    body.appendChild(tr);
  }
  if (!state.files.length) {
    body.innerHTML = '<tr><td colspan="4" class="muted">工作流目录里没有 json，先上传一个</td></tr>';
  }
}

function renderDiagnostics(items) {
  const list = el("diag");
  list.innerHTML = "";
  if (!items.length) {
    list.innerHTML = '<li class="muted">无</li>';
    return;
  }
  const tagMap = { error: "错误", warn: "注意", info: "提示", ok: "正常" };
  for (const item of items) {
    const li = document.createElement("li");
    li.className = `diag-item ${item.level || "info"}`;
    const tag = document.createElement("span");
    tag.className = "diag-tag";
    tag.textContent = tagMap[item.level] || "提示";
    li.append(tag, document.createTextNode(item.message || ""));
    list.appendChild(li);
  }
}

function applySettings(data) {
  state.files = data.workflows || data.files || [];
  state.notes = data.workflow_notes || {};
  state.usage = data.workflow_usage || {};
  state.paths = data.paths || {};
  state.models = (data.models || []).map((m) => ({ ...m, author_params: { ...(m.author_params || {}) } }));
  state.originalKeys = new Set(state.models.map((m) => String(m.key || "").trim()).filter(Boolean));

  el("ver").textContent = `v${data.version || "?"}`;
  const backend = data.backend || {};
  el("backend-chip").textContent = `后端：${backend.label || "ComfyUI（本地）"}`;

  applyConfig(data);
  el("p-wf").textContent = state.paths.workflow_dir || "";
  el("p-models").textContent = state.paths.models_json || "";
  el("p-host").textContent = state.paths.host_plugin_dir || "（填了宿主 data 目录后显示）";

  renderDiagnostics(data.diagnostics || []);
  renderModels();
  renderWorkflows();
}

/* ---------------- 动作 ---------------- */

async function loadSettings() {
  setStatus("读取中…");
  try {
    const data = await bridge.apiGet("settings");
    applySettings(data);
    setStatus("已加载", "ok");
  } catch (err) {
    setStatus(`读取失败：${err.message || err}`, "bad");
  }
}

async function saveAll() {
  el("btn-save").disabled = true;
  setStatus("保存中…");
  try {
    const models = {};
    const kept = [];
    for (const item of state.models) {
      const key = String(item.key || "").trim();
      if (!key) continue;
      kept.push(key);
      models[key] = {
        label: item.label || key,
        workflow: item.workflow,
        enabled: item.enabled !== false,
        aliases: item.aliases || [],
        tags: item.tags || [],
        author_params: item.author_params || {},
      };
    }
    if (!kept.length) throw new Error("至少保留一个模型");
    const deleted = [...state.originalKeys].filter((key) => !kept.includes(key));
    const defaultKey = (state.models.find((m) => m.is_default) || {}).key || kept[0];

    await bridge.apiPost("settings", { config: collectConfig() });
    let data = await bridge.apiPost("models", { models, delete: deleted, default: defaultKey });
    data = await bridge.apiPost("workflows/notes", { notes: state.notes });
    applySettings(data);
    setStatus("已保存并生效（无需重启）", "ok");
  } catch (err) {
    setStatus(`保存失败：${err.message || err}`, "bad");
  } finally {
    el("btn-save").disabled = false;
  }
}

async function testBackend() {
  setStatus("测试连接…");
  try {
    const result = await bridge.apiPost("test", {});
    if (result.ok) {
      setStatus(`连接正常 · ComfyUI ${result.version || "?"} · 显存 ${result.vram_free_gb}/${result.vram_total_gb}G · 队列 ${result.running}/${result.pending}`, "ok");
    } else {
      setStatus(`连接失败：${result.error || "未知原因"}`, "bad");
    }
  } catch (err) {
    setStatus(`测试失败：${err.message || err}`, "bad");
  }
}

function addModel() {
  state.models.push({
    key: "",
    label: "",
    workflow: state.files[0] || "",
    enabled: true,
    is_default: state.models.length === 0,
    aliases: [],
    tags: [],
    author_params: { steps: 30, cfg: 5, width: 832, height: 1216, sampler_name: "euler_ancestral", scheduler: "normal" },
  });
  renderModels();
}

async function uploadWorkflow(file) {
  if (!file) return;
  if (file.size > 4 * 1024 * 1024) {
    setStatus("工作流文件超过 4MB", "bad");
    return;
  }
  setStatus(`上传 ${file.name}…`);
  try {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error || new Error("读取失败"));
      reader.readAsDataURL(file);
    });
    const result = await bridge.apiPost("workflows/upload", {
      filename: file.name,
      data: dataUrl,
      overwrite: el("wf-overwrite").checked,
    });
    applySettings(result);
    setStatus(`已上传 ${result.name || file.name}`, "ok");
  } catch (err) {
    setStatus(`上传失败：${err.message || err}`, "bad");
  }
}

/* ---------------- 绑定 ---------------- */

for (const tab of document.querySelectorAll("#tabs a")) {
  tab.href = viewUrl(tab.dataset.view);
}

el("btn-save").addEventListener("click", saveAll);
el("btn-test").addEventListener("click", testBackend);
el("btn-add-model").addEventListener("click", addModel);
el("btn-upload-wf").addEventListener("click", () => el("wf-file").click());
el("wf-file").addEventListener("change", () => uploadWorkflow(el("wf-file").files && el("wf-file").files[0]));

for (const button of document.querySelectorAll("[data-copy]")) {
  button.addEventListener("click", async () => {
    const target = el(button.dataset.copy);
    const text = (target.textContent || "").trim();
    if (!text) return;
    if (await copyText(text)) {
      setStatus("已复制", "ok");
      return;
    }
    try {
      const range = document.createRange();
      range.selectNodeContents(target);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      setStatus("已选中，请按 Ctrl+C（浏览器禁止自动复制）", "warn");
    } catch (err) {
      setStatus("复制失败，请手动选中文本", "bad");
    }
  });
}

(async () => {
  try {
    await bridge.ready();
  } catch (err) {
    console.warn("bridge ready failed", err);
  }
  await loadSettings();
})();
