const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
const el = (id) => document.getElementById(id);

const state = {
  config: {},
  models: [],
  files: [],
  notes: {},
  usage: {},
  paths: {},
  originalKeys: new Set(),
  referencePath: "",
  busy: false,
  loadedSettings: false,
};

/* ==================== 通用 ==================== */

function setStatus(text, tone = "") {
  const node = el("status");
  node.textContent = text || "";
  node.dataset.tone = tone;
}

async function copyText(text) {
  if (!text) return false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (err) {
    /* iframe 权限策略会拦，走兜底 */
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

function switchTab(name) {
  for (const tab of document.querySelectorAll("#tabs .tab")) {
    tab.classList.toggle("active", tab.dataset.tab === name);
  }
  el("panel-generate").hidden = name !== "generate";
  el("panel-settings").hidden = name !== "settings";
  for (const node of document.querySelectorAll(".only-generate")) node.hidden = name !== "generate";
  for (const node of document.querySelectorAll(".only-settings")) node.hidden = name !== "settings";
  if (name === "settings" && !state.loadedSettings) loadSettings();
}

/* ==================== 生成 ==================== */

function updateBackendChip(backend) {
  const chip = el("chip-backend");
  if (!backend) return;
  if (backend.online) {
    chip.textContent = `ComfyUI ${backend.version || ""} · 显存 ${backend.vram_free_gb}/${backend.vram_total_gb}G · 队列 ${backend.running}/${backend.pending}`;
    chip.dataset.tone = "ok";
  } else {
    chip.textContent = `后端离线：${backend.error || "未知"}`;
    chip.dataset.tone = "bad";
  }
}

function updateBanner(backend, models) {
  const banner = el("banner");
  const tips = [];
  if (backend && !backend.online) {
    tips.push("ComfyUI 连不上：" + (backend.error || "原因未知") + "。到「设置」检查后端地址（Docker 里应为 http://host.docker.internal:8188）。");
  }
  if (!models || !models.length) {
    tips.push("没有可用模型：到「设置」启用模型，或检查 models.json。");
  }
  if (tips.length) {
    banner.innerHTML = tips.map((tip) => "<div>• " + tip + "</div>").join("");
    banner.hidden = false;
  } else {
    banner.hidden = true;
    banner.innerHTML = "";
  }
}

function displayLabel(item) {
  // label 里再写一遍英文 key 是冗余的；显示时剥掉，key 另外展示
  const label = String(item.label || item.key || "");
  const key = String(item.key || "");
  if (key && label.toLowerCase().startsWith(key.toLowerCase())) {
    return label.slice(key.length).replace(/^[\s\-·_]+/, "") || key;
  }
  return label;
}

function renderModelsForGenerate(models, fallback) {
  const select = el("model");
  const previous = select.value;
  select.innerHTML = "";
  const usable = models.filter((m) => m.enabled !== false);
  for (const item of usable) {
    const option = document.createElement("option");
    option.value = item.key;
    option.textContent = displayLabel(item) + (item.is_default ? "（默认）" : "");
    select.appendChild(option);
  }
  if (!usable.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "（无可用模型）";
    select.appendChild(option);
  }
  if (previous && usable.some((m) => m.key === previous)) select.value = previous;
  else if (fallback && usable.some((m) => m.key === fallback)) select.value = fallback;
  syncModelHint();
}

function syncModelHint() {
  const kind = el("kind").value;
  const needsRef = kind === "reference" || kind === "edit";
  el("reference-row").hidden = !needsRef;
  if (!needsRef) el("ref-preview").hidden = true;
  el("model-hint").textContent =
    kind === "text2img" || kind === "auto"
      ? "文生图按此模型出图（换模型即换画风）"
      : "结构用专用工作流，底模与参数按此模型";
}

async function loadStatus() {
  el("chip-backend").textContent = "连接中…";
  try {
    const data = await bridge.apiGet("status");
    updateBackendChip(data.backend || {});
    renderModelsForGenerate(data.models || [], data.default_model || "");
    updateBanner(data.backend || {}, data.models || []);
  } catch (err) {
    el("chip-backend").textContent = "状态读取失败：" + (err.message || err);
    el("chip-backend").dataset.tone = "bad";
  }
}

const KIND_MAP = { auto: "auto", "文生图": "text2img", text2img: "text2img", selfie: "selfie", "自拍": "selfie", edit: "edit", "编辑": "edit", reference: "reference", "参考图": "reference" };

function loadRequestIntoForm(item) {
  const req = (item.receipt && item.receipt.request) || {};
  const hasAnything = req.prompt || req.kind || req.model_key;
  if (!hasAnything) {
    setStatus("这条记录没有存原始参数（旧版本生成的），只能看不能重跑", "warn");
    return false;
  }
  if (req.prompt) el("prompt").value = req.prompt;
  if (req.kind) {
    const kind = KIND_MAP[String(req.kind)] || KIND_MAP[String(req.kind).toLowerCase()] || "auto";
    el("kind").value = kind;
  }
  if (req.model_key) el("model").value = req.model_key;
  if (req.width) el("width").value = req.width;
  if (req.height) el("height").value = req.height;
  if (req.seed !== undefined && req.seed !== null && req.seed !== "") el("seed").value = req.seed;
  else el("seed").value = -1;
  el("negative").value = req.extra_negative || "";
  syncModelHint();
  switchTab("generate");
  setStatus("已载入上次参数，点「生成」即可重跑", "warn");
  return true;
}

function showImage(image) {
  const preview = el("preview");
  preview.innerHTML = "";
  const img = document.createElement("img");
  img.alt = image.name || "result";
  img.src = image.data_url || image.url;
  preview.appendChild(img);

  const actions = document.createElement("div");
  actions.className = "preview-actions";
  const download = document.createElement("a");
  download.textContent = "下载";
  download.href = image.data_url || image.url;
  download.download = image.name || "tsukiyo.png";
  actions.appendChild(download);
  const size = document.createElement("span");
  size.className = "hint";
  size.textContent = image.size ? (image.size / 1024 / 1024).toFixed(1) + " MB" : "";
  actions.appendChild(size);
  preview.appendChild(actions);
}

function showReceipt(receipt) {
  const meta = el("result-meta");
  meta.textContent = receipt.ok
    ? (receipt.kind || "") + " · " + (receipt.model_key || "") + " · " + ((receipt.elapsed_ms || 0) / 1000).toFixed(1) + "s · seed " + receipt.seed
    : "失败：" + (receipt.error || "未知错误");
  meta.dataset.tone = receipt.ok ? "ok" : "bad";
  if (receipt.positive) {
    el("prompt-detail").hidden = false;
    el("prompt-final").textContent = "POS:\n" + receipt.positive + "\n\nNEG:\n" + (receipt.negative || "");
  } else {
    el("prompt-detail").hidden = true;
  }
}

function setProgress(visible, percent, text) {
  const box = el("progress");
  box.hidden = !visible;
  if (!visible) return;
  const fill = el("progress-fill");
  if (percent === null || percent === undefined) {
    fill.classList.add("indeterminate");
    fill.style.width = "35%";
  } else {
    fill.classList.remove("indeterminate");
    fill.style.width = Math.max(2, Math.min(100, percent)) + "%";
  }
  el("progress-text").textContent = text || "";
}

async function generate() {
  if (state.busy) return;
  const prompt = el("prompt").value.trim();
  const kind = el("kind").value;
  if (!prompt) {
    setStatus("先写点画面描述", "bad");
    el("prompt").focus();
    return;
  }
  if ((kind === "reference" || kind === "edit") && !state.referencePath) {
    setStatus("参考图 / 编辑需要先上传一张图", "bad");
    return;
  }
  state.busy = true;
  el("btn-generate").disabled = true;
  setStatus("生成中…");
  setProgress(true, null, "提交中…");

  const payload = {
    prompt,
    kind,
    model_key: el("model").value || "",
    reference_path: state.referencePath,
    width: Number(el("width").value) || 0,
    height: Number(el("height").value) || 0,
    seed: Number(el("seed").value),
    negative: el("negative").value.trim(),
  };

  try {
    // 插件页 iframe 是 sandbox="allow-scripts allow-forms allow-downloads"（没有 allow-same-origin），
    // 页面里的裸 fetch 属于跨域请求，会被浏览器直接拦成 “Failed to fetch”。
    // 所以生成必须走 bridge，由父页面用同源凭证代发；代价是拿不到 SSE 的逐秒进度，
    // 这里用本地计时器代替。
    const startedAt = Date.now();
    const ticker = setInterval(() => {
      const seconds = ((Date.now() - startedAt) / 1000).toFixed(1);
      setProgress(true, null, "生成中… " + seconds + "s（含排队）");
    }, 500);
    let final;
    try {
      final = await bridge.apiPost("generate", payload);
    } finally {
      clearInterval(ticker);
    }
    if (!final || typeof final !== "object") throw new Error("后端没有返回结果");
    showReceipt(final);
    if (final.ok && (final.images || []).length) {
      showImage(final.images[0]);
      setStatus("完成，用时 " + ((final.elapsed_ms || 0) / 1000).toFixed(1) + "s", "ok");
      loadHistory();
    } else {
      setStatus(final.error || "生成失败", "bad");
    }
    setProgress(false);
  } catch (err) {
    setStatus("请求失败：" + (err.message || err), "bad");
    setProgress(false);
  } finally {
    state.busy = false;
    el("btn-generate").disabled = false;
  }
}

async function uploadReference(file) {
  if (!file) {
    state.referencePath = "";
    el("ref-preview").hidden = true;
    return;
  }
  if (!/^image\/(png|jpeg|webp)$/.test(file.type)) {
    setStatus("只支持 PNG / JPEG / WebP", "bad");
    return;
  }
  if (file.size > 20 * 1024 * 1024) {
    setStatus("参考图超过 20MB，先压一下", "bad");
    return;
  }
  setStatus("上传参考图…");
  try {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error || new Error("读取失败"));
      reader.readAsDataURL(file);
    });
    const result = await bridge.apiPost("upload", { filename: file.name, data: dataUrl });
    state.referencePath = result.path || "";
    const preview = el("ref-preview");
    preview.hidden = false;
    preview.innerHTML = "";
    const img = document.createElement("img");
    img.src = dataUrl;
    img.alt = "reference";
    preview.appendChild(img);
    setStatus("参考图已就绪", "ok");
  } catch (err) {
    state.referencePath = "";
    setStatus("上传失败：" + (err.message || err), "bad");
  }
}

