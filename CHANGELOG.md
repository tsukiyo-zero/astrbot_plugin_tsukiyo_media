# Changelog

遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [0.5.1] - 2026-11-02

### 新增
- 三档工作流**切换时自动带入作者参数**：新接口 `GET /workflows/inspect` 解析工作流里的 steps/cfg/sampler/scheduler/尺寸/IP-Adapter 权重，切换下拉即填到下面的输入框（并提示"保存后生效"）
- 模型表采样器/调度器改为**可下拉选择**（datalist 同时允许手填自定义值）
- 工作流表「当前用于」列改为**快捷按钮**：直接点「自拍 / 参考图 / 编辑」把该文件设为对应档，不用再上去找下拉

### 修复
- 模型表**点「删除」没反应**：iframe 里 `confirm()` 被浏览器沙箱拦截、静默返回 false；改成按钮两步确认（再点一次才删）
- 工作流表里只读单元（被引用、当前用于）看起来和可编辑的一样 → 加 `.cell-ro` 弱化样式，确认删除按钮加红框

## [0.5.0] - 2026-11-02

### 修复
- **点页签后报「Token 无效」**：AstrBot 的插件页面 token 是按路径授权的（`is_scope_valid(payload, path)`），跨视图复用必然失效。改为**单一视图 + 页面内页签**，删掉独立的 settings 视图

### 新增
- **生成进度**：新接口 `POST /generate/stream`（SSE），提交后立刻推 prompt_id，随后推「排队中/生成中/收尾中」和耗时，页面显示进度条与阶段
- **历史持久化**：每次生成写入插件数据目录 `history.json`（保留 60 条），重启后 Studio 仍能看到缩略图与参数；`GET /history` 改读持久化记录
- 生成页与设置页合并为一个视图，顶部只保留「生成 / 设置」两个页签

## [0.4.0] - 2026-11-02

### 新增
- 设置页重做：**模型表格可直接增删改**（label / 工作流 / steps / cfg / 尺寸 / 采样器 / 调度器 / 别名 / 标签 / 启用 / 默认），保存即写回 `models.json`
- **上传工作流**：页面直接传 ComfyUI API 格式 JSON 到 `workflows/`，可选覆盖；上传前校验必须是 API 格式
- **工作流说明**：每个工作流可写一句备注（存插件数据目录的 `workflow_notes.json`，不动你的工作流文件），并显示"被哪些模型使用 / 用于哪一档"
- 顶部**页签**：生成 / 设置 两个视图互相跳转（沿用 Dashboard 的 path token，不破坏鉴权）
- 头部明确标注**后端类型**（当前仅「ComfyUI（本地 HTTP）」，在线 API 在路线图）

### 修复
- 输入框与面板同色，看起来像只读 → 输入框改用更亮的底色 + hover/focus 描边，只读态用虚线边框区分
- 复制按钮在 iframe 里报"复制失败" → 先试 `navigator.clipboard`，再降级 `execCommand('copy')`，都失败才提示手动选中

## [0.3.1] - 2026-11-02

### 新增
- 设置页顶部**上手引导**：解释"模型 / 工作流 / 后端"三个概念，并给出插件目录、工作流目录、models.json 的实际路径（容器 + 宿主，可复制）
- 设置页**自检**：地址是否填错（容器里填 127.0.0.1 会提醒）、工作流目录/文件缺失、模型引用的工作流不存在、全部模型被停用、出图目录不可写、自拍参考图未配、未被引用的工作流
- 设置页**工作流文件表**：列出目录下所有 json，以及各自被哪些模型使用
- Studio 顶部提示条：后端离线或没有可用模型时，直接告诉你该去哪儿改

## [0.3.0] - 2026-11-02

### 新增
- **设置页** `views/settings`：后端连接（含一键测试）、生成默认参数、自拍/参考图/编辑三档工作流与权重、路径配置（含宿主机路径映射）、模型表
- 模型可**启用/停用**、可单独指定工作流、可切换默认模型；停用模型不参与选模
- 保存后**热重建运行时**（`AstrBotConfig.save_config` + 重装 pipeline），不需要重启进程
- 新 API：`GET/POST /settings`、`POST /models`、`GET /workflows`、`POST /test`

### 修复
- Studio 在"文生图/自拍"链路上不再显示参考图上传框（只有参考图/编辑才显示）

## [0.2.1] - 2026-11-02

### 变更
- 显示名改为 **月夜绘影**，插件系列统一「月夜」前缀（后续插件命名 `月夜XX`）
- `metadata.author` 改为稳定包身份 `tsukiyo-zero`（原 `Mio (tsukiyo-zero)` 含空格括号，会让市场 `plugin_id` 不规范）
- 补齐市场元数据：`logo.png`（256×256）、`tags`、`social_link`

## [0.2.0] - 2026-11-02

### 新增
- **可视化页面** `views/studio`：后端状态（版本/显存/队列）、模型下拉、链路选择、提示词与高级参数、参考图上传与预览、生成并预览、最近生成缩略图、实际提交提示词展开
  - 后端 API：`GET /status`、`POST /generate`、`POST /upload`（base64 JSON）、`GET /history`、`GET /file`（仅允许读产物/参考图目录）
  - 通过 `window.AstrBotPluginView` bridge 调用，无需 Dashboard 改前端
- 自拍档 `identity_prompt` 默认值填了一个**示例角色**（蓝发鲸鱼娘），改成自己角色即可

### 变更
- `workflows/selfie-ref.json` **去人设化**：只保留作者质量词，人物特征移到配置（`selfie.identity_prompt`），仓库可作为通用模板
- 工作流文件改中性名：`selfie-ref.json` / `reference-ref.json` / `edit-img2img.json`

## [0.1.0] - 2026-11-02

首个可运行版本（仓库名 `astrbot_plugin_tsukiyo_media`，显示名「月夜绘影」，作者 Mio / tsukiyo-zero）。

### 新增
- ComfyUI HTTP 客户端：`/prompt`、`/history/{id}`、`/view`、`/upload/image`、`/queue`、`/interrupt`
- 工作流**图结构绑定**（`binder.py`）：顺着 `KSampler` 连线推断正/负向、latent、save，自动识别 IP-Adapter 身份参考图与 img2img 源图；不写死 node id
- 后端契约 `backends/base.py`：`MediaBackend` / `RenderPlan` / `Asset`，为在线 API 与视频预留扩展点
- 四条链路：`text2img` / `selfie` / `reference` / `edit`
- 模型目录 `models.json`：`author_params` 默认只读、支持别名与标签、热重载（`/img reload`）
- 自动选模：风格关键词 → 模型；显式 `model=` 优先；无命中回落默认
- 提示词层：负权重语法清洗、标签清洗、上游规则段落清洗、可选中文子句丢弃、按逗号去重追加
- 命令：`/img`、`/img models|status|last|reload|selfie|edit|ref`
- LLM 工具 `tsukiyo_image_generate`，可直接被陪伴类插件的 `tool_call` 后端调用
- 单元测试 33 项（binder / router / prompt），`scripts/smoke.py` 真机冒烟

### 已知限制
- 生成历史只保存在内存，重启后 `/img last` 不可用
- `routing.mode=llm` 尚未实现（当前只有规则路由）
- 引用消息中的图片暂未自动解析（只取本轮消息里的图）
