# Changelog

遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

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