async function loadHistory() {
  const grid = el("history-grid");
  grid.innerHTML = '<span class="hint">读取中…</span>';
  try {
    const data = await bridge.apiGet("history", { limit: 12 });
    const items = data.items || [];
    grid.innerHTML = "";
    if (!items.length) {
      grid.innerHTML = '<span class="hint">还没有生成记录</span>';
      return;
    }
    for (const item of items) {
      const card = document.createElement("button");
      card.className = "thumb";
      card.title = item.name;
      const img = document.createElement("img");
      img.loading = "lazy";
      img.src = item.data_url || item.url;
      img.alt = item.name;
      card.appendChild(img);
      card.addEventListener("click", () => {
        showImage(item);
        if (item.receipt && item.receipt.ok) showReceipt(item.receipt);
        loadRequestIntoForm(item);
      });
      grid.appendChild(card);
    }
  } catch (err) {
    grid.innerHTML = '<span class="hint">历史读取失败：' + (err.message || err) + "</span>";
  }
}

/* ==================== 设置 ==================== */

function workflowFilesFor(kind) {
  // 目录即类型：selfie 只列 selfie/ 下的文件，以此类推，从机制上避免选错类型
  const prefix = kind + "/";
  return state.files.filter((name) => name.startsWith(prefix));
}

