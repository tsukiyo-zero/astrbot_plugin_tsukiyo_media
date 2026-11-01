# 架构与多后端演进

## 目标

一个**低耦合**的生成插件：能连本地 ComfyUI，也能连在线 API，以后还能出视频；
不做陪伴面板、不持有任何人设/关系/日程状态。

## 分层

```
main.py            AstrBot 适配层：命令解析、图片收集、发送
api.py             TsukiyoMediaAPI：对外唯一门面（别的插件/上层只依赖它）
core/              纯业务，零 AstrBot 依赖
  types.py         ImageRequest / PromptBundle / ImagePlan / GenerationResult
  catalog.py       models.json：模型 → 工作流 + 作者参数（只读）
  router.py        kind 路由（selfie/edit/reference/text2img）+ 自动选模
  prompt.py        清洗（负权重/标签/规则段）+ 按逗号去重追加
  pipeline.py      路由 → 选模 → 拼词 → 绑定 → 提交 → 取图 → 落盘
backends/
  base.py          MediaBackend / RenderPlan / Asset  ← 多后端扩展点
  comfyui/         client.py（HTTP）+ binder.py（图结构绑定）
```

依赖方向单向：`main → api → core → backends`，没有任何反向 import，也没有跨插件 import。

## 三个关键设计

### 1. 工作流绑定靠图结构，不靠 node id

`binder.resolve_roles()` 从唯一的 `KSampler` 出发，顺着 `positive` / `negative` / `latent_image`
的连线反查节点；IP-Adapter 的身份参考图、`VAEEncode` 的源图分别向上溯源到 `LoadImage`。

好处：作者重排节点、改标题、换工作流，插件不用改代码。
代价：要求工作流是 ComfyUI **API 格式**，且采样器/保存节点唯一——不满足直接报错，不猜。

### 2. 作者参数默认只读

`models.json` 里每个模型带 `author_params`（steps/cfg/sampler/scheduler/尺寸），
只有显式传入 `sampler_override` 才覆盖，且白名单限定四个字段。
这条把“换底模照抄作者参数”从口头约定变成了结构约束。

### 3. 提示词分段、可审计

`PromptBundle.parts` 记录每段来源（identity / fixed / user / extra），
`GenerationResult.positive/negative` 存的是**真正提交给 ComfyUI 的全文**，
可以直接和 `/history` 对照，排查“谁塞了这套衣服”这类问题不需要翻代码。

## 多后端怎么接

`backends/base.py` 定义契约：

```python
class MediaBackend(Protocol):
    name: str
    capabilities: set[str]
    async def health(self) -> dict: ...
    async def render(self, plan: RenderPlan) -> list[Asset]: ...
    async def close(self) -> None: ...
```

接入一个新后端 = 实现这三件套 + 在配置里注册 + 在 `models.json` 里给模型标 `backend` 字段。

`RenderPlan` 只描述“要什么”（正负词、尺寸、种子、参考图），不描述“怎么调 HTTP”，
所以在线 API 后端不需要伪造 ComfyUI 的 submit/wait 语义。

### 演进步骤（v0.2）

1. 把 `pipeline._run()` 里的 ComfyUI 调用移到 `backends/comfyui/backend.py`（`ComfyUIBackend.render`）
2. `ImagePipeline` 改为持有 `MediaBackend`，按 `models.json` 的 `backend` 字段选后端
3. 新增 `backends/openai_image/`，实现 `render` 时走 `/v1/images/generations`
4. 配置从 `comfyui: {...}` 升级为 `backends: {comfyui_local: {...}, api_remote: {...}}` + `routing.default_backend`
5. 配置迁移：保留旧键读取，写新键（`schema_version` 自增），不破坏老用户

### 视频（v0.3）

- `ImageRequest.modality = "video"`，`Asset.modality = "video"` + `meta{duration,fps}`
- ComfyUI 侧用 `SaveVideo` / `VHS_VideoCombine` 节点，binder 增加 `video_save` 角色
- 命令/工具层加 `tsukiyo_video_generate`，与 `tsukiyo_image_generate` 并列

## 不做什么

- 不存人格、关系、好感度
- 不写调度器（主动消息、定时）
- 不做面板/前端（AstrBot 自带的配置页够用）
- 不在插件里直接发消息给非本会话对象（发送只针对当前 event）

保持这些“不做”，插件才能长期只赚功能、不涨耦合。
