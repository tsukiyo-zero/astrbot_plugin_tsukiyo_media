# astrbot_plugin_tsukiyo_media · 月夜绘影

一个**低耦合**的 AstrBot 生成插件：把「一段描述」变成「一张图」（后续扩展到视频）。

- 后端可换：现在手动配置本地 ComfyUI（HTTP API），预留在线 API 后端
- 四条链路：文生图 · 自拍（IP-Adapter 身份参考）· 编辑（img2img）· 参考图生图
- 模型：目录文件驱动，自动按描述选模，也能手动 `model=xxx`
- 工作流：**按图结构自动绑定节点**，不写死 node id、不依赖节点标题，换工作流不用改代码
- 出图参数默认沿用**作者参数**（steps/cfg/sampler/尺寸），要改才改
- 不依赖任何陪伴/人格类插件，也不向它反向 import

## 设计边界

| 属于本插件 | 不属于本插件 |
|---|---|
| 后端通信（ComfyUI / 在线 API）、队列、超时 | 人格、好感度、关系 |
| 工作流绑定与参数回填 | 日程、场景状态、穿搭模板 |
| 提示词清洗与拼接 | 主动消息、发送策略 |
| 产物落盘、返回路径 | 陪伴面板、记忆 |

一句话：**本插件不回答「要不要生成」，只回答「怎么生成」。**

## 安装

```bash
cd /AstrBot/data/plugins
git clone https://github.com/tsukiyo-zero/astrbot_plugin_tsukiyo_media.git
# 依赖：httpx（AstrBot 已自带，一般无需安装）
```

在 AstrBot 面板启用插件，填好 ComfyUI 地址（本机 `http://127.0.0.1:8188`；Docker 里跑 AstrBot 时用 `http://host.docker.internal:8188`）。

## 命令

```
/img models                     列出模型（* 为默认）
/img status                     ComfyUI 版本 / 显存 / 队列
/img last                       上一张图的参数与产物路径
/img reload                     重载模型目录与工作流（管理员）
/img 一只在屋顶睡觉的橘猫          自动判断：文生图
/img selfie 海边散步，黄昏逆光      自拍档：人设参考图 + IP-Adapter
/img ref 换成夜景                 参考图生图（需带图）
/img edit 把衣服换成蓝色            编辑（需带图）
/img model=miao 像素风房间          手动选模
/img size=832x1216 seed=123 ...   覆盖尺寸 / 种子
```

## 可视化页面

启用插件后，AstrBot WebUI → **插件** → **月夜绘影**，有两个视图：

### Studio（生成）

- 看后端状态：ComfyUI 版本、显存占用、队列长度（离线时直接显示原因）
- 选链路（自动 / 文生图 / 自拍 / 参考图 / 编辑）与模型
- 填提示词、尺寸、种子、额外负向词，一键生成并预览；参考图/编辑链路才显示上传框
- 展开看**实际提交给 ComfyUI 的完整正负向词**（排查问题不用翻日志）
- 最近 12 张缩略图，点开可查看/下载

### 设置（Settings）

- 后端连接：地址、连接/出图超时、轮询间隔 + **一键测试连接**
- 生成默认：全局负向词、作者词拼接方式、并发、文件前缀、是否丢弃中文
- 三档参数：自拍 / 参考图 / 编辑各自的工作流、固定词、IPA 权重、尺寸（工作流用下拉选，不用手打文件名）
- 路径：工作流目录、出图目录、**宿主机 data 目录**（填了之后能显示并复制宿主路径，方便在资源管理器里打开）
- 模型表：逐个**启用/停用**、设默认、给每个模型换工作流
- 保存后**热重建运行时**（不重启 AstrBot）；停用的模型不会出现在生成页，也不会被自动选模命中

页面由 `views/studio/`、`views/settings/` 提供，后端接口在 `page_api.py`；路由前缀固定为 `/<插件名>`，
前端通过 `window.AstrBotPluginView` 的 `apiGet` / `apiPost` 调用，不需要改 AstrBot 前端。