function fillWorkflowSelect(select, current) {
  const kind = String(select.dataset.cfg || "").split(".")[0];
  const files = workflowFilesFor(kind);
  select.innerHTML = "";
  if (!current) {
    // 没配工作流时给一个空选项，避免 <select> 自动选中第一项、保存时把“第一项”当成用户选择
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "（未设置，用默认）";
    select.appendChild(option);
  }
  for (const name of files) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  }
  if (current && !files.includes(current)) {
    const option = document.createElement("option");
    option.value = current;
    option.textContent = current + "（缺失）";
    select.appendChild(option);
  }
  select.value = current || "";
}

function applyConfig(data) {
  state.config = data.config || {};
  // 先填下拉选项、再回填值：<select> 在还没有 option 时赋值会被丢弃，
  // 随后浏览器自动选中第一项，保存就把「列表第一项」写回了配置
  //（早期版本三条链路全被写成 draw-cat.json 的根因）。
  for (const select of document.querySelectorAll("select[data-wf]")) {
    const key = String(select.dataset.cfg || "");
    fillWorkflowSelect(select, getPath(state.config, key));
    if (!select.dataset.bound) {
      select.dataset.bound = "1";
      select.addEventListener("change", () => {
        const kind = key.split(".")[0];
        state.config[kind] = Object.assign({}, state.config[kind] || {}, { workflow: select.value });
        autofillFromWorkflow(kind, select.value);
      });
    }
  }
  for (const input of document.querySelectorAll("[data-cfg]")) {
    const value = getPath(state.config, input.dataset.cfg);
    if (input.type === "checkbox") input.checked = Boolean(value);
    else if (value !== undefined && value !== null) input.value = value;
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

  const group = document.createElement("select");
  for (const pair of [["anime", "动漫系"], ["real", "写实系"], ["other", "其他"], ["", "未分类"]]) {
    const option = document.createElement("option");
    option.value = pair[0];
    option.textContent = pair[1];
    if ((model.group || "") === pair[0]) option.selected = true;
    group.appendChild(option);
  }
  group.addEventListener("change", () => {
    state.models[index].group = group.value;
  });
  const tdGroup = document.createElement("td");
  tdGroup.appendChild(group);

  const desc = document.createElement("input");
  desc.value = model.desc || "";
  desc.placeholder = "一句话定位，如 肤感极佳";
  desc.className = "cell-text";
  desc.addEventListener("input", () => {
    state.models[index].desc = desc.value;
  });
  const tdDesc = document.createElement("td");
  tdDesc.appendChild(desc);

  const wf = document.createElement("select");
  // 模型表只服务文生图：只列 text2img/ 下的文件
  for (const name of state.files.filter((item) => item.startsWith("text2img/"))) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    wf.appendChild(option);
  }
  if (model.workflow) wf.value = model.workflow;
  wf.addEventListener("change", () => {
    state.models[index].workflow = wf.value;
  });
  const tdWf = document.createElement("td");
  tdWf.appendChild(wf);

  const cells = [];
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
    cells.push(td);
  }

  const del = document.createElement("button");
  del.className = "ghost danger";
  del.textContent = model._confirmDelete ? "确认删除" : "删除";
  if (model._confirmDelete) del.classList.add("confirming");
  del.addEventListener("click", () => {
    if (!model._confirmDelete) {
      state.models.forEach((item) => {
        item._confirmDelete = false;
      });
      state.models[index]._confirmDelete = true;
      renderModelTable();
      return;
    }
    state.models.splice(index, 1);
    renderModelTable();
  });
  const tdAction = document.createElement("td");
  tdAction.appendChild(del);

  tr.append(tdEnabled, tdDefault, tdKey, tdLabel, tdGroup, tdDesc, tdWf);
  for (const cell of cells) tr.appendChild(cell);
  tr.appendChild(tdAction);
  return tr;
}

