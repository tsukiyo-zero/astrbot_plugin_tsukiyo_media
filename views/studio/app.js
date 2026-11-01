const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;

const el = (id) => document.getElementById(id);
const ui = {
  status: el("chip-backend"),
  backend: el("backend-status"),
  kind: el("kind"),
  model: el("model"),
  modelHint: el("model-hint"),
  prompt: el("prompt"),
  width: el("width"),
  height: el("height"),
  seed: el("seed"),
  negative: el("negative"),
  generate: el("btn-generate"),
  genHint: el("gen-hint"),
  refresh: el("btn-refresh"),
  historyBtn: el("btn-history"),
  preview: el("preview"),
  meta: el("result-meta"),
  detail: el("prompt-detail"),
  finalPrompt: el("prompt-final"),
  historyGrid: el("history-grid"),
  reference: el("reference"),
  referenceHint: el("reference-hint"),
  refPreview: el("ref-preview"),
};

let defaultModel = "";
let referencePath = "";

function setHint(text, tone = "") {
  ui.genHint.textContent = text || "";
  ui.genHint.dataset.tone = tone;
}

function fmtSize(bytes) {
  if (!bytes) return "";
  if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
}

async function loadStatus() {
  ui.status.textContent = "连接中…";
  ui.status.dataset.tone = "";
  try {
    const data = await bridge.apiGet("status");
    const backend = data.backend || {};
    if (backend.online) {
      ui.status.textContent = `ComfyUI ${backend.version || ""} · 显存 ${backend.vram_free_gb}/${backend.vram_total_gb}G · 队列 ${backend.running}/${backend.pending}`;
      ui.status.dataset.tone = "ok";
    } else {
      ui.status.textContent = `后端离线：${backend.error || "未知原因"}`;
      ui.status.dataset.tone = "bad";
    }
    renderModels(data.models || [], data.default_model || "");
  } catch (err) {
    ui.status.textContent = `状态读取失败：${err.message || err}`;
    ui.status.dataset.tone = "bad";
  }
}

function renderModels(models, fallback) {
  defaultModel = fallback || defaultModel;
  ui.model.innerHTML = "";
  for (const item of models) {
    const option = document.createElement("option");
    option.value = item.key;
    option.textContent = `${item.label}${item.is_default ? "（默认）" : ""}`;
    if (item.key === defaultModel) option.selected = true;
    ui.model.appendChild(option);
  }
  if (!models.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "（无模型，检查 models.json）";
    ui.model.appendChild(option);
  }
  syncModelHint();
}

function syncModelHint() {
  ui.model.disabled = false;
  ui.modelHint.textContent =
    ui.kind.value === "text2img" || ui.kind.value === "auto"
      ? "文生图按此模型出图"
      : "该链路用配置里的工作流，模型下拉不生效";
  const needsRef = ui.kind.value === "reference" || ui.kind.value === "edit";
  ui.referenceHint.textContent = needsRef ? "这个链路必须上传一张图" : "自拍/文生图不需要参考图";
}

function showImage(image) {
  ui.preview.innerHTML = "";
  const img = document.createElement("img");
  img.alt = image.name || "result";
  img.src = image.data_url || image.url;
  ui.preview.appendChild(img);

  const actions = document.createElement("div");
  actions.className = "preview-actions";
  const download = document.createElement("a");
  download.textContent = "下载";
  download.href = image.data_url || image.url;
  download.download = image.name || "tsukiyo.png";
  actions.appendChild(download);
  const size = document.createElement("span");
  size.className = "hint";
  size.textContent = fmtSize(image.size);
  actions.appendChild(size);
  ui.preview.appendChild(actions);
}