## LLM 工具

插件向 AstrBot 注册函数工具 `tsukiyo_image_generate`，聊天模型可自行调用：

```python
tsukiyo_image_generate(
    prompt="1girl, beach, sunset",   # 英文 tag，逗号分隔
    kind="auto",                     # auto/selfie/edit/reference/text2img
    model_key="",                    # 仅文生图生效
    reference_image_path="",         # 通常留空，自动取本轮图片
    caption="",                      # 随图发送的一句话
    send=True,
)
```

返回 JSON 回执：`{ok, kind, model_key, workflow, paths, elapsed_ms, prompt_id, seed, sent, error}`。

### 与陪伴类插件解耦

陪伴插件的配置里有 `photo_generation_backend = tool_call` + `custom_photo_tool_name`，
把后端切成 `tool_call` 并把工具名填成 `tsukiyo_image_generate`，**不需要改任何插件代码**就能用本插件顶替原有生图内核。
（参数名可配：`custom_photo_tool_prompt_param=prompt`、`custom_photo_tool_kind_param=kind`、`custom_photo_tool_reference_param=reference_image_path`）

## 模型目录 `models.json`

不写代码就能加模型：

```json
{
  "default": "obsession",
  "models": {
    "miao": {
      "label": "miao 柔光",
      "workflow": "draw-miao.json",
      "aliases": ["柔光", "miao"],
      "tags": ["写实", "柔光"],
      "author_params": {
        "steps": 30, "cfg": 4.5,
        "sampler_name": "euler_ancestral", "scheduler": "exponential",
        "width": 832, "height": 1216
      }
    }
  }
}
```

- `enabled`：是否启用（停用后不出现在生成页，也不会被自动选模命中）
- `workflow`：相对 `workflows/` 的文件名
- `author_params`：**默认只读**，只有显式给 `--override` 语义或改这里才会变
- `aliases`：`model=柔光` 也能命中

改完 `/img reload` 生效（普通用户不可用，需管理员）。

## 工作流绑定原理

不靠 node id（`"14"`、`"25"` 这种一改工作流就崩），而是**顺着采样器的连线反查**：

| 角色 | 定位方式 |
|---|---|
| sampler | 唯一的 `KSampler` / `KSamplerAdvanced` |
| positive / negative | 顺着 `sampler.inputs.positive` / `.negative` 的连线 |
| latent | 顺着 `latent_image`：`EmptyLatentImage`（文生图）或 `VAEEncode`（图生图） |
| save | 唯一的 `SaveImage` |
| 身份参考图 | 从 `IPAdapter*.inputs.image` 往上找 `LoadImage` |
| 源图 | 从 `VAEEncode.inputs.pixels` 往上找 `LoadImage`（可穿过 `ImageScale`） |

**约束**：工作流必须是 ComfyUI **API 格式**（`节点id → {class_type, inputs}`），且采样器、保存节点唯一。
不满足会直接报错，而不是猜一个节点用——这比「悄悄出错图」好排查得多。

## 提示词拼接

- `prompt_mode=append`（默认）：工作流里的作者词保留，本次描述**按逗号去重追加**
- `prompt_mode=replace`：完全用插件拼的词覆盖作者词
- 自动清洗：负权重语法 `-1.5::…::`、`Positive prompt:` 之类标签、上游规则段落（`Image edit contract:` 等）
- `strip_non_english=true` 时丢弃含中文的子句（CLIP 读不懂中文，但中文描述也会被丢，慎用）