function renderModelTable() {
  const body = el("models-body");
  body.innerHTML = "";
  state.models.forEach((model, index) => body.appendChild(modelRow(model, index)));
  if (!state.models.length) {
    body.innerHTML = '<tr><td colspan="16" class="hint">还没有模型，点「新增模型」</td></tr>';
  }
}

function renderWorkflowTable() {
  const body = el("wf-body");
  body.innerHTML = "";
  const kindMap = {};
  for (const pair of [["selfie", "自拍"], ["reference", "参考图"], ["edit", "编辑"]]) {
    const workflow = (state.config[pair[0]] || {}).workflow;
    if (workflow) kindMap[workflow] = kindMap[workflow] ? kindMap[workflow] + " / " + pair[1] : pair[1];
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
    tdUse.className = "cell-ro";
    const owners = state.usage[name] || [];
    tdUse.textContent = owners.length ? owners.join(", ") : "未被引用";

    const tdKind = document.createElement("td");
    const actions = document.createElement("div");
    actions.className = "kind-actions";
    for (const pair of [["selfie", "自拍"], ["reference", "参考图"], ["edit", "编辑"]]) {
      const kind = pair[0];
      const label = pair[1];
      const active = ((state.config[kind] || {}).workflow || "") === name;
      const compatible = name.startsWith(kind + "/");
      const btn = document.createElement("button");
      btn.className = "ghost" + (active ? " active" : "");
      btn.textContent = active ? "✓ " + label : label;
      btn.disabled = !compatible;
      btn.title = !compatible
        ? "只能指派 " + kind + "/ 目录下的文件"
        : active
          ? "当前已用于" + label
          : "设为" + label + "档工作流";
      btn.addEventListener("click", () => assignKind(kind, name));
      actions.appendChild(btn);
    }
    tdKind.appendChild(actions);

    tr.append(tdName, tdNote, tdUse, tdKind);
    body.appendChild(tr);
  }
  if (!state.files.length) {
    body.innerHTML = '<tr><td colspan="4" class="hint">工作流目录里没有 json，先上传一个</td></tr>';
  }
}

