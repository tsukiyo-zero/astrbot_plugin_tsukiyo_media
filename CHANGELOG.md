# Changelog

遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-11-02

首个可运行版本（仓库名 `astrbot_plugin_tsukiyo_media`，显示名「月夜工坊」，作者 Mio / tsukiyo-zero）。

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
