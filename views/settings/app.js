const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
const el = (id) => document.getElementById(id);
const statusEl = el("status");

function setStatus(text, tone = "") {
  statusEl.textContent = text || "";
  statusEl.dataset.tone = tone;
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

let workflows = [];
let modelsState = [];

function fillWorkflowSelects() {
  for (const select of document.querySelectorAll("select[data-wf]")) {
    const current = select.dataset.current || select.value;
    select.innerHTML = "";
    for (const name of workflows) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      select.appendChild(option);
    }
    if (current) select.value = current;
    select.dataset.current = select.value;
  }
}

function renderModels(models) {
  modelsState = models.map((m) => ({ ...m }));
  const body = el("models-body");
  body.innerHTML = "";
  modelsState.forEach((model, index) => {
    const tr = document.createElement("tr");

    const tdEnabled = document.createElement("td");
    const enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.checked = model.enabled;
    enabled.addEventListener("change", () => {
      modelsState[index].enabled = enabled.checked;
    });
    tdEnabled.appendChild(enabled);

    const tdDefault = document.createElement("td");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "default-model";
    radio.checked = model.is_default;
    radio.addEventListener("change", () => {
      modelsState.forEach((m, i) => {
        m.is_default = i === index;
      });
    });
    tdDefault.appendChild(radio);

    const tdKey = document.createElement("td");
    tdKey.innerHTML = `<code>${model.key}</code>`;

    const tdLabel = document.createElement("td");
    tdLabel.textContent = model.label;

    const tdWf = document.createElement("td");
    const select = document.createElement("select");
    for (const name of workflows) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      if (name === model.workflow) option.selected = true;
      select.appendChild(option);
    }
    if (!workflows.includes(model.workflow)) {
      const option = document.createElement("option");
      option.value = model.workflow;
      option.textContent = `${model.workflow}（缺失）`;
      option.selected = true;
      select.appendChild(option);
    }
    select.addEventListener("change", () => {
      modelsState[index].workflow = select.value;
    });
    tdWf.appendChild(select);

    tr.append(tdEnabled, tdDefault, tdKey, tdLabel, tdWf);
    body.appendChild(tr);
  });
}

function applySettings(data) {
  workflows = data.workflows || [];
  el("ver").textContent = `v${data.version || "?"}`;
  for (const input of document.querySelectorAll("[data-cfg]")) {
    const value = getPath(data.config || {}, input.dataset.cfg);
    if (input.type === "checkbox") {
      input.checked = Boolean(value);
    } else if (value !== undefined && value !== null) {
      input.value = value;
    }
    if (input.dataset.wf !== undefined) input.dataset.current = input.value;
  }
  fillWorkflowSelects();
  const paths = data.paths || {};
  el("p-wf").textContent = paths.workflow_dir || "";
  el("p-host").textContent = paths.host_workflow_dir || "（未配置宿主目录）";

  el("o-wf").textContent = paths.workflow_dir || "";
  const wf2 = el("o-wf2");
  if (wf2) wf2.textContent = paths.workflow_dir || "";
  el("o-models").textContent = paths.models_json || "";
  el("o-plugin").textContent = paths.plugin_dir || "";
  el("o-plugin-host").textContent = paths.host_plugin_dir || "（在下面填宿主机 data 目录后显示）";

  renderDiagnostics(data.diagnostics || []);
  renderWorkflowTable(data.workflows || [], data.workflow_usage || {});
  renderModels(data.models || []);
}

function renderDiagnostics(items) {
  const list = el("diag");
  if (!list) return;
  list.innerHTML = "";
  if (!items.length) {
    list.innerHTML = '<li class="hint">无</li>';
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    li.className = `diag-item ${item.level || "info"}`;
    const tag = { error: "错误", warn: "注意", info: "提示", ok: "正常" }[item.level] || "提示";
    li.innerHTML = `<span class="diag-tag">${tag}</span>${item.message || ""}`;
    list.appendChild(li);
  }
}

function renderWorkflowTable(files, usage) {
  const body = el("wf-body");
  if (!body) return;
  body.innerHTML = "";
  if (!files.length) {
    body.innerHTML = '<tr><td colspan="2" class="hint">工作流目录里没有 json</td></tr>';
    return;
  }
  for (const name of files) {
    const tr = document.createElement("tr");
    const tdName = document.createElement("td");
    tdName.innerHTML = `<code>${name}</code>`;
    const tdUse = document.createElement("td");
    const owners = usage[name] || [];
    tdUse.textContent = owners.length ? owners.join(", ") : "（未被引用）";
    if (!owners.length) tdUse.className = "hint";
    tr.append(tdName, tdUse);
    body.appendChild(tr);
  }
}

function collectConfig() {
  const config = { comfyui: {}, generation: {}, paths: {}, selfie: {}, reference: {}, edit: {} };
  for (const input of document.querySelectorAll("[data-cfg]")) {
    const path = input.dataset.cfg;
    let value;
    if (input.type === "checkbox") value = input.checked;
    else if (input.type === "number") value = input.value === "" ? 0 : Number(input.value);
    else value = input.value;
    setPath(config, path, value);
  }
  return config;
}

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
    const modelsPatch = {
      models: Object.fromEntries(modelsState.map((m) => [m.key, { enabled: m.enabled, workflow: m.workflow }])),
      default: (modelsState.find((m) => m.is_default) || {}).key || "",
    };
    const data = await bridge.apiPost("settings", { config: collectConfig() });
    const final = await bridge.apiPost("models", modelsPatch);
    applySettings(final || data);
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

el("btn-save").addEventListener("click", saveAll);
el("btn-test").addEventListener("click", testBackend);
for (const button of document.querySelectorAll("[data-copy]")) {
  button.addEventListener("click", async () => {
    const text = el(button.dataset.copy).textContent || "";
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setStatus("已复制路径", "ok");
    } catch {
      setStatus("复制失败，请手动选中", "bad");
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
  try {
    const wf = await bridge.apiGet("workflows");
    if (wf && wf.items) {
      workflows = wf.items;
      fillWorkflowSelects();
    }
  } catch (err) {
    console.warn("workflows load failed", err);
  }
})();