async function autofillFromWorkflow(kind, name) {
  const hint = document.querySelector('[data-inspect-hint="' + kind + '"]');
  if (!kind || !name) return;
  try {
    const data = await bridge.apiGet("workflows/inspect", { name });
    const setVal = (suffix, value) => {
      const input = document.querySelector('[data-cfg="' + kind + "." + suffix + '"]');
      if (input && value !== null && value !== undefined && value !== "") input.value = value;
    };
    setVal("width", data.width);
    setVal("height", data.height);
    setVal("ipadapter_weight", data.ipadapter_weight);
    if (kind === "edit") setVal("denoise", data.denoise);
    if (hint) {
      const size = data.width && data.height ? data.width + "×" + data.height : "沿用源图尺寸";
      const parts = [
        "底模 " + (data.checkpoint || "?"),
        (data.steps ?? "-") + " 步",
        "CFG " + (data.cfg ?? "-"),
        (data.sampler_name || "-") + " / " + (data.scheduler || "-"),
        size,
        data.ipadapter_weight !== null && data.ipadapter_weight !== undefined
          ? "IPA " + data.ipadapter_weight
          : "无 IP-Adapter",
        data.mode === "img2img" ? "图生图" : "文生图",
      ];
      hint.textContent = "@ " + name + " → " + parts.join(" · ") + "（填入后保存生效；这些参数由工作流本身决定）";
    }
  } catch (err) {
    if (hint) hint.textContent = "读取工作流参数失败：" + (err.message || err);
  }
}

function assignKind(kind, name) {
  state.config[kind] = Object.assign({}, state.config[kind] || {}, { workflow: name });
  const select = document.querySelector('select[data-cfg="' + kind + '.workflow"]');
  if (select) select.value = name;
  autofillFromWorkflow(kind, name);
  renderWorkflowTable();
  const labels = { selfie: "自拍", reference: "参考图", edit: "编辑" };
  setStatus("已把 " + name + " 设为「" + (labels[kind] || kind) + "」工作流（记得点保存）", "warn");
}

function renderDiagnostics(items) {
  const list = el("diag");
  list.innerHTML = "";
  if (!items.length) {
    list.innerHTML = '<li class="hint">无</li>';
    return;
  }
  const map = { error: "错误", warn: "注意", info: "提示", ok: "正常" };
  for (const item of items) {
    const li = document.createElement("li");
    li.className = "diag-item " + (item.level || "info");
    const tag = document.createElement("span");
    tag.className = "diag-tag";
    tag.textContent = map[item.level] || "提示";
    li.append(tag, document.createTextNode(item.message || ""));
    list.appendChild(li);
  }
}

