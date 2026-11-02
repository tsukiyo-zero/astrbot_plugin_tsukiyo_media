# Changelog

遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [0.0.0] - 开发中

> 项目仍在内测，**尚未发布版本号**：`0.1.0`–`0.6.5` 是早期快速迭代时的临时编号，不代表成熟度，保留在下方仅作历史记录。正式发版前统一记在 0.0.0 下。

### 新增
- **工作流按链路分目录**：`workflows/text2img|selfie|reference|edit/`，目录即类型——自拍只能读 `selfie/`，页面下拉按目录过滤，从机制上杜绝“自拍选中 `draw-*` 导致参考图静默失效”
- **选模型 = 选文件**：`<链路>/<模型>.json` 优先，没有就退回三档里配置的那个文件（不再有 `default.json` 这种重复概念——配置选谁，谁就是默认）。参数、作者词、底模全部只存在于工作流文件里，**不再运行时覆盖**。首批自拍变体：`selfie/obsession.json`、`selfie/miao.json`、`selfie/novaflat.json`
- 链路模板移到 `templates/`（`selfie.json` / `reference.json` / `edit.json`），只供生成脚本使用，不参与运行时扫描
- 新增 `scripts/build_chain_workflows.py`：从模型的 `text2img/` 工作流里取底模、作者正负向词、步数/CFG/采样器，灌进链路模板生成变体，避免手工复制
- 三档设置去掉 IPA / 宽高 / 重绘强度输入（这些归工作流文件），只保留：工作流、人设词、固定词、人设参考图；**「默认模型」也去掉**——工作流下拉选哪个文件，哪个就是默认
- **自拍 / 参考图 / 编辑也能用「模型」换画风**：工作流结构保持专用（IP-Adapter / img2img 不变），底模换成所选模型工作流里的 checkpoint，步数 / CFG / 采样器 / 尺寸跟该模型的作者参数走；不选模型时行为与之前完全一致
- **选模型时作者正负向词一起跟随**：这三条链路不再固定用 `selfie-ref.json` 里那套 obsession 作者词，而是取所选模型 `draw-*.json` 的 pos/neg；人设词、固定提示词、你的描述仍追加在后面。以前选 `miao` 跑自拍，底模换了但作者词还是 obsession 的（`bad feet`、`pale_skin` 都不会进来）
- 新增 `tests/test_pipeline.py`（`build_plan` / checkpoint / 作者词解析 / 目录逃逸），并在 `tests/test_binder.py` 加底模与作者词覆盖用例
- **自拍档「默认模型」**：设置页三档的「自拍」里多一个模型下拉（存 `selfie.model`）。QQ 自拍、`/img selfie`、`tsukiyo_image_generate` 没显式传 `model_key` 时用它（底模 + 作者词 + 参数一起换）；页面生成仍以页面选的模型为准；默认模型被删/停用会自动退回工作流自带参数，不阻塞出图

### 修复
- **设置页保存会把三档工作流写坏**：`applyConfig()` 先给 `<select>` 赋值、后填 `<option>`，值被丢弃后浏览器自动选中列表第一项（`draw-cat.json`），点保存就把「自拍 / 参考图 / 编辑」全写成纯文生图，参考图被静默忽略。改为**先填选项、再用配置值回填**；未配置时插入空选项「（未设置，用默认）」，不再把第一项当成用户选择
- 「三档工作流」下拉的 change 事件同步写回 `state.config`，避免页面上改了但状态里还是旧值
- **页面点「生成」报 `Failed to fetch`**：AstrBot 的插件页 iframe 是 `sandbox="allow-scripts allow-forms allow-downloads"`（**没有 `allow-same-origin`**），页面里直接 `fetch()` 属于跨域请求，被浏览器拦掉；只有走 `bridge` 由父页面同源代发才行。改为 `bridge.apiPost("generate", …)`，进度条退化为本地计时（拿不到 SSE 逐秒进度），`POST /generate` 响应补上 `positive` / `negative`，仍能看到实际提交的正负向词

## [0.6.4] - 2026-11-02

### 新增
- 模型表新增「分类」下拉（动漫系 / 写实系 / 其他 / 未分类）与「定位」文本框，直接写回 `models.json` 的 `group` / `desc`，改完图鉴文案立即生效

## [0.6.3] - 2026-11-02

### 优化
- `/img 模型` 改为**模型图鉴**排版：默认模型单独拎出（⭐ + 风格/适用），其余按「动漫系 / 写实系」分组，每个模型给一句定位，末尾给用法示例
- `models.json` 每条新增 `group`（anime/real）与 `desc`（一句话定位），图鉴内容由数据驱动，改 JSON 就能改文案
- 新增 `tests/test_gallery.py`（分组/默认/树形/停用标记）

## [0.6.2] - 2026-11-02

### 优化
- `/img 模型` 列表重排：`★ key  名称  标签` 三列对齐，去掉重复的别名/名称前缀，并在末尾给用法示例
- 设置页「三档工作流」每档加了**参数摘要**：切换工作流后显示该工作流自带的底模、步数、CFG、采样器/调度器、尺寸、IP-Adapter 权重、结构类型，明确“这些由工作流本身决定”

## [0.6.1] - 2026-11-02

### 修复
- **`/draw`、`/画图`、`/img` 全部失效**：v0.5.2 起把三个 `@filter.command` 叠在同一个函数上，而 AstrBot 的 handler 过滤器是 **AND** 关系（`waking_check/stage.py`），等于要求消息同时等于三个命令，永远匹配不上。改为单命令 + `alias={"画图", "draw"}`
- 新增启动自检日志 `[TsukiyoMedia] 命令已注册: img(draw, 画图)`，以及 `tests/test_commands.py` 防止再叠装饰器

## [0.6.0] - 2026-11-02

### 新增
- **历史可重跑**：点 Studio 里的缩略图，会把当时的原始请求（描述/链路/模型/尺寸/种子/负向词）填回生成页，点生成即可复现
- 生成记录新增 `request` 字段，保存的是**用户原始请求**（不是拼接后的最终提示词）
- 模型表下面加「采样器 / 调度器怎么选」说明（euler_ancestral / dpmpp_2m / lcm / karras 等各自适合什么）
- **参考图自动压缩**：>2MB 或最长边 >1536 的图，上传前自动缩到 1536 并转 JPEG（q88），避免大图上传慢/失败；PIL 缺失时自动跳过

## [0.5.3] - 2026-11-02

### 新增
- `/draw` 兼容命令：与 `/img`、`/画图` 等价；额外支持旧插件写法 `/draw <模型key> <描述>`（首词命中模型 key/别名时自动选模）

## [0.5.2] - 2026-11-02

### 新增
- 命令中文别名：`/img 帮助`、`/img 模型`、`/img 状态`（原来只认英文 help/models/status）
- 新增 `/画图` 命令，与 `/img` 等价（中文用户不用记英文命令）

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