## 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 中文描述没效果 | CLIP 只认英文 tag；让调用方先转成英文 tag，或开 `strip_non_english` 至少不占 token |
| 报「工作流里找不到/多个采样器」 | 工作流不是 API 格式，或含多个 `KSampler`；先用 ComfyUI 的「导出 (API)」 |
| 参考图上传失败 | ComfyUI `/upload/image` 对超大图不友好；本插件会自动按原文件上传，超大图建议先压到 2MB 内 |
| Docker 里连不上 ComfyUI | 用 `http://host.docker.internal:8188`，别用 `127.0.0.1` |
| 出图颜色偏艳 / 脚崩 | 那是底模作者词的问题，调 `author_params` 或在 `generation.negative_prompt` 里加压制词 |

## 开发

```bash
# 单元测试（不联网、不需要 GPU）
python -m unittest discover -s tests -p "test_*.py"

# 真机冒烟（会真的出图）
python scripts/smoke.py --base-url http://127.0.0.1:8188 --prompt "a cat on a roof"
python scripts/smoke.py --kind selfie --reference ./ref.png --prompt "sitting on bed"
```

目录结构：

```
main.py / api.py            AstrBot 入口与对外 API（TsukiyoMediaAPI）
page_api.py                 可视化页面的后端 API（status / generate / history / file）
views/studio/               WebUI 里的 Studio 页面（index.html + app.js + style.css）
core/                       纯逻辑：types / catalog / router / prompt / pipeline
backends/base.py            后端契约：MediaBackend / RenderPlan / Asset（多后端扩展点）
backends/comfyui/           client（HTTP）+ binder（节点绑定）
workflows/                  随插件发布的工作流（API 格式）
models.json                 模型目录
docs/architecture.md        架构与多后端演进计划
tests/                      不依赖网络的单元测试
```

## 多后端演进

插件的定位是**低耦合 + 可扩展**，所以后端从一开始就留了口：

| 阶段 | 后端 | 说明 |
|---|---|---|
| v0.1 | ComfyUI | 手动配置 `comfyui.base_url`，走本地 HTTP |
| v0.2（当前） | ComfyUI + 可视化页面 | Studio 页面可看状态、选模型、生成、看历史 |
| v0.3 | 在线图片 API | 新增 `backends/openai_image/`，实现同一个 `MediaBackend` 契约 |
| v0.4 | 视频 | 增加 `modality=video`，`Asset` 已预留视频元数据字段 |

`backends/base.py` 里的 `MediaBackend` 就是那条缝：实现 `health / render / close` 三件套即可接入，
流水线、命令、提示词层都不用改。详见 `docs/architecture.md`。

## Roadmap

- [x] v0.1 文生图 / 自拍 / 参考图 / 编辑 / 自动与手动选模（ComfyUI 后端）
- [x] v0.2 可视化页面（状态 / 选模 / 生成 / 历史）；工作流去人设化
- [x] v0.3 设置页（连接 / 默认参数 / 三档工作流 / 路径 / 模型启用与默认）+ 保存热重建
- [ ] v0.3 抽出 `MediaBackend` 并落地在线 API 后端（`backends/openai_image`）
- [ ] v0.3 生成历史持久化（重启后 `/img last` 与 Studio 历史仍可用）
- [ ] v0.4 视频生成（`modality=video`）
- [ ] v0.4 LLM 辅助选模（`routing.mode=llm`，规则兜底）
- [ ] v0.5 任务队列与取消、并发上限可视化
- [ ] v0.6 hires 二次细化、局部重绘（SAM）

## 致谢

- 随插件附带的工作流模板与各底模的**作者参数**（steps / cfg / sampler / scheduler / 尺寸），
  来自我们此前使用的 [`astrbot_plugin_image_companion`](https://github.com/menglimi/astrbot_plugin_image_companion)（作者 menglimi）的配置；
  底模与采样参数的版权归各模型作者，本仓库只做参数整理与结构绑定
- 插件可视化视图的 bridge 用法与 Web API 约定，参照 AstrBot 官方文档
  [插件可视化视图](https://docs.astrbot.app/dev/star/guides/plugin-pages.html)
- 插件目录/metadata/依赖约定遵循 [插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)

## License

MIT