function applySettings(data) {
  state.files = data.workflows || [];
  state.notes = data.workflow_notes || {};
  state.usage = data.workflow_usage || {};
  state.paths = data.paths || {};
  state.models = (data.models || []).map((m) => Object.assign({}, m));
  state.originalKeys = new Set(state.models.map((m) => String(m.key || "").trim()).filter(Boolean));
  el("chip-ver").textContent = "v" + (data.version || "?");

  applyConfig(data);
  el("p-wf").textContent = state.paths.workflow_dir || "";
  el("p-models").textContent = state.paths.models_json || "";
  el("p-host").textContent = state.paths.host_plugin_dir || "（填了宿主 data 目录后显示）";

  renderDiagnostics(data.diagnostics || []);
  renderModelTable();
  renderWorkflowTable();
}

async function loadSettings() {
  setStatus("读取中…");
  try {
    const data = await bridge.apiGet("settings");
    applySettings(data);
    state.loadedSettings = true;
    setStatus("已加载", "ok");
  } catch (err) {
    setStatus("读取失败：" + (err.message || err), "bad");
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
        group: item.group || "",
        desc: item.desc || "",
        workflow: item.workflow,
        enabled: item.enabled !== false,
        aliases: item.aliases || [],
        tags: item.tags || [],
      };
    }
    if (!kept.length) throw new Error("至少保留一个模型");
    const deleted = [...state.originalKeys].filter((key) => !kept.includes(key));
    const defaultKey = (state.models.find((m) => m.is_default) || {}).key || kept[0];

    await bridge.apiPost("settings", { config: collectConfig() });
    let data = await bridge.apiPost("models", { models, delete: deleted, default: defaultKey });
    data = await bridge.apiPost("workflows/notes", { notes: state.notes });
    applySettings(data);
    state.loadedSettings = true;
    await loadStatus();
    loadHistory();
    setStatus("已保存并生效（无需重启）", "ok");
  } catch (err) {
    setStatus("保存失败：" + (err.message || err), "bad");
  } finally {
    el("btn-save").disabled = false;
  }
}

async function testBackend() {
  setStatus("测试连接…");
  try {
    const result = await bridge.apiPost("test", {});
    if (result.ok) {
      setStatus("连接正常 · ComfyUI " + (result.version || "?") + " · 显存 " + result.vram_free_gb + "/" + result.vram_total_gb + "G", "ok");
    } else {
      setStatus("连接失败：" + (result.error || "未知原因"), "bad");
    }
  } catch (err) {
    setStatus("测试失败：" + (err.message || err), "bad");
  }
}

function addModel() {
  state.models.push({
    key: "",
    label: "",
    workflow: state.files.filter((name) => name.startsWith("text2img/"))[0] || "",
    enabled: true,
    is_default: state.models.length === 0,
    group: "anime",
    desc: "",
    aliases: [],
    tags: [],
  });
  renderModelTable();
}

async function uploadWorkflow(file) {
  if (!file) return;
  if (file.size > 4 * 1024 * 1024) {
    setStatus("工作流文件超过 4MB", "bad");
    return;
  }
  setStatus("上传 " + file.name + "…");
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
    setStatus("已上传 " + (result.name || file.name), "ok");
  } catch (err) {
    setStatus("上传失败：" + (err.message || err), "bad");
  }
}

/* ==================== 绑定与启动 ==================== */

for (const tab of document.querySelectorAll("#tabs .tab")) {
  tab.addEventListener("click", () => switchTab(tab.dataset.tab));
}

el("btn-generate").addEventListener("click", generate);
el("btn-refresh").addEventListener("click", loadStatus);
el("btn-history").addEventListener("click", loadHistory);
el("kind").addEventListener("change", syncModelHint);
el("reference").addEventListener("change", () => uploadReference(el("reference").files && el("reference").files[0]));
el("prompt").addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") generate();
});

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
  switchTab("generate");
  await loadStatus();
  await loadHistory();
})();