function showReceipt(receipt) {
  ui.meta.textContent = receipt.ok
    ? `${receipt.kind || ""} · ${receipt.model_key || ""} · ${(receipt.elapsed_ms / 1000).toFixed(1)}s · seed ${receipt.seed}`
    : `失败：${receipt.error || "未知错误"}`;
  ui.meta.dataset.tone = receipt.ok ? "ok" : "bad";
  if (receipt.positive) {
    ui.detail.hidden = false;
    ui.finalPrompt.textContent = `POS:\n${receipt.positive}\n\nNEG:\n${receipt.negative || ""}`;
  } else {
    ui.detail.hidden = true;
  }
}

async function generate() {
  const prompt = ui.prompt.value.trim();
  if (!prompt) {
    setHint("先写点画面描述", "bad");
    ui.prompt.focus();
    return;
  }
  const kind = ui.kind.value;
  if ((kind === "reference" || kind === "edit") && !referencePath) {
    setHint("参考图 / 编辑需要先上传一张图", "bad");
    ui.reference.focus();
    return;
  }
  ui.generate.disabled = true;
  setHint("生成中…");
  const payload = {
    prompt,
    kind,
    model_key: ui.model.value || "",
    reference_path: referencePath,
    width: Number(ui.width.value) || 0,
    height: Number(ui.height.value) || 0,
    seed: Number(ui.seed.value),
    negative: ui.negative.value.trim(),
  };
  const started = Date.now();
  try {
    const receipt = await bridge.apiPost("generate", payload);
    showReceipt(receipt);
    if (receipt.ok && (receipt.images || []).length) {
      showImage(receipt.images[0]);
      setHint(`完成，用时 ${((Date.now() - started) / 1000).toFixed(1)}s`, "ok");
      loadHistory();
    } else {
      setHint(receipt.error || "生成失败", "bad");
    }
  } catch (err) {
    setHint(`请求失败：${err.message || err}`, "bad");
  } finally {
    ui.generate.disabled = false;
  }
}

async function loadHistory() {
  ui.historyGrid.innerHTML = '<span class="hint">读取中…</span>';
  try {
    const data = await bridge.apiGet("history", { limit: 12 });
    const items = data.items || [];
    ui.historyGrid.innerHTML = "";
    if (!items.length) {
      ui.historyGrid.innerHTML = '<span class="hint">还没有生成记录</span>';
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
      });
      ui.historyGrid.appendChild(card);
    }
  } catch (err) {
    ui.historyGrid.innerHTML = `<span class="hint">历史读取失败：${err.message || err}</span>`;
  }
}

async function uploadReference(file) {
  if (!file) {
    referencePath = "";
    ui.refPreview.hidden = true;
    ui.refPreview.innerHTML = "";
    return;
  }
  if (!/^image\/(png|jpeg|webp)$/.test(file.type)) {
    setHint("只支持 PNG / JPEG / WebP", "bad");
    return;
  }
  if (file.size > 20 * 1024 * 1024) {
    setHint("参考图超过 20MB，先压一下", "bad");
    return;
  }
  setHint("上传参考图…");
  try {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error || new Error("读取失败"));
      reader.readAsDataURL(file);
    });
    const result = await bridge.apiPost("upload", { filename: file.name, data: dataUrl });
    referencePath = result.path || "";
    ui.refPreview.hidden = false;
    ui.refPreview.innerHTML = "";
    const img = document.createElement("img");
    img.src = dataUrl;
    img.alt = "reference";
    ui.refPreview.appendChild(img);
    setHint("参考图已就绪", "ok");
  } catch (err) {
    referencePath = "";
    setHint(`上传失败：${err.message || err}`, "bad");
  }
}

ui.generate.addEventListener("click", generate);
ui.refresh.addEventListener("click", loadStatus);
ui.historyBtn.addEventListener("click", loadHistory);
ui.kind.addEventListener("change", syncModelHint);
ui.reference.addEventListener("change", () => uploadReference(ui.reference.files && ui.reference.files[0]));
ui.prompt.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") generate();
});

(async () => {
  try {
    await bridge.ready();
  } catch (err) {
    console.warn("bridge ready failed", err);
  }
  await loadStatus();
  await loadHistory();
})();
